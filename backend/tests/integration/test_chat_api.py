import json
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import AsyncClient

from app.models.chat import ChatMessage, ChatMessageRole, ChatSession
from app.models.iam import Organization
from app.services.ai.deps import RetrievedChunk

# ── SSE helpers ─────────────────────────────────────────────────────────────


def _drain_sse(body: str) -> list[dict]:
    """Parse SSE 'data: {json}\\n\\n' frames into a list of dicts."""
    out = []
    for line in body.splitlines():
        line = line.strip()
        if line.startswith("data:"):
            out.append(json.loads(line[len("data:") :].strip()))
    return out


def _done(events: list[dict]) -> dict:
    """Return the first event with type=='done'."""
    return next(e for e in events if e["type"] == "done")


async def _stream_message(
    client: AsyncClient,
    session_id: str,
    content: str,
    auth_headers: dict,
) -> tuple[int, list[dict]]:
    """POST to the SSE stream endpoint and collect all events.

    Returns (status_code, events).  For non-200 responses the events list
    will be empty (the error comes back as JSON, not SSE).
    """
    async with client.stream(
        "POST",
        f"/chat/sessions/{session_id}/messages/stream",
        json={"content": content},
        headers=auth_headers,
    ) as resp:
        body = ""
        async for chunk in resp.aiter_text():
            body += chunk
    events = _drain_sse(body) if resp.status_code == 200 else []
    return resp.status_code, events


# ── Mock factory ─────────────────────────────────────────────────────────────


def _make_streaming_mock(content: str, sources: list):
    """Return an async generator mock for send_message_streaming.

    Persists real DB rows (user + assistant messages) so session GET tests
    that count messages still work.  Yields a single 'done' SSE event
    carrying the persisted message data.
    """

    async def _fake_streaming(
        db, session, user_content, *, user_id, is_org_admin, skill_id=None
    ):
        from app.models.chat import ChatMessage, ChatMessageRole
        from app.schemas.chat import ChatMessageResponse, ChatSourceReference

        user_msg = ChatMessage(
            session_id=session.id,
            role=ChatMessageRole.USER,
            content=user_content,
        )
        db.add(user_msg)

        # Mirror real send_message_streaming auto-title behaviour
        if session.title == "New Chat":
            session.title = user_content[:100].strip()

        assistant_msg = ChatMessage(
            session_id=session.id,
            role=ChatMessageRole.ASSISTANT,
            content=content,
            metadata_=(
                {
                    "sources": [
                        {
                            "document_id": str(s.document_id),
                            "document_title": s.document_title,
                            "chunk_id": str(s.chunk_id),
                            "chunk_index": s.chunk_index,
                            "page_number": s.page_number,
                            "score": s.score,
                            "snippet": s.content[:200],
                        }
                        for s in sources
                    ]
                }
                if sources
                else None
            ),
        )
        db.add(assistant_msg)
        await db.flush()

        source_dicts = [
            {
                "document_id": str(s.document_id),
                "document_title": s.document_title,
                "chunk_id": str(s.chunk_id),
                "chunk_index": s.chunk_index,
                "page_number": s.page_number,
                "score": s.score,
                "snippet": s.content[:200],
            }
            for s in sources
        ]

        yield {
            "type": "done",
            "user_message": {
                "id": str(user_msg.id) if user_msg.id else "u-test",
                "role": "user",
                "content": user_content,
                "session_id": str(session.id),
                "metadata_": None,
                "created_at": None,
            },
            "assistant_message": {
                "id": str(assistant_msg.id) if assistant_msg.id else "a-test",
                "role": "assistant",
                "content": content,
                "session_id": str(session.id),
                "metadata_": assistant_msg.metadata_,
                "created_at": None,
            },
            "sources": source_dicts,
        }

    return _fake_streaming


