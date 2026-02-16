from uuid import UUID
from typing import Any, Dict
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.execution import AuditLog

async def log_audit(
    db: AsyncSession,
    actor_id: UUID,  # User ID performing the action
    action: str,     # CREATE, UPDATE, DELETE, ARCHIVE
    entity_type: str,
    entity_id: UUID,
    changes: Dict[str, Any] = {}
):
    """
    Logs an audit event to the database.
    """
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
