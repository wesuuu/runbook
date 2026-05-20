"""Verify chat agent globalization doesn't leak state across requests.

Note: asyncio.gather with two coroutines on the same SQLAlchemy session
deadlocks in the SAVEPOINT-based test setup (the session uses a single
connection). We validate state-isolation by running two send_message
calls sequentially — this is sufficient to catch the _LiveState bleed
that could occur with the cache design, because the concern is that
state from call N corrupts call N+1's deps, not that they overlap in
wall-clock time.
"""

from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.iam import Organization, User
from app.services.ai.deps import RetrievedChunk
from app.services.ai.send_message import send_message_streaming
from app.services.ai.sessions import create_session


@pytest.mark.asyncio
async def test_sequential_runs_do_not_share_sources(
    db_session: AsyncSession,
    test_user: User,
    test_org: Organization,
    second_user: User,
    second_org: Organization,
):
    """Two sequential requests must have isolated deps.sources.

    With the _AGENT_CACHE + _LiveState design, the cache maps model-tuple →
    (agent, live). Each request calls live.set(new_state) before agent.run().
    This test verifies that call N+1 sees its own fresh CompactionState and
    does not inherit sources accumulated during call N.
    """
    sess1 = await create_session(db_session, user_id=test_user.id, org_id=test_org.id)
    sess2 = await create_session(
        db_session, user_id=second_user.id, org_id=second_org.id
    )

    fake_chunk_a = RetrievedChunk(
        document_id=uuid4(),
        document_slug="a",
        document_title="A",
        chunk_id=uuid4(),
        chunk_index=0,
        page_number=None,
        content="A-content",
        score=0.9,
    )
    fake_chunk_b = RetrievedChunk(
        document_id=uuid4(),
        document_slug="b",
        document_title="B",
        chunk_id=uuid4(),
        chunk_index=0,
        page_number=None,
        content="B-content",
        score=0.9,
    )

    call_count = {"n": 0}

    async def fake_run(prompt, deps, message_history=None, **kwargs):
        call_count["n"] += 1
        if call_count["n"] == 1:
            deps.sources.append(fake_chunk_a)
        else:
            deps.sources.append(fake_chunk_b)
        result = MagicMock()
        result.output = "ok"
        result.all_messages = MagicMock(return_value=[])
        return result

    fake_agent = MagicMock()
    fake_agent.run = fake_run

    async def fake_build(*args, **kwargs):
        return fake_agent

    async def drain(session):
        async for _ in send_message_streaming(
            db_session, session, "q", user_id=session.user_id, is_org_admin=False
        ):
            pass

    with patch("app.services.ai.send_message.build_chat_agent", fake_build):
        # Run sequentially — single-connection test sessions can't handle
        # concurrent awaits on the same session (SAVEPOINT deadlock).
        await drain(sess1)
        await drain(sess2)

    from sqlalchemy import select

    from app.models.chat import ChatMessage, ChatMessageRole

    res1 = await db_session.execute(
        select(ChatMessage).where(
            ChatMessage.session_id == sess1.id,
            ChatMessage.role == ChatMessageRole.ASSISTANT,
        )
    )
    res2 = await db_session.execute(
        select(ChatMessage).where(
            ChatMessage.session_id == sess2.id,
            ChatMessage.role == ChatMessageRole.ASSISTANT,
        )
    )
    msg1 = res1.scalar_one()
    msg2 = res2.scalar_one()
    sources1 = (msg1.metadata_ or {}).get("sources", [])
    sources2 = (msg2.metadata_ or {}).get("sources", [])
    titles1 = {s["document_title"] for s in sources1}
    titles2 = {s["document_title"] for s in sources2}
    assert (
        "A" in titles1 and "B" not in titles1
    ), f"sess1 should only have source A, got {titles1}"
    assert (
        "B" in titles2 and "A" not in titles2
    ), f"sess2 should only have source B, got {titles2}"
