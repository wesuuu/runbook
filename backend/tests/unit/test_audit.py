import uuid
import pytest
from unittest.mock import AsyncMock, MagicMock
from sqlalchemy.ext.asyncio import AsyncSession
from app.services.audit import log_audit
from app.models.execution import AuditLog

@pytest.mark.asyncio
async def test_log_audit_creates_entry():
    # Arrange
    mock_db = AsyncMock(spec=AsyncSession)
    actor_id = uuid.uuid4()
    entity_id = uuid.uuid4()
    changes = {"field": "value"}
    
    # Act
    await log_audit(
        db=mock_db,
        actor_id=actor_id,
        action="TEST_ACTION",
        entity_type="TestEntity",
        entity_id=entity_id,
        changes=changes
    )
    
    # Assert
    # Check that db.add was called with an AuditLog instance
    assert mock_db.add.called
    args = mock_db.add.call_args[0]
    audit_entry = args[0]
    
    assert isinstance(audit_entry, AuditLog)
    assert audit_entry.actor_id == actor_id
    assert audit_entry.action == "TEST_ACTION"
    assert audit_entry.entity_id == entity_id
    assert audit_entry.changes == changes
