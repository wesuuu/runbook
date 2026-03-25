import uuid
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient

from app.models.chat import ChatMessage, ChatMessageRole, ChatSession
from app.models.iam import Organization


# Mock LLM and RAG calls for all tests in this module
@pytest.fixture(autouse=True)
def mock_llm_and_rag():
    with patch(
        "app.services.chat_service._call_llm",
        new_callable=AsyncMock,
        return_value="I'm Trellis AI, happy to help!",
    ), patch(
        "app.services.chat_service.retrieve_relevant_chunks",
        new_callable=AsyncMock,
        return_value=[],
    ), patch(
        "app.services.chat_service._org_has_documents",
        new_callable=AsyncMock,
        return_value=False,
    ):
        yield


async def _create_session(
    client: AsyncClient,
    auth_headers: dict,
    title: str = "Test Chat",
) -> dict:
    resp = await client.post(
        "/chat/sessions",
        json={"title": title},
        headers=auth_headers,
    )
    assert resp.status_code == 201
    return resp.json()


class TestCreateChatSession:
    @pytest.mark.asyncio
    async def test_create_session_returns_201(
        self, client: AsyncClient, auth_headers: dict, test_org: Organization
    ):
        resp = await client.post(
            "/chat/sessions",
            json={"title": "My Research Chat"},
            headers=auth_headers,
        )
        assert resp.status_code == 201
        body = resp.json()
        assert body["title"] == "My Research Chat"
        assert body["status"] == "active"
        assert body["id"] is not None

    @pytest.mark.asyncio
    async def test_create_session_default_title(
        self, client: AsyncClient, auth_headers: dict, test_org: Organization
    ):
        resp = await client.post(
            "/chat/sessions",
            json={},
            headers=auth_headers,
        )
        assert resp.status_code == 201
        assert resp.json()["title"] == "New Chat"

    @pytest.mark.asyncio
    async def test_create_session_with_document_ids(
        self, client: AsyncClient, auth_headers: dict, test_org: Organization
    ):
        doc_id = str(uuid.uuid4())
        resp = await client.post(
            "/chat/sessions",
            json={"context_document_ids": [doc_id]},
            headers=auth_headers,
        )
        assert resp.status_code == 201
        assert resp.json()["context_document_ids"] == [doc_id]

    @pytest.mark.asyncio
    async def test_create_session_requires_auth(self, client: AsyncClient):
        resp = await client.post("/chat/sessions", json={})
        assert resp.status_code == 401


class TestListChatSessions:
    @pytest.mark.asyncio
    async def test_list_sessions_empty(
        self, client: AsyncClient, auth_headers: dict, test_org: Organization
    ):
        resp = await client.get("/chat/sessions", headers=auth_headers)
        assert resp.status_code == 200
        body = resp.json()
        assert body["items"] == []
        assert body["total"] == 0

    @pytest.mark.asyncio
    async def test_list_sessions_returns_created(
        self, client: AsyncClient, auth_headers: dict, test_org: Organization
    ):
        await _create_session(client, auth_headers, "Chat A")
        await _create_session(client, auth_headers, "Chat B")

        resp = await client.get("/chat/sessions", headers=auth_headers)
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] == 2
        assert len(body["items"]) == 2

    @pytest.mark.asyncio
    async def test_list_sessions_respects_pagination(
        self, client: AsyncClient, auth_headers: dict, test_org: Organization
    ):
        for i in range(5):
            await _create_session(client, auth_headers, f"Chat {i}")

        resp = await client.get(
            "/chat/sessions?limit=2&offset=0", headers=auth_headers
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] == 5
        assert len(body["items"]) == 2

    @pytest.mark.asyncio
    async def test_other_user_cannot_see_my_sessions(
        self,
        client: AsyncClient,
        auth_headers: dict,
        second_auth_headers: dict,
        test_org: Organization,
    ):
        await _create_session(client, auth_headers, "Secret Chat")

        resp = await client.get("/chat/sessions", headers=second_auth_headers)
        # second_user may not be in an org, so 403 or 200 with 0
        assert resp.status_code in (200, 403)
        if resp.status_code == 200:
            assert resp.json()["total"] == 0


