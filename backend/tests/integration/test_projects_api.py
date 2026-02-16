import pytest
from httpx import AsyncClient
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from uuid import UUID

from app.models.science import Project
from app.models.execution import AuditLog

@pytest.mark.asyncio
async def test_create_project(client: AsyncClient, db_session: AsyncSession):
    # Setup: Create Organization and User (for actor_id FK)
    from app.models.iam import Organization, User
    from uuid import UUID
    
    org = Organization(name="Test Org")
    db_session.add(org)
    
    user = User(
        id=UUID("00000000-0000-0000-0000-000000000000"),
        email="test@example.com",
        full_name="Test User",
        hashed_password="hashed_secret"
    )
    db_session.add(user)
    
    await db_session.commit()
    await db_session.refresh(org)

    # Act
    response = await client.post("/projects/", json={
        "name": "Integration Test Project",
        "description": "Created via verified integration test",
        "organization_id": str(org.id)
    })
    
    # Assert HTTP Response
    assert response.status_code == 200
    data = response.json()
    assert data["name"] == "Integration Test Project"
    project_id = data["id"]
    
    # Assert database state (Project created)
    result = await db_session.execute(select(Project).where(Project.id == project_id))
    project = result.scalar_one_or_none()
    assert project is not None
    
    # Assert Audit Log created
    audit_res = await db_session.execute(
        select(AuditLog).where(
            AuditLog.entity_id == project_id,
            AuditLog.action == "CREATE"
        )
    )
    log_entry = audit_res.scalar_one_or_none()
    assert log_entry is not None
    assert log_entry.changes["name"] == "Integration Test Project"
