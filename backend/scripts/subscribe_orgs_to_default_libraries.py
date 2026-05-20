"""Backfill: subscribe every existing org to all default libraries.

Use case: a future commit adds a second library with is_default=true.
Run this script once after deploy to enroll existing orgs.
Idempotent: skips orgs that already have the subscription.

Usage (from backend/):
    python scripts/subscribe_orgs_to_default_libraries.py
"""

import asyncio
import logging
import sys
from pathlib import Path

# Make `app` importable when run as a script
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.config import settings

# Import all models to ensure ORM relationships are registered
from app.models import iam, jobs, science  # noqa: F401
from app.models.iam import Organization
from app.services.protocols import library_registry

logging.basicConfig(level=logging.INFO, format="%(message)s")
log = logging.getLogger(__name__)


async def main() -> None:
    library_registry.register_source(
        library_registry.BundledJSONSource(
            Path(__file__).resolve().parents[1] / "app/data/unit_op_libraries"
        )
    )
    await library_registry.reload_libraries()

    defaults = library_registry.default_library_slugs()
    log.info("Default libraries: %s", defaults)

    engine = create_async_engine(settings.database_url, echo=False)
    Session = async_sessionmaker(engine, expire_on_commit=False)

    async with Session() as db:
        org_q = await db.execute(select(Organization))
        orgs = list(org_q.scalars())
        log.info("Backfilling %d organizations...", len(orgs))
        for org in orgs:
            await library_registry.subscribe_default_libraries(db, org.id)
        await db.commit()
        log.info("Done.")

    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
