"""Repair: re-create swimLane nodes for ProtocolRoles missing them.

Older role-creation paths only inserted the ProtocolRole row without
appending a swimLane node to protocol.graph. This leaves any nested
unit-op nodes (parentId="lane-<role_id>") orphaned in the editor.

Run once after deploying the role-mutation graph-sync fix. Idempotent:
protocols whose lanes already exist are skipped.

Usage: python scripts/backfill_protocol_role_lanes.py [--dry-run]
"""

import argparse
import asyncio
import sys

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.config import settings
from app.models.protocols import Protocol, ProtocolRole
from app.services.protocols.roles import _build_lane_node, _graph_layout, _lane_id


async def repair(dry_run: bool) -> int:
    engine = create_async_engine(settings.database_url, echo=False)
    sessionmaker = async_sessionmaker(engine, expire_on_commit=False)
    fixed = 0
    async with sessionmaker() as session:
        protocols = (await session.execute(select(Protocol))).scalars().all()
        for proto in protocols:
            roles = (
                (
                    await session.execute(
                        select(ProtocolRole)
                        .where(ProtocolRole.protocol_id == proto.id)
                        .order_by(ProtocolRole.sort_order)
                    )
                )
                .scalars()
                .all()
            )
            if not roles:
                continue
            graph = dict(proto.graph or {})
            nodes = list(graph.get("nodes", []))
            existing_lane_ids = {
                n.get("id") for n in nodes if n.get("type") == "swimLane"
            }
            layout = _graph_layout(graph)
            existing_lane_count = len(existing_lane_ids)
            missing = [r for r in roles if _lane_id(r.id) not in existing_lane_ids]
            if not missing:
                continue
            for offset, role in enumerate(missing):
                nodes.append(
                    _build_lane_node(role, layout, existing_lane_count + offset)
                )
            graph["nodes"] = nodes
            print(
                f"protocol {proto.id} ({proto.name}): adding {len(missing)} lane(s) "
                f"for {[r.name for r in missing]}"
            )
            if not dry_run:
                proto.graph = graph
            fixed += 1
        if not dry_run:
            await session.commit()
    await engine.dispose()
    return fixed


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--dry-run", action="store_true", help="report what would change"
    )
    args = parser.parse_args()
    fixed = asyncio.run(repair(args.dry_run))
    verb = "would fix" if args.dry_run else "fixed"
    print(f"\n{verb} {fixed} protocol(s)")


if __name__ == "__main__":
    sys.exit(main())
