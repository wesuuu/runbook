"""Service: deterministic mutations on Protocol.graph (DRAFT only).

All functions:
  - load the protocol, check VIEW/EDIT and DRAFT status
  - mutate ``protocol.graph`` (a JSONB dict) in-place
  - flush and return the protocol

Step indices reference unit-op nodes only (Process Start excluded), 0-based.
The single-chain edge invariant is maintained: ps -> step[0] -> step[1] -> ...
Arbitrary DAG topologies are not reshaped.
"""

from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.iam import ObjectType, PermissionLevel
from app.models.science import Protocol
from app.services.core.permissions import check_permission


async def _load_and_guard(
    db: AsyncSession, user_id: UUID, protocol_id: UUID
) -> Protocol:
    proto = (
        await db.execute(select(Protocol).where(Protocol.id == protocol_id))
    ).scalar_one_or_none()
    if proto is None:
        raise ValueError(f"Protocol {protocol_id} not found")
    if proto.project_id is not None:
        allowed = await check_permission(
            db,
            user_id,
            ObjectType.PROJECT,
            proto.project_id,
            PermissionLevel.EDIT,
        )
        if not allowed:
            raise ValueError("You don't have edit permission on this protocol")
    if proto.status != "DRAFT":
        raise ValueError(
            "Protocol is published — create a draft in the protocol editor first."
        )
    return proto


def _split_nodes(graph: dict) -> tuple[list[dict], list[int], list[int]]:
    """Return (nodes, ps_indices, unit_op_indices)."""
    nodes = list(graph.get("nodes", []))
    ps_idx = [i for i, n in enumerate(nodes) if n.get("type") == "processStart"]
    uo_idx = [i for i, n in enumerate(nodes) if n.get("type") == "unitOp"]
    return nodes, ps_idx, uo_idx


def _rebuild_chain_edges(
    existing_edges: list[dict], ps_id: str, ordered_unit_op_ids: list[str]
) -> list[dict]:
    """Replace the linear chain edges with ps -> uo[0] -> uo[1] -> ...

    Non-chain edges (e.g. user-drawn cross-links) are preserved as-is. We
    detect chain edges as: source==ps_id, OR (source in unit_op_ids AND
    target in unit_op_ids AND no parallel structural meaning).
    """
    uo_set = set(ordered_unit_op_ids)
    preserved = [
        e
        for e in existing_edges
        if e.get("source") != ps_id
        and not (e.get("source") in uo_set and e.get("target") in uo_set)
    ]
    chain: list[dict] = []
    prev = ps_id
    for nid in ordered_unit_op_ids:
        chain.append({"id": f"edge-{uuid4()}", "source": prev, "target": nid})
        prev = nid
    return preserved + chain


async def add_step(
    db: AsyncSession,
    *,
    user_id: UUID,
    protocol_id: UUID,
    name: str,
    unit_op_name: str,
    duration_min: int = 30,
    description: str = "",
    category: str = "General",
    params: dict[str, Any] | None = None,
    after_step_index: int | None = None,
    role_id: UUID | None = None,
) -> Protocol:
    """Insert a new unit-op node into the graph.

    ``after_step_index=None`` appends after the last unit op. Otherwise
    inserts immediately after that 0-based unit-op step index.
    """
    proto = await _load_and_guard(db, user_id, protocol_id)
    graph = dict(proto.graph or {})
    nodes, ps_idx, uo_idx = _split_nodes(graph)
    if not ps_idx:
        raise ValueError("Protocol graph has no Process Start node")
    ps_id = nodes[ps_idx[0]]["id"]

    if after_step_index is not None:
        if after_step_index < 0 or after_step_index >= len(uo_idx):
            raise ValueError(
                f"after_step_index {after_step_index} out of range "
                f"(protocol has {len(uo_idx)} unit op steps)"
            )
        insert_pos = uo_idx[after_step_index] + 1
    else:
        insert_pos = (uo_idx[-1] + 1) if uo_idx else (ps_idx[0] + 1)

    new_node: dict[str, Any] = {
        "id": f"node-{uuid4()}",
        "type": "unitOp",
        "position": {"x": 100, "y": 200},
        "data": {
            "label": name,
            "unitOpId": None,
            "category": category,
            "description": description,
            "duration_min": duration_min,
            "params": params or {},
            "paramSchema": {},
        },
    }
    if role_id is not None:
        new_node["parentId"] = f"lane-{role_id}"
    nodes.insert(insert_pos, new_node)

    new_uo_ids = [n["id"] for n in nodes if n.get("type") == "unitOp"]
    edges = _rebuild_chain_edges(graph.get("edges", []), ps_id, new_uo_ids)

    graph["nodes"] = nodes
    graph["edges"] = edges
    proto.graph = graph
    await db.flush()
    return proto
