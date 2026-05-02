"""Validate a Protocol graph against structural and quality rules.

Pure function — no DB, no LLM. Callers fetch the graph + unit-op catalog
and pass them in. Used by the chat agent's `validate_protocol` tool to
self-check work after `create_protocol`, and reusable from any future
REST endpoint or background job.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from pydantic import BaseModel

from app.models.science import ProtocolRole, UnitOpDefinition

Severity = str  # "error" | "warning"


class ValidationIssue(BaseModel):
    severity: Severity
    code: str
    message: str
    node_id: str | None = None


class ValidationResult(BaseModel):
    ok: bool
    issues: list[ValidationIssue]


_PLACEHOLDER_DESCRIPTIONS = {"", "todo", "tbd", "n/a", "placeholder"}


def validate_protocol_graph(
    graph: dict[str, Any],
    unit_ops: list[UnitOpDefinition],
    roles: list[ProtocolRole] | None = None,
) -> ValidationResult:
    """Check a graph for structural and quality problems.

    Args:
        graph: The Protocol.graph JSONB.
        unit_ops: Org-visible UnitOpDefinitions for resolving `unitOpId`.
        roles: ProtocolRole rows for cross-checking that swimLane nodes
            and unit-op `parentId`s line up. When omitted, role/lane
            consistency checks are skipped.

    Returns:
        ValidationResult — `ok=False` if any issue has severity="error".
    """
    issues: list[ValidationIssue] = []
    nodes: list[dict[str, Any]] = list(graph.get("nodes", []))
    edges: list[dict[str, Any]] = list(graph.get("edges", []))

    process_starts = [n for n in nodes if n.get("type") == "processStart"]
    unit_op_nodes = [n for n in nodes if n.get("type") == "unitOp"]

    if not process_starts:
        issues.append(
            ValidationIssue(
                severity="error",
                code="missing_process_start",
                message=(
                    "Protocol has no Process Start node. Every protocol must "
                    "begin with one."
                ),
            )
        )

    component_starts = _process_starts_per_component(nodes, edges, process_starts)
    for component_idx, count in enumerate(component_starts):
        if count > 1:
            issues.append(
                ValidationIssue(
                    severity="error",
                    code="multiple_process_starts",
                    message=(
                        f"Connected component {component_idx} has {count} "
                        "Process Start nodes; expected exactly 1."
                    ),
                )
            )

    unit_op_ids = {str(op.id) for op in unit_ops}
    incoming_targets = {e.get("target") for e in edges}

    for n in unit_op_nodes:
        node_id = n.get("id") or "<unknown>"
        data = n.get("data") or {}
        label = data.get("label") or "<unnamed>"

        unit_op_id = data.get("unitOpId")
        if unit_op_id and str(unit_op_id) not in unit_op_ids:
            issues.append(
                ValidationIssue(
                    severity="error",
                    code="unknown_unit_op_id",
                    message=(
                        f"Step '{label}' references unitOpId={unit_op_id} which "
                        "does not exist in the unit-op catalog."
                    ),
                    node_id=node_id,
                )
            )

        param_schema = data.get("paramSchema") or {}
        if not param_schema.get("properties"):
            issues.append(
                ValidationIssue(
                    severity="warning",
                    code="empty_param_schema",
                    message=(
                        f"Step '{label}' has no parameter schema. Scientists "
                        "won't be able to set per-run values."
                    ),
                    node_id=node_id,
                )
            )

        description = (data.get("description") or "").strip().lower()
        if description in _PLACEHOLDER_DESCRIPTIONS:
            issues.append(
                ValidationIssue(
                    severity="warning",
                    code="missing_description",
                    message=(
                        f"Step '{label}' has no description. Add instructions "
                        "the technician should follow."
                    ),
                    node_id=node_id,
                )
            )

        if not unit_op_id and (data.get("category") or "").lower() in {"", "general"}:
            issues.append(
                ValidationIssue(
                    severity="warning",
                    code="placeholder_category",
                    message=(
                        f"Step '{label}' has no unitOpId and category "
                        f"'{data.get('category', '')}'. Either match an existing "
                        "unit op or set a specific category (e.g. 'Media Prep')."
                    ),
                    node_id=node_id,
                )
            )

        parent_id = n.get("parentId")
        if parent_id and isinstance(parent_id, str) and parent_id.startswith("lane-"):
            lane_node_ids = {
                ln.get("id") for ln in nodes if ln.get("type") == "swimLane"
            }
            if parent_id not in lane_node_ids:
                issues.append(
                    ValidationIssue(
                        severity="warning",
                        code="orphaned_parent_id",
                        message=(
                            f"Step '{label}' has parentId={parent_id} but no "
                            "matching swimLane node exists. The step will not "
                            "render inside any role lane."
                        ),
                        node_id=node_id,
                    )
                )

        if node_id not in incoming_targets:
            issues.append(
                ValidationIssue(
                    severity="warning",
                    code="disconnected_step",
                    message=(
                        f"Step '{label}' has no incoming edge. It is not "
                        "reachable from any Process Start."
                    ),
                    node_id=node_id,
                )
            )

    if roles is not None:
        lane_nodes = [n for n in nodes if n.get("type") == "swimLane"]
        lane_ids_by_role = {f"lane-{r.id}": r for r in roles}
        present_lane_ids = {ln.get("id") for ln in lane_nodes}
        for lane_id, role in lane_ids_by_role.items():
            if lane_id not in present_lane_ids:
                issues.append(
                    ValidationIssue(
                        severity="warning",
                        code="missing_lane_node",
                        message=(
                            f"Role '{role.name}' has no swimLane node in the "
                            "graph. Steps assigned to this role will not appear "
                            "inside its lane."
                        ),
                    )
                )
        for ln in lane_nodes:
            ln_id = ln.get("id")
            if ln_id and ln_id not in lane_ids_by_role:
                issues.append(
                    ValidationIssue(
                        severity="warning",
                        code="orphaned_lane_node",
                        message=(
                            f"SwimLane node {ln_id} does not match any "
                            "ProtocolRole. Either remove the lane or recreate "
                            "the role."
                        ),
                        node_id=ln_id,
                    )
                )

    ok = not any(i.severity == "error" for i in issues)
    return ValidationResult(ok=ok, issues=issues)


def _process_starts_per_component(
    nodes: list[dict[str, Any]],
    edges: list[dict[str, Any]],
    process_starts: list[dict[str, Any]],
) -> list[int]:
    """Count Process Start nodes within each connected component.

    Returns a list of counts (one per component). Components with zero
    Process Starts are excluded — that case is handled by the
    'missing_process_start' rule when the count is zero overall.
    """
    if not nodes:
        return []
    adjacency: dict[str, set[str]] = {n["id"]: set() for n in nodes if "id" in n}
    for e in edges:
        s, t = e.get("source"), e.get("target")
        if s in adjacency and t in adjacency:
            adjacency[s].add(t)
            adjacency[t].add(s)

    process_start_ids = {ps["id"] for ps in process_starts if "id" in ps}
    visited: set[str] = set()
    counts: list[int] = []
    for node_id in adjacency:
        if node_id in visited:
            continue
        stack = [node_id]
        component: set[str] = set()
        while stack:
            cur = stack.pop()
            if cur in component:
                continue
            component.add(cur)
            stack.extend(adjacency[cur])
        visited |= component
        ps_in_component = len(component & process_start_ids)
        if ps_in_component:
            counts.append(ps_in_component)
    return counts


__all__ = [
    "ValidationIssue",
    "ValidationResult",
    "validate_protocol_graph",
]
