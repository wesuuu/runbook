"""Integration tests for POST /chat/sessions/{id}/generate-protocol."""

import uuid
from unittest.mock import AsyncMock, patch, MagicMock

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.chat import ChatMessage, ChatMessageRole, ChatSession
from app.models.execution import AuditLog
from app.models.iam import Organization
from app.models.science import Project, Protocol
from app.services.protocol_generator import GeneratedProtocol, GeneratedStep


def _fake_generated_protocol():
    return GeneratedProtocol(
        name="CHO Cell Culture",
        description="Standard CHO cell expansion protocol",
        steps=[
            GeneratedStep(
                name="Media Prep",
                unit_op_name="Media Prep",
                category="Media Prep",
                duration_min=30,
                params={"volume_ml": 500},
            ),
            GeneratedStep(
                name="Seeding",
                unit_op_name="Seeding",
                category="Cell Culture",
                duration_min=45,
                params={"density": 0.5e6},
            ),
        ],
    )


async def _create_session_with_messages(
    client: AsyncClient,
    auth_headers: dict,
) -> str:
    """Create a chat session and send a message to populate it."""
    # Create session
    resp = await client.post(
        "/chat/sessions",
        json={"title": "Protocol Discussion"},
        headers=auth_headers,
    )
    assert resp.status_code == 201
    session_id = resp.json()["id"]

    # Send a message (mocked LLM)
    with patch(
        "app.services.chat_service._call_llm",
        new_callable=AsyncMock,
        return_value="Sure, let's discuss the protocol.",
    ), patch(
        "app.services.chat_service.retrieve_relevant_chunks",
        new_callable=AsyncMock,
        return_value=[],
    ), patch(
        "app.services.chat_service._org_has_documents",
        new_callable=AsyncMock,
        return_value=False,
    ):
        resp = await client.post(
            f"/chat/sessions/{session_id}/messages",
            json={"content": "I want to create a CHO cell culture protocol"},
            headers=auth_headers,
        )
        assert resp.status_code == 201

    return session_id


class TestGenerateProtocolEndpoint:
    @pytest.mark.asyncio
    async def test_generates_draft_protocol(
        self,
        client: AsyncClient,
        auth_headers: dict,
        test_org: Organization,
        test_project: Project,
    ):
        session_id = await _create_session_with_messages(client, auth_headers)

        with patch(
            "app.services.protocol_generator.generate_protocol_from_chat",
        ) as mock_gen:
            # Make the mock create a real Protocol in DB
            async def fake_generate(db, session, project_id, user_id, protocol_name=None):
                protocol = Protocol(
                    name=protocol_name or "CHO Cell Culture",
                    description="Generated protocol",
                    project_id=project_id,
                    status="DRAFT",
                    graph={
                        "nodes": [],
                        "edges": [],
                        "_metadata": {
                            "source": "ai_generated",
                            "chat_session_id": str(session.id),
                        },
                    },
                )
                db.add(protocol)
                await db.flush()
                return protocol

            mock_gen.side_effect = fake_generate

            resp = await client.post(
                f"/chat/sessions/{session_id}/generate-protocol",
                json={"project_id": str(test_project.id)},
                headers=auth_headers,
            )

        assert resp.status_code == 201
        body = resp.json()
        assert body["protocol_name"] == "CHO Cell Culture"
        assert body["project_id"] == str(test_project.id)
        assert "protocol_id" in body

    @pytest.mark.asyncio
    async def test_requires_session_ownership(
        self,
        client: AsyncClient,
        auth_headers: dict,
        second_auth_headers: dict,
        test_org: Organization,
        test_project: Project,
        second_user,
    ):
        session_id = await _create_session_with_messages(client, auth_headers)

        resp = await client.post(
            f"/chat/sessions/{session_id}/generate-protocol",
            json={"project_id": str(test_project.id)},
            headers=second_auth_headers,
        )
        assert resp.status_code == 403

    @pytest.mark.asyncio
    async def test_nonexistent_project_returns_404(
        self,
        client: AsyncClient,
        auth_headers: dict,
        test_org: Organization,
    ):
        session_id = await _create_session_with_messages(client, auth_headers)
        fake_project_id = str(uuid.uuid4())

        resp = await client.post(
            f"/chat/sessions/{session_id}/generate-protocol",
            json={"project_id": fake_project_id},
            headers=auth_headers,
        )
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_nonexistent_session_returns_404(
        self,
        client: AsyncClient,
        auth_headers: dict,
        test_org: Organization,
        test_project: Project,
    ):
        fake_session_id = str(uuid.uuid4())

        resp = await client.post(
            f"/chat/sessions/{fake_session_id}/generate-protocol",
            json={"project_id": str(test_project.id)},
            headers=auth_headers,
        )
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_audit_log_created(
        self,
        client: AsyncClient,
        auth_headers: dict,
        test_org: Organization,
        test_project: Project,
        db_session: AsyncSession,
    ):
        session_id = await _create_session_with_messages(client, auth_headers)

        with patch(
            "app.services.protocol_generator.generate_protocol_from_chat",
        ) as mock_gen:
            async def fake_generate(db, session, project_id, user_id, protocol_name=None):
                protocol = Protocol(
                    name="Test Protocol",
                    description="Generated",
                    project_id=project_id,
                    status="DRAFT",
                    graph={
                        "nodes": [],
                        "edges": [],
                        "_metadata": {
                            "source": "ai_generated",
                            "chat_session_id": str(session.id),
                        },
                    },
                )
                db.add(protocol)
                await db.flush()
                return protocol

            mock_gen.side_effect = fake_generate

            resp = await client.post(
                f"/chat/sessions/{session_id}/generate-protocol",
                json={"project_id": str(test_project.id)},
                headers=auth_headers,
            )

        assert resp.status_code == 201
        protocol_id = resp.json()["protocol_id"]

        # Check audit log
        result = await db_session.execute(
            select(AuditLog).where(
                AuditLog.entity_id == uuid.UUID(protocol_id),
                AuditLog.action == "CREATE",
            )
        )
        audit = result.scalar_one_or_none()
        assert audit is not None
        assert audit.entity_type == "Protocol"
        assert audit.changes["source"] == "ai_generated"
        assert "chat_session_id" in audit.changes

    @pytest.mark.asyncio
    async def test_with_custom_protocol_name(
        self,
        client: AsyncClient,
        auth_headers: dict,
        test_org: Organization,
        test_project: Project,
    ):
        session_id = await _create_session_with_messages(client, auth_headers)

        with patch(
            "app.services.protocol_generator.generate_protocol_from_chat",
        ) as mock_gen:
            async def fake_generate(db, session, project_id, user_id, protocol_name=None):
                protocol = Protocol(
                    name=protocol_name or "Default Name",
                    description="Generated",
                    project_id=project_id,
                    status="DRAFT",
                    graph={"nodes": [], "edges": [], "_metadata": {}},
                )
                db.add(protocol)
                await db.flush()
                return protocol

            mock_gen.side_effect = fake_generate

            resp = await client.post(
                f"/chat/sessions/{session_id}/generate-protocol",
                json={
                    "project_id": str(test_project.id),
                    "protocol_name": "My Custom Protocol",
                },
                headers=auth_headers,
            )

        assert resp.status_code == 201
        assert resp.json()["protocol_name"] == "My Custom Protocol"
