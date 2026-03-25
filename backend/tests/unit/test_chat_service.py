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
    _format_rag_context,
    _org_has_documents,
    RetrievedChunk,
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


class TestFormatRagContext:
    def test_empty_sources_returns_empty(self):
        assert _format_rag_context([]) == ""

    def test_formats_single_source_with_page(self):
        chunk = RetrievedChunk(
            document_id=uuid.uuid4(),
            document_title="Buffer SOP",
            chunk_id=uuid.uuid4(),
            chunk_index=0,
            page_number=3,
            content="Mix Tris-HCl at pH 7.4",
            score=0.9,
        )
        result = _format_rag_context([chunk])
        assert "DOCUMENT CONTEXT" in result
        assert '[1] "Buffer SOP", page 3' in result
        assert "Mix Tris-HCl" in result

    def test_formats_source_without_page(self):
        chunk = RetrievedChunk(
            document_id=uuid.uuid4(),
            document_title="Notes",
            chunk_id=uuid.uuid4(),
            chunk_index=0,
            page_number=None,
            content="Some content",
            score=0.8,
        )
        result = _format_rag_context([chunk])
        assert '[1] "Notes":' in result
        assert "page" not in result.split("[1]")[1].split(":")[0]

    def test_formats_multiple_sources(self):
        chunks = [
            RetrievedChunk(
                document_id=uuid.uuid4(),
                document_title=f"Doc {i}",
                chunk_id=uuid.uuid4(),
                chunk_index=i,
                page_number=i + 1,
                content=f"Content {i}",
                score=0.9 - i * 0.1,
            )
            for i in range(3)
        ]
        result = _format_rag_context(chunks)
        assert "[1]" in result
        assert "[2]" in result
        assert "[3]" in result


class TestOrgHasDocuments:
    @pytest.mark.asyncio
    async def test_returns_false_for_empty_org(
        self, db_session: AsyncSession, org_id: uuid.UUID
    ):
        result = await _org_has_documents(db_session, org_id)
        assert result is False