class TestGetChatSession:
    @pytest.mark.asyncio
    async def test_get_session_by_id(
        self, client: AsyncClient, auth_headers: dict, test_org: Organization
    ):
        created = await _create_session(client, auth_headers)
        session_id = created["id"]

        resp = await client.get(
            f"/chat/sessions/{session_id}", headers=auth_headers
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["id"] == session_id
        assert "messages" in body

    @pytest.mark.asyncio
    async def test_get_nonexistent_session_returns_404(
        self, client: AsyncClient, auth_headers: dict, test_org: Organization
    ):
        fake_id = str(uuid.uuid4())
        resp = await client.get(
            f"/chat/sessions/{fake_id}", headers=auth_headers
        )
        assert resp.status_code == 404


class TestUpdateChatSession:
    @pytest.mark.asyncio
    async def test_rename_session(
        self, client: AsyncClient, auth_headers: dict, test_org: Organization
    ):
        created = await _create_session(client, auth_headers)
        session_id = created["id"]

        resp = await client.patch(
            f"/chat/sessions/{session_id}",
            json={"title": "Renamed Chat"},
            headers=auth_headers,
        )
        assert resp.status_code == 200
        assert resp.json()["title"] == "Renamed Chat"


class TestDeleteChatSession:
    @pytest.mark.asyncio
    async def test_delete_session_returns_204(
        self, client: AsyncClient, auth_headers: dict, test_org: Organization
    ):
        created = await _create_session(client, auth_headers)
        session_id = created["id"]

        resp = await client.delete(
            f"/chat/sessions/{session_id}", headers=auth_headers
        )
        assert resp.status_code == 204

        # Verify it's gone
        resp = await client.get(
            f"/chat/sessions/{session_id}", headers=auth_headers
        )
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_delete_nonexistent_returns_404(
        self, client: AsyncClient, auth_headers: dict, test_org: Organization
    ):
        fake_id = str(uuid.uuid4())
        resp = await client.delete(
            f"/chat/sessions/{fake_id}", headers=auth_headers
        )
        assert resp.status_code == 404


class TestSendChatMessage:
    @pytest.mark.asyncio
    async def test_send_message_returns_both_messages(
        self, client: AsyncClient, auth_headers: dict, test_org: Organization
    ):
        created = await _create_session(client, auth_headers)
        session_id = created["id"]

        resp = await client.post(
            f"/chat/sessions/{session_id}/messages",
            json={"content": "What is cell culture?"},
            headers=auth_headers,
        )
        assert resp.status_code == 201
        body = resp.json()
        assert body["user_message"]["role"] == "user"
        assert body["user_message"]["content"] == "What is cell culture?"
        assert body["assistant_message"]["role"] == "assistant"
        assert len(body["assistant_message"]["content"]) > 0
        assert "sources" in body
        assert body["sources"] == []

    @pytest.mark.asyncio
    async def test_send_message_auto_titles_session(
        self, client: AsyncClient, auth_headers: dict, test_org: Organization
    ):
        # Create with default title
        resp = await client.post(
            "/chat/sessions",
            json={},
            headers=auth_headers,
        )
        session_id = resp.json()["id"]
        assert resp.json()["title"] == "New Chat"

        # Send first message
        await client.post(
            f"/chat/sessions/{session_id}/messages",
            json={"content": "Tell me about CHO cells"},
            headers=auth_headers,
        )

        # Check that title was updated
        resp = await client.get(
            f"/chat/sessions/{session_id}", headers=auth_headers
        )
        assert resp.json()["title"] == "Tell me about CHO cells"

    @pytest.mark.asyncio
    async def test_send_message_to_nonexistent_session(
        self, client: AsyncClient, auth_headers: dict, test_org: Organization
    ):
        fake_id = str(uuid.uuid4())
        resp = await client.post(
            f"/chat/sessions/{fake_id}/messages",
            json={"content": "Hello"},
            headers=auth_headers,
        )
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_send_empty_message_rejected(
        self, client: AsyncClient, auth_headers: dict, test_org: Organization
    ):
        created = await _create_session(client, auth_headers)
        session_id = created["id"]

        resp = await client.post(
            f"/chat/sessions/{session_id}/messages",
            json={"content": ""},
            headers=auth_headers,
        )
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_messages_persist_in_session(
        self, client: AsyncClient, auth_headers: dict, test_org: Organization
    ):
        created = await _create_session(client, auth_headers)
        session_id = created["id"]

        # Send two messages
        await client.post(
            f"/chat/sessions/{session_id}/messages",
            json={"content": "First question"},
            headers=auth_headers,
        )
        await client.post(
            f"/chat/sessions/{session_id}/messages",
            json={"content": "Follow-up question"},
            headers=auth_headers,
        )

        # Get session — should have 4 messages (2 user + 2 assistant)
        resp = await client.get(
            f"/chat/sessions/{session_id}", headers=auth_headers
        )
        assert resp.status_code == 200
        messages = resp.json()["messages"]
        assert len(messages) == 4


class TestSendChatMessageWithRAG:
    """Tests for RAG source retrieval in chat responses."""

    @pytest.fixture(autouse=True)
    def override_mocks(self):
        """Override the module-level mocks with RAG-aware ones."""
        from app.services.chat_service import RetrievedChunk

        fake_sources = [
            RetrievedChunk(
                document_id=uuid.UUID("00000000-0000-0000-0000-000000000001"),
                document_title="Buffer Prep SOP",
                chunk_id=uuid.UUID("00000000-0000-0000-0000-000000000010"),
                chunk_index=3,
                page_number=2,
                content="Mix 50 mM Tris-HCl at pH 7.4 with 150 mM NaCl.",
                score=0.85,
            ),
        ]
        with patch(
            "app.services.chat_service._call_llm",
            new_callable=AsyncMock,
            return_value="Based on the Buffer Prep SOP [1], you should mix Tris-HCl.",
        ), patch(
            "app.services.chat_service.retrieve_relevant_chunks",
            new_callable=AsyncMock,
            return_value=fake_sources,
        ), patch(
            "app.services.chat_service._org_has_documents",
            new_callable=AsyncMock,
            return_value=True,
        ):
            yield

    @pytest.mark.asyncio
    async def test_message_returns_sources(
        self, client: AsyncClient, auth_headers: dict, test_org: Organization
    ):
        created = await _create_session(client, auth_headers)
        session_id = created["id"]

        resp = await client.post(
            f"/chat/sessions/{session_id}/messages",
            json={"content": "How do I prepare buffer?"},
            headers=auth_headers,
        )
        assert resp.status_code == 201
        body = resp.json()
        assert len(body["sources"]) == 1
        source = body["sources"][0]
        assert source["document_title"] == "Buffer Prep SOP"
        assert source["chunk_index"] == 3
        assert source["page_number"] == 2
        assert source["score"] == 0.85
        assert "Tris-HCl" in source["snippet"]

    @pytest.mark.asyncio
    async def test_sources_saved_in_message_metadata(
        self, client: AsyncClient, auth_headers: dict, test_org: Organization
    ):
        created = await _create_session(client, auth_headers)
        session_id = created["id"]

        await client.post(
            f"/chat/sessions/{session_id}/messages",
            json={"content": "Buffer question"},
            headers=auth_headers,
        )

        # Get session and check assistant message metadata
        resp = await client.get(
            f"/chat/sessions/{session_id}", headers=auth_headers
        )
        messages = resp.json()["messages"]
        assistant_msg = [m for m in messages if m["role"] == "assistant"][0]
        assert assistant_msg["metadata_"] is not None
        assert "sources" in assistant_msg["metadata_"]
        assert len(assistant_msg["metadata_"]["sources"]) == 1
