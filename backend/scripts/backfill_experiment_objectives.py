"""F-0093 §2.2 — CLI for the objective backfill.

Run once after the migration deploys; safe to re-run (the work is idempotent
and restartable — see `app.services.experiments.backfill`).

Usage (from backend/, venv active):  python scripts/backfill_experiment_objectives.py
"""

import asyncio
import logging

from app.db.session import AsyncSessionLocal
from app.services.experiments.backfill import backfill_objectives

logger = logging.getLogger("backfill_experiment_objectives")


async def _main() -> None:
    logging.basicConfig(level=logging.INFO)
    async with AsyncSessionLocal() as db:
        stats = await backfill_objectives(db)
    skipped = stats["skipped_over_cap"] + stats["skipped_unparseable"]
    line = (
        "backfill_experiment_objectives complete: "
        f"total={stats['total']} already_set={stats['already_set']} "
        f"backfilled={stats['backfilled']} "
        f"skipped_over_cap={stats['skipped_over_cap']} "
        f"skipped_unparseable={stats['skipped_unparseable']}"
    )
    if skipped:
        logger.warning(line)
    else:
        logger.info(line)


if __name__ == "__main__":
    asyncio.run(_main())
