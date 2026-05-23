import logging

from sqlalchemy import event as _sa_event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import Session as SyncSession

from app.core.config import settings

logger = logging.getLogger("db.session")

engine = create_async_engine(
    settings.database_url,
    echo=settings.debug,
    # Detect connections killed while idle (e.g. by pgbouncer / postgres
    # idle_in_transaction_session_timeout) before SQLAlchemy hands them out.
    pool_pre_ping=True,
    # Force-recycle conns older than 30 min so we never reuse one that
    # outlived a server-side idle timeout we don't control.
    pool_recycle=1800,
)

AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
)


def _drain_pending_default_channels(session) -> None:
    """TD-0091c: drain queued provisioning IDs and schedule background work.

    Called on after_commit so we never provision for a user whose insert
    was rolled back. Wrapped in try/except so a failure here can never
    break request teardown.
    """
    pending = list(session.info.get("pending_default_channels", []) or [])
    session.info["pending_default_channels"] = []
    if not pending:
        return
    try:
        from app.services.core.notifications.provisioning import (
            provision_default_channel_for_user,
        )
        from app.services.core.task_runner import get_task_runner

        runner = get_task_runner()
        for uid in pending:
            runner.submit(provision_default_channel_for_user(uid))
    except Exception:
        logger.exception(
            "default-channel drain failed; pending=%s", pending
        )


@_sa_event.listens_for(SyncSession, "after_commit")
def _after_commit_drain(session):
    _drain_pending_default_channels(session)


@_sa_event.listens_for(SyncSession, "after_soft_rollback")
def _after_rollback_clear(session, previous_transaction):
    # Discard pending IDs on rollback so we don't provision for a user
    # whose row was rolled back.
    session.info["pending_default_channels"] = []


async def get_db():
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()
