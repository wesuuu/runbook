"""Graph processing utilities for protocol/run graphs.

Provides topological sorting, connected component discovery,
and role/step extraction from graph JSONB data.
"""


def _topo_sort_nodes(
    component_ids: set[str],
    edges: list[dict],
    node_map: dict[str, dict],
) -> list[dict]:
    """Topologically sort nodes within a connected component.

    Falls back to x-position ordering for nodes at the same depth
    or when cycles exist.
    """
    directed: dict[str, list[str]] = {nid: [] for nid in component_ids}
    in_degree: dict[str, int] = {nid: 0 for nid in component_ids}
    for e in edges:
        src, tgt = e.get("source"), e.get("target")
        if src in component_ids and tgt in component_ids:
            directed[src].append(tgt)
            in_degree[tgt] = in_degree.get(tgt, 0) + 1

    # Kahn's algorithm — use x-position to break ties
    def _x(nid: str) -> float:
        return node_map[nid].get("position", {}).get("x", 0)

    queue = sorted(
        [nid for nid in component_ids if in_degree[nid] == 0],
        key=_x,
    )
    result: list[str] = []
    while queue:
        curr = queue.pop(0)
        result.append(curr)
        for neighbor in directed[curr]:
            in_degree[neighbor] -= 1
            if in_degree[neighbor] == 0:
                queue.append(neighbor)
                queue.sort(key=_x)

    # Remaining nodes (cycles) — append sorted by x-position
    visited = set(result)
    for nid in sorted(component_ids - visited, key=_x):
        result.append(nid)

    return [node_map[nid] for nid in result]


def _find_connected_components(
    unit_ops: list[dict],
    edges: list[dict],
) -> list[list[dict]]:
    """Group unit-op nodes into connected components based on edges.

    Each component is topologically sorted by edge direction,
    with x-position as tie-breaker.
    """
    node_map = {n["id"]: n for n in unit_ops}
    unit_op_ids = set(node_map.keys())

    # Build undirected adjacency for component discovery
    adj: dict[str, set[str]] = {nid: set() for nid in unit_op_ids}
    for e in edges:
        src, tgt = e.get("source"), e.get("target")
        if src in unit_op_ids and tgt in unit_op_ids:
            adj[src].add(tgt)
            adj[tgt].add(src)

    # BFS to find components
    visited: set[str] = set()
    components: list[list[dict]] = []
    for nid in unit_op_ids:
        if nid in visited:
            continue
        comp_ids: set[str] = set()
        queue = [nid]
        while queue:
            curr = queue.pop(0)
            if curr in visited:
                continue
            visited.add(curr)
            comp_ids.add(curr)
            for neighbor in adj[curr]:
                if neighbor not in visited:
                    queue.append(neighbor)
        sorted_nodes = _topo_sort_nodes(comp_ids, edges, node_map)
        components.append(sorted_nodes)

    # Sort components by the x-position of their first node
    components.sort(
        key=lambda c: c[0].get("position", {}).get("x", 0) if c else 0,
    )
    return components


def _parse_graph_roles_and_steps(graph: dict) -> tuple[list[dict], list[dict], bool]:
    """Extract roles and ordered steps from a protocol/run graph.

    Returns:
        (roles_with_steps, flat_steps, is_role_based) where roles_with_steps
        is a list of dicts with role_name and steps, flat_steps is all steps
        with role_name attached (for batch record), and is_role_based indicates
        whether grouping is swimlane-based (True) or process-based (False).
    """
    nodes = graph.get("nodes", [])
    edges = graph.get("edges", [])

    unit_ops = sorted(
        [n for n in nodes if n.get("type") == "unitOp"],
        key=lambda n: n.get("position", {}).get("x", 0),
    )
    process_starts = [n for n in nodes if n.get("type") == "processStart"]
    swim_lanes = {
        n["id"]: n for n in nodes if n.get("type") == "swimLane"
    }

    # Check if any unitOps are parented to swimlanes
    any_parented = any(
        n.get("parentId") and n["parentId"] in swim_lanes
        for n in unit_ops
    )

    def _step_dict(node: dict, role_name: str) -> dict:
        data = node.get("data", {})
        return {
            "id": node["id"],
            "name": data.get("label", "Unnamed"),
            "description": data.get("description", ""),
            "params": data.get("params"),
            "param_schema": data.get("paramSchema"),
            "duration_min": data.get("duration_min"),
            "role_name": role_name,
        }

    def _find_process_start_for_component(
        comp_node_ids: set[str],
    ) -> dict | None:
        """Find the processStart node connected to a component."""
        for ps in process_starts:
            if ps["id"] in comp_node_ids:
                return ps
        return None

    roles_with_steps: list[dict] = []
    flat_steps: list[dict] = []

    if any_parented and swim_lanes:
        # Group by swimlane
        for lane_id, lane in swim_lanes.items():
            lane_name = lane.get("data", {}).get("label", "Unknown Role")
            lane_ops = [
                n for n in unit_ops if n.get("parentId") == lane_id
            ]
            lane_steps = [_step_dict(n, lane_name) for n in lane_ops]

            # Check for processStart parented to this lane
            lane_ps = [
                ps for ps in process_starts
                if ps.get("parentId") == lane_id
            ]
            process_name = ""
            process_description = ""
            if lane_ps:
                ps_data = lane_ps[0].get("data", {})
                process_name = ps_data.get("label", "")
                process_description = ps_data.get("description", "")

            if lane_steps:
                entry: dict = {
                    "role_name": lane_name,
                    "steps": lane_steps,
                }
                if process_name:
                    entry["process_name"] = process_name
                    entry["process_description"] = process_description
                roles_with_steps.append(entry)
                flat_steps.extend(lane_steps)

        # Include orphaned steps (not parented to any lane)
        orphans = [
            n for n in unit_ops
            if not n.get("parentId") or n["parentId"] not in swim_lanes
        ]
        if orphans:
            orphan_steps = [_step_dict(n, "Unassigned") for n in orphans]
            roles_with_steps.append({
                "role_name": "Unassigned",
                "steps": orphan_steps,
            })
            flat_steps.extend(orphan_steps)
        return roles_with_steps, flat_steps, True  # is_role_based
    else:
        # No swimlane parenting — group by connected components
        # Include processStart nodes in component discovery
        all_relevant = unit_ops + process_starts
        components = _find_connected_components(all_relevant, edges)

        for comp_nodes in components:
            # Separate processStart from unitOps in this component
            comp_unit_ops = [
                n for n in comp_nodes if n.get("type") == "unitOp"
            ]
            comp_ps = [
                n for n in comp_nodes if n.get("type") == "processStart"
            ]

            # Skip components with no unit ops (orphaned processStart)
            if not comp_unit_ops:
                continue

            process_name = ""
            process_description = ""
            if comp_ps:
                ps_data = comp_ps[0].get("data", {})
                process_name = ps_data.get("label", "")
                process_description = ps_data.get("description", "")

            # In process-based mode, role_name is always empty (no swimlane roles)
            # Process sections use process_name instead for section headers
            comp_steps = [_step_dict(n, "") for n in comp_unit_ops]
            entry = {
                "role_name": "",  # Empty for process-based
                "steps": comp_steps,
            }
            if process_name:
                entry["process_name"] = process_name
                entry["process_description"] = process_description
            roles_with_steps.append(entry)
            flat_steps.extend(comp_steps)
        return roles_with_steps, flat_steps, False  # is_role_based
