import uuid

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.chat import (
    ChatMessage,
    ChatMessageRole,
    ChatSession,
    ChatSessionStatus,
)
from app.models.iam import Organization, OrganizationMember, User
from app.services.chat_service import (
    create_session,
    delete_session,
    get_session,
    list_sessions,
    _get_message_history,
    ChatDeps,
    RetrievedChunk,
    SearchDocumentsResult,
    search_documents_tool,
    MAX_CONTEXT_MESSAGES,
)


@pytest_asyncio.fixture
async def org_id(db_session: AsyncSession, test_org: Organization) -> uuid.UUID:
    return test_org.id


@pytest_asyncio.fixture
async def user_id(db_session: AsyncSession, test_user: User) -> uuid.UUID:
    return test_user.id


@pytest_asyncio.fixture
async def chat_session(
    db_session: AsyncSession, user_id: uuid.UUID, org_id: uuid.UUID
) -> ChatSession:
    session = await create_session(db_session, user_id, org_id, title="Test Chat")
    await db_session.flush()
    return session


class TestCreateSession:
    @pytest.mark.asyncio
    async def test_creates_session_with_defaults(
        self, db_session: AsyncSession, user_id: uuid.UUID, org_id: uuid.UUID
    ):
        session = await create_session(db_session, user_id, org_id)
        assert session.id is not None
        assert session.user_id == user_id
        assert session.org_id == org_id
        assert session.title == "New Chat"
        assert session.status == ChatSessionStatus.ACTIVE

    @pytest.mark.asyncio
    async def test_creates_session_with_custom_title(
        self, db_session: AsyncSession, user_id: uuid.UUID, org_id: uuid.UUID
    ):
        session = await create_session(
            db_session, user_id, org_id, title="My Research Chat"
        )
        assert session.title == "My Research Chat"

    @pytest.mark.asyncio
    async def test_creates_session_with_document_ids(
        self, db_session: AsyncSession, user_id: uuid.UUID, org_id: uuid.UUID
    ):
        doc_id = uuid.uuid4()
        session = await create_session(
            db_session,
            user_id,
            org_id,
            context_document_ids=[doc_id],
        )
        assert session.context_document_ids == [str(doc_id)]


class TestGetSession:
    @pytest.mark.asyncio
    async def test_returns_session_with_messages(
        self, db_session: AsyncSession, chat_session: ChatSession
    ):
        # Add a message
        msg = ChatMessage(
            session_id=chat_session.id,
            role=ChatMessageRole.USER,
            content="Hello",
        )
        db_session.add(msg)
        await db_session.flush()

        result = await get_session(db_session, chat_session.id)
        assert result is not None
        assert result.id == chat_session.id
        assert len(result.messages) == 1
        assert result.messages[0].content == "Hello"

    @pytest.mark.asyncio
    async def test_returns_none_for_missing_session(
        self, db_session: AsyncSession
    ):
        result = await get_session(db_session, uuid.uuid4())
        assert result is None


class TestListSessions:
    @pytest.mark.asyncio
    async def test_lists_user_sessions(
        self, db_session: AsyncSession, user_id: uuid.UUID, org_id: uuid.UUID
    ):
        await create_session(db_session, user_id, org_id, title="Chat 1")
        await create_session(db_session, user_id, org_id, title="Chat 2")
        await db_session.flush()

        sessions, total = await list_sessions(db_session, user_id, org_id)
        assert total == 2
        assert len(sessions) == 2

    @pytest.mark.asyncio
    async def test_does_not_list_other_users_sessions(
        self,
        db_session: AsyncSession,
        user_id: uuid.UUID,
        org_id: uuid.UUID,
        second_user: User,
    ):
        await create_session(db_session, user_id, org_id, title="My Chat")
        await db_session.flush()

        sessions, total = await list_sessions(
            db_session, second_user.id, org_id
        )
        assert total == 0

    @pytest.mark.asyncio
    async def test_pagination(
        self, db_session: AsyncSession, user_id: uuid.UUID, org_id: uuid.UUID
    ):
        for i in range(5):
            await create_session(db_session, user_id, org_id, title=f"Chat {i}")
        await db_session.flush()

        sessions, total = await list_sessions(
            db_session, user_id, org_id, limit=2, offset=0
        )
        assert total == 5
        assert len(sessions) == 2


class TestDeleteSession:
    @pytest.mark.asyncio
    async def test_deletes_session(
        self, db_session: AsyncSession, chat_session: ChatSession
    ):
        session_id = chat_session.id
        await delete_session(db_session, chat_session)
        await db_session.flush()

        result = await get_session(db_session, session_id)
        assert result is None


class TestGetMessageHistory:
    @pytest.mark.asyncio
    async def test_returns_messages_in_order(
        self, db_session: AsyncSession, chat_session: ChatSession
    ):
        db_session.add(
            ChatMessage(
                session_id=chat_session.id,
                role=ChatMessageRole.USER,
                content="First",
            )
        )
        db_session.add(
            ChatMessage(
                session_id=chat_session.id,
                role=ChatMessageRole.ASSISTANT,
                content="Reply",
            )
        )
        await db_session.flush()

        history = await _get_message_history(db_session, chat_session.id)
        assert len(history) == 2
        assert history[0]["role"] == "user"
        assert history[0]["content"] == "First"
        assert history[1]["role"] == "assistant"

    @pytest.mark.asyncio
    async def test_truncates_to_max_context(
        self, db_session: AsyncSession, chat_session: ChatSession
    ):
        for i in range(MAX_CONTEXT_MESSAGES + 10):
            db_session.add(
                ChatMessage(
                    session_id=chat_session.id,
                    role=ChatMessageRole.USER,
                    content=f"Message {i}",
                )
            )
        await db_session.flush()

        history = await _get_message_history(db_session, chat_session.id)
        assert len(history) == MAX_CONTEXT_MESSAGES


class TestSearchDocumentsToolResult:
    def test_search_result_model_structure(self):
        result = SearchDocumentsResult(
            results=[],
            total=0,
            message="No matching documents found in the library",
        )
        assert result.total == 0
        assert result.message == "No matching documents found in the library"
        assert result.results == []

    def test_chat_deps_accumulates_sources(self):
        from unittest.mock import MagicMock
        deps = ChatDeps(db=MagicMock(), org_id=uuid.uuid4())
        assert deps.sources == []
        assert deps.tool_calls == []

        chunk = RetrievedChunk(
            document_id=uuid.uuid4(),
            document_title="Test Doc",
            chunk_id=uuid.uuid4(),
            chunk_index=0,
            page_number=1,
            content="Test content",
            score=0.9,
        )
        deps.sources.append(chunk)
        deps.tool_calls.append({"tool": "search_documents", "query": "test", "results": 1})
        assert len(deps.sources) == 1
        assert len(deps.tool_calls) == 1

    def test_source_deduplication(self):
        chunk_id = uuid.uuid4()
        doc_id = uuid.uuid4()
        chunks = [
            RetrievedChunk(
                document_id=doc_id,
                document_title="Doc",
                chunk_id=chunk_id,
                chunk_index=0,
                page_number=1,
                content="Content",
                score=0.9,
            ),
            RetrievedChunk(
                document_id=doc_id,
                document_title="Doc",
                chunk_id=chunk_id,
                chunk_index=0,
                page_number=1,
                content="Content",
                score=0.85,
            ),
        ]
        seen_ids = set()
        unique = []
        for s in chunks:
            if s.chunk_id not in seen_ids:
                seen_ids.add(s.chunk_id)
                unique.append(s)
        assert len(unique) == 1
