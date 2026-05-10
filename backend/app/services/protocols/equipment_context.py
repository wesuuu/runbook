"""Flatten assigned equipment in a protocol graph into a template-context dict.

Returns a flat ``{f"{local_id}_name": eq.name, f"{local_id}_description":
eq.description}`` mapping that callers merge into the per-step params namespace
before invoking the template renderer. Walks every unit op node (including
swimlane children) and fetches the referenced Equipment rows in a single
org-scoped query.
"""

import logging
import uuid
from collections import defaultdict
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.science import Equipment

logger = logging.getLogger(__name__)


async def build_equipment_context(
    db: AsyncSession,
    org_id: uuid.UUID | None,
    graph: dict[str, Any] | None,
) -> tuple[dict[str, str], list[str]]:
    """Walk the protocol graph, build the flat template-context dict.

    Args:
        db: async session.
        org_id: scope Equipment lookup to this org. When ``None`` (e.g. the
            caller has no selected org) the function short-circuits and returns
            an empty context — Equipment is org-scoped, so nothing resolves.
        graph: protocol graph JSONB (``{"nodes": [...], "edges": [...]}``).

    Returns:
        ``(context, warnings)`` where ``context`` maps
        ``"<local_id>_name"`` / ``"<local_id>_description"`` to the resolved
        equipment field, and ``warnings`` is a list of human-readable strings
        for duplicate local_ids and missing Equipment rows.
    """
    if not graph or org_id is None:
        return {}, []

    nodes = graph.get("nodes") or []
    assignments: list[tuple[str, str, str]] = []
    for node in nodes:
        if node.get("type") != "unitOp":
            continue
        for eq in (node.get("data") or {}).get("equipment") or []:
            local_id = eq.get("local_id")
            equipment_id = eq.get("equipment_id")
            if not local_id or not equipment_id:
                continue
            assignments.append((node.get("id", ""), local_id, equipment_id))

    if not assignments:
        return {}, []

    by_local: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for node_id, local_id, equipment_id in assignments:
        by_local[local_id].append((node_id, equipment_id))

    warnings: list[str] = []
    for local_id, hits in by_local.items():
        if len(hits) > 1:
            node_ids = ", ".join(h[0] for h in hits)
            warnings.append(
                f"Duplicate equipment local_id '{local_id}' on nodes: "
                f"{node_ids} - first wins"
            )

    eq_uuids: set[uuid.UUID] = set()
    for hits in by_local.values():
        try:
            eq_uuids.add(uuid.UUID(hits[0][1]))
        except (ValueError, TypeError):
            continue

    eq_by_uuid: dict[str, Equipment] = {}
    if eq_uuids:
        result = await db.execute(
            select(Equipment).where(
                Equipment.id.in_(eq_uuids),
                Equipment.organization_id == org_id,
            )
        )
        for row in result.scalars().all():
            eq_by_uuid[str(row.id)] = row

    context: dict[str, str] = {}
    for local_id, hits in by_local.items():
        equipment_id = hits[0][1]
        eq = eq_by_uuid.get(equipment_id)
        if not eq:
            warnings.append(
                f"Equipment for local_id '{local_id}' "
                f"(equipment_id={equipment_id}) not found in organization"
            )
            continue
        context[f"{local_id}_name"] = eq.name or ""
        context[f"{local_id}_description"] = eq.description or ""

    if warnings:
        logger.warning("Equipment context warnings: %s", "; ".join(warnings))

    return context, warnings
