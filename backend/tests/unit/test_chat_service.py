import json
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

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
from app.services.ai.chat_service import (
    create_session,
    delete_session,
    get_session,
    list_sessions,
    estimate_tokens,
    estimate_messages_tokens,
    compact_history,
    _build_conversation_text,
    _truncate_to_fit,
    ChatDeps,
    RetrievedChunk,
    SearchDocumentsResult,
    search_documents_tool,
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
        deps = ChatDeps(
            db=MagicMock(), org_id=uuid.uuid4(),
            user_id=uuid.uuid4(), is_org_admin=False,
        )
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


# ─── Token Estimation Tests ───


class TestEstimateTokens:
    def test_basic_heuristic(self):
        # 4 chars per token
        assert estimate_tokens("abcd") == 1
        assert estimate_tokens("abcdefgh") == 2
        assert estimate_tokens("") == 0

    def test_longer_text(self):
        text = "a" * 400
        assert estimate_tokens(text) == 100

    def test_short_text_rounds_down(self):
        assert estimate_tokens("ab") == 0
        assert estimate_tokens("abc") == 0
        assert estimate_tokens("abcd") == 1


class TestEstimateMessagesTokens:
    def test_sums_across_messages(self):
        messages = [
            {
                "kind": "request",
                "parts": [
                    {"part_kind": "user-prompt", "content": "a" * 100}
                ],
            },
            {
                "kind": "response",
                "parts": [
                    {"part_kind": "text", "content": "b" * 200}
                ],
            },
        ]
        tokens = estimate_messages_tokens(messages)
        # Each message serializes to JSON; total should reflect both
        assert tokens > 0

    def test_strips_system_prompt_parts(self):
        msg_with_system = {
            "kind": "request",
            "parts": [
                {"part_kind": "system-prompt", "content": "x" * 1000},
                {"part_kind": "user-prompt", "content": "hello"},
            ],
        }
        msg_without_system = {
            "kind": "request",
            "parts": [
                {"part_kind": "user-prompt", "content": "hello"},
            ],
        }
        # With system prompt stripped, both should produce similar token counts
        tokens_with = estimate_messages_tokens([msg_with_system])
        tokens_without = estimate_messages_tokens([msg_without_system])
        assert tokens_with == tokens_without

    def test_empty_messages(self):
        assert estimate_messages_tokens([]) == 0


# ─── Conversation Text Building ───


class TestBuildConversationText:
    def test_builds_from_dict_messages(self):
        messages = [
            {
                "kind": "request",
                "parts": [
                    {"part_kind": "user-prompt", "content": "What is CHO?"},
                ],
            },
            {
                "kind": "response",
                "parts": [
                    {"part_kind": "text", "content": "CHO stands for Chinese Hamster Ovary."},
                ],
            },
        ]
        text = _build_conversation_text(messages)
        assert "User: What is CHO?" in text
        assert "Assistant: CHO stands for Chinese Hamster Ovary." in text

    def test_includes_existing_summary(self):
        text = _build_conversation_text([], existing_summary="Previous context here")
        assert "[Previous summary]: Previous context here" in text

    def test_truncates_long_tool_returns(self):
        messages = [
            {
                "kind": "request",
                "parts": [
                    {
                        "part_kind": "tool-return",
                        "tool_name": "search_documents",
                        "content": "x" * 500,
                    },
                ],
            },
        ]
        text = _build_conversation_text(messages)
        assert "..." in text
        # Tool return content should be truncated to 200 chars
        assert len(text) < 500


# ─── Truncate to Fit ───


class TestTruncateToFit:
    def test_removes_oldest_messages_first(self):
        messages = [
            {"kind": "request", "parts": [{"part_kind": "user-prompt", "content": "a" * 400}]},
            {"kind": "response", "parts": [{"part_kind": "text", "content": "b" * 400}]},
            {"kind": "request", "parts": [{"part_kind": "user-prompt", "content": "c" * 100}]},
        ]
        # Set a tight budget that can only fit the last message
        result = _truncate_to_fit(messages, 50)
        assert len(result) == 1
        assert result[0]["parts"][0]["content"] == "c" * 100

    def test_preserves_last_message(self):
        messages = [
            {"kind": "request", "parts": [{"part_kind": "user-prompt", "content": "a" * 10000}]},
        ]
        result = _truncate_to_fit(messages, 10)
        # Should always keep at least one message
        assert len(result) == 1

    def test_no_truncation_when_under_budget(self):
        messages = [
            {"kind": "request", "parts": [{"part_kind": "user-prompt", "content": "hi"}]},
        ]
        result = _truncate_to_fit(messages, 100000)
        assert len(result) == 1


# ─── Compact History ───


class TestCompactHistory:
    @pytest.mark.asyncio
    async def test_no_compaction_under_budget(
        self, db_session: AsyncSession, chat_session: ChatSession
    ):
        # Small messages, big budget
        messages = [
            {"kind": "request", "parts": [{"part_kind": "user-prompt", "content": "hi"}]},
            {"kind": "response", "parts": [{"part_kind": "text", "content": "hello"}]},
        ]
        result, summary = await compact_history(
            db=db_session,
            session_id=chat_session.id,
            messages=messages,
            token_budget=100000,
            model=MagicMock(),
            org_id=chat_session.org_id,
        )
        assert result == messages
        assert summary is None

    @pytest.mark.asyncio
    async def test_compaction_over_budget(
        self, db_session: AsyncSession, chat_session: ChatSession
    ):
        # Add some DB messages so the count query works
        for i in range(4):
            db_session.add(ChatMessage(
                session_id=chat_session.id,
                role=ChatMessageRole.USER if i % 2 == 0 else ChatMessageRole.ASSISTANT,
                content=f"Message {i}",
            ))
        await db_session.flush()

        # Create pydantic-ai style messages that exceed the budget
        messages = [
            {"kind": "request", "parts": [{"part_kind": "user-prompt", "content": "a" * 2000}]},
            {"kind": "response", "parts": [{"part_kind": "text", "content": "b" * 2000}]},
            {"kind": "request", "parts": [{"part_kind": "user-prompt", "content": "c" * 2000}]},
            {"kind": "response", "parts": [{"part_kind": "text", "content": "d" * 100}]},
        ]

        with patch(
            "app.services.ai.chat_service._generate_summary",
            new_callable=AsyncMock,
            return_value="Summary of the conversation.",
        ):
            result, summary = await compact_history(
                db=db_session,
                session_id=chat_session.id,
                messages=messages,
                token_budget=100,  # Very small budget to force compaction
                model=MagicMock(),
                org_id=chat_session.org_id,
            )

        assert summary == "Summary of the conversation."
        # Should have compacted: [summary_request] + [latest_message]
        assert len(result) == 2

    @pytest.mark.asyncio
    async def test_compaction_inserts_summary_message(
        self, db_session: AsyncSession, chat_session: ChatSession
    ):
        # Add DB messages
        db_session.add(ChatMessage(
            session_id=chat_session.id,
            role=ChatMessageRole.USER,
            content="Hello",
        ))
        await db_session.flush()

        messages = [
            {"kind": "request", "parts": [{"part_kind": "user-prompt", "content": "a" * 2000}]},
            {"kind": "response", "parts": [{"part_kind": "text", "content": "b" * 100}]},
        ]

        with patch(
            "app.services.ai.chat_service._generate_summary",
            new_callable=AsyncMock,
            return_value="Test summary content.",
        ):
            await compact_history(
                db=db_session,
                session_id=chat_session.id,
                messages=messages,
                token_budget=100,
                model=MagicMock(),
                org_id=chat_session.org_id,
            )

        # Verify summary message was inserted
        from sqlalchemy import select
        result = await db_session.execute(
            select(ChatMessage).where(
                ChatMessage.session_id == chat_session.id,
                ChatMessage.role == ChatMessageRole.SUMMARY,
            )
        )
        summary_msg = result.scalar_one_or_none()
        assert summary_msg is not None
        assert summary_msg.content == "Test summary content."
        assert summary_msg.metadata_["type"] == "summary"
        assert summary_msg.metadata_["summarized_message_count"] == 1