# Mock send_message_streaming for all tests in this module
@pytest.fixture(autouse=True)
def mock_llm_and_rag():
    with patch(
        "app.api.endpoints.chat.send_message_streaming",
        new=_make_streaming_mock("I'm Batchrite AI, happy to help!", []),
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

        resp = await client.get("/chat/sessions?limit=2&offset=0", headers=auth_headers)
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

        resp = await client.get(f"/chat/sessions/{session_id}", headers=auth_headers)
        assert resp.status_code == 200
        body = resp.json()
        assert body["id"] == session_id
        assert "messages" in body

    @pytest.mark.asyncio
    async def test_get_nonexistent_session_returns_404(
        self, client: AsyncClient, auth_headers: dict, test_org: Organization
    ):
        fake_id = str(uuid.uuid4())
        resp = await client.get(f"/chat/sessions/{fake_id}", headers=auth_headers)
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

        resp = await client.delete(f"/chat/sessions/{session_id}", headers=auth_headers)
        assert resp.status_code == 204

        # Verify it's gone
        resp = await client.get(f"/chat/sessions/{session_id}", headers=auth_headers)
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_delete_nonexistent_returns_404(
        self, client: AsyncClient, auth_headers: dict, test_org: Organization
    ):
        fake_id = str(uuid.uuid4())
        resp = await client.delete(f"/chat/sessions/{fake_id}", headers=auth_headers)
        assert resp.status_code == 404


class TestSendChatMessage:
    @pytest.mark.asyncio
    async def test_send_message_returns_both_messages(
        self, client: AsyncClient, auth_headers: dict, test_org: Organization
    ):
        created = await _create_session(client, auth_headers)
        session_id = created["id"]

        status_code, events = await _stream_message(
            client, session_id, "What is cell culture?", auth_headers
        )
        assert status_code == 200
        done = _done(events)
        assert done["user_message"]["role"] == "user"
        assert done["user_message"]["content"] == "What is cell culture?"
        assert done["assistant_message"]["role"] == "assistant"
        assert len(done["assistant_message"]["content"]) > 0
        assert "sources" in done
        assert done["sources"] == []

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

        # Send first message via stream
        await _stream_message(
            client, session_id, "Tell me about CHO cells", auth_headers
        )

        # Check that title was updated
        resp = await client.get(f"/chat/sessions/{session_id}", headers=auth_headers)
        assert resp.json()["title"] == "Tell me about CHO cells"

    @pytest.mark.asyncio
    async def test_send_message_to_nonexistent_session(
        self, client: AsyncClient, auth_headers: dict, test_org: Organization
    ):
        fake_id = str(uuid.uuid4())
        async with client.stream(
            "POST",
            f"/chat/sessions/{fake_id}/messages/stream",
            json={"content": "Hello"},
            headers=auth_headers,
        ) as resp:
            await resp.aread()
            assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_send_empty_message_rejected(
        self, client: AsyncClient, auth_headers: dict, test_org: Organization
    ):
        created = await _create_session(client, auth_headers)
        session_id = created["id"]

        async with client.stream(
            "POST",
            f"/chat/sessions/{session_id}/messages/stream",
            json={"content": ""},
            headers=auth_headers,
        ) as resp:
            await resp.aread()
            assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_messages_persist_in_session(
        self, client: AsyncClient, auth_headers: dict, test_org: Organization
    ):
        created = await _create_session(client, auth_headers)
        session_id = created["id"]

        # Send two messages
        await _stream_message(client, session_id, "First question", auth_headers)
        await _stream_message(client, session_id, "Follow-up question", auth_headers)

        # Get session — should have 4 messages (2 user + 2 assistant)
        resp = await client.get(f"/chat/sessions/{session_id}", headers=auth_headers)
        assert resp.status_code == 200
        messages = resp.json()["messages"]
        assert len(messages) == 4

    @pytest.mark.asyncio
    async def test_send_message_failure_persists_error_row(
        self,
        client: AsyncClient,
        auth_headers: dict,
        test_org: Organization,
        db_session,
    ):
        """Agent crash → endpoint returns 200 SSE with 'error' event carrying
        error_code; the forensic ERROR row is written via AsyncSessionLocal."""
        created = await _create_session(client, auth_headers)
        session_id = created["id"]

        async def _boom(*args, **kwargs):
            raise ValueError("simulated agent failure")
            yield  # makes _boom an async generator; this line is never reached

        # Capture the ChatMessage objects passed to writer.add() so we can
        # assert the forensic row was constructed correctly without needing
        # cross-connection DB visibility.
        captured_rows: list[ChatMessage] = []

        class _FakeWriter:
            def add(self, obj):
                captured_rows.append(obj)

            async def commit(self):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *_):
                pass

        def _fake_session_local():
            return _FakeWriter()

        with (
            patch("app.api.endpoints.chat.send_message_streaming", new=_boom),
            patch("app.api.endpoints.chat.AsyncSessionLocal", new=_fake_session_local),
        ):
            async with client.stream(
                "POST",
                f"/chat/sessions/{session_id}/messages/stream",
                json={"content": "this will fail"},
                headers=auth_headers,
            ) as resp:
                body = ""
                async for chunk in resp.aiter_text():
                    body += chunk
                assert resp.status_code == 200

        events = _drain_sse(body)
        assert any(e["type"] == "error" for e in events)
        error_event = next(e for e in events if e["type"] == "error")
        assert "error_code" in error_event

        error_code = error_event["error_code"]

        # The forensic ERROR row was queued for writing
        assert len(captured_rows) == 1
        error_row = captured_rows[0]
        assert error_row.role == ChatMessageRole.ERROR
        assert "simulated agent failure" in error_row.content
        assert error_row.metadata_["error_type"] == "ValueError"
        assert "Traceback" in error_row.metadata_["traceback"]
        assert error_row.metadata_["error_code"] == error_code

        # GET session hides ERROR row from the thread (row not actually in DB
        # since we captured it, so the GET returns 0 error rows naturally)
        resp = await client.get(f"/chat/sessions/{session_id}", headers=auth_headers)
        messages = resp.json()["messages"]
        assert all(m["role"] != "error" for m in messages)


class TestSendChatMessageWithRAG:
    """Tests for RAG source retrieval in chat responses."""

    @pytest.fixture(autouse=True)
    def override_mocks(self):
        """Override the module-level mocks with RAG-aware ones."""
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
            "app.api.endpoints.chat.send_message_streaming",
            new=_make_streaming_mock(
                "Based on the Buffer Prep SOP [1], you should mix Tris-HCl.",
                fake_sources,
            ),
        ):
            yield

    @pytest.mark.asyncio
    async def test_message_returns_sources(
        self, client: AsyncClient, auth_headers: dict, test_org: Organization
    ):
        created = await _create_session(client, auth_headers)
        session_id = created["id"]

        status_code, events = await _stream_message(
            client, session_id, "How do I prepare buffer?", auth_headers
        )
        assert status_code == 200
        done = _done(events)
        assert len(done["sources"]) == 1
        source = done["sources"][0]
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

        await _stream_message(client, session_id, "Buffer question", auth_headers)

        # Get session and check assistant message metadata
        resp = await client.get(f"/chat/sessions/{session_id}", headers=auth_headers)
        messages = resp.json()["messages"]
        assistant_msg = [m for m in messages if m["role"] == "assistant"][0]
        assert assistant_msg["metadata_"] is not None
        assert "sources" in assistant_msg["metadata_"]
        assert len(assistant_msg["metadata_"]["sources"]) == 1
