from typing import Any, Dict
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.execution import AuditLog

# Well-known user referenced by audit entries created by system processes
# (webhooks, scheduled jobs) that have no authenticated user. The row is
# seeded at DB init; see backend/app/db/seed.py and the corresponding
# Alembic migration.
SYSTEM_ACTOR_ID: UUID = UUID("00000000-0000-0000-0000-000000000000")


async def log_audit(
    db: AsyncSession,
    actor_id: UUID,  # User ID performing the action
    action: str,     # CREATE, UPDATE, DELETE, ARCHIVE
    entity_type: str,
    entity_id: UUID,
    changes: Dict[str, Any] | None = None
):
    """
    Logs an audit event to the database.
    """
    changes = changes or {}

    # Ensure dictionary values are JSON serializable (e.g. UUIDs to str)
    def json_serializable(v):
        if isinstance(v, UUID):
            return str(v)
        return v

    serialized_changes = {k: json_serializable(v) for k, v in changes.items()}

    audit_entry = AuditLog(
        entity_type=entity_type,
        entity_id=entity_id,
        actor_id=actor_id,
        action=action,
        changes=serialized_changes
    )
    db.add(audit_entry)
    # Note: We do not commit here, letting the caller handle the transaction scope.
