"""Integration tests for F-0089 library-sourced protocol creation."""

from unittest.mock import patch

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_skill_id_prefixes_model_visible_content_but_not_db(
    client: AsyncClient,
    auth_headers: dict,
    test_org,
    db_session,
) -> None:
    """skill_id on the request must prepend [skill:<id>] to the model-visible
    user_content but keep the DB-persisted content clean.
    """
    sess_resp = await client.post("/chat/sessions", json={}, headers=auth_headers)
    assert sess_resp.status_code == 201
    session_id = sess_resp.json()["id"]

    captured: dict = {}

    async def fake_send_message_streaming(db, session, user_content, **kwargs):
        captured["user_content"] = user_content
        captured["skill_id"] = kwargs.get("skill_id")
        yield {
            "type": "done",
            "user_message": {
                "id": "u1",
                "session_id": str(session.id),
                "role": "user",
                "content": "draft a media prep protocol",
                "metadata_": None,
                "created_at": "2026-01-01",
            },
            "assistant_message": {
                "id": "a1",
                "session_id": str(session.id),
                "role": "assistant",
                "content": "ok",
                "metadata_": None,
                "created_at": "2026-01-01",
            },
            "sources": [],
        }

    with patch(
        "app.api.endpoints.chat.send_message_streaming",
        side_effect=fake_send_message_streaming,
    ):
        async with client.stream(
            "POST",
            f"/chat/sessions/{session_id}/messages/stream",
            json={
                "content": "draft a media prep protocol",
                "skill_id": "new-protocol",
            },
            headers=auth_headers,
        ) as resp:
            assert resp.status_code == 200
            async for _ in resp.aiter_text():
                pass

    assert captured["skill_id"] == "new-protocol", (
        "Endpoint must forward skill_id to send_message_streaming"
    )
    assert captured["user_content"] == "draft a media prep protocol"


@pytest.mark.asyncio
async def test_skill_prefix_lands_in_serialized_message_history(
    db_session, test_org, test_user
) -> None:
    """After turn 1, the `[skill:<id>]` prefix must be present in the
    user-request part of `session.ai_message_history`.

    This is the load-bearing assertion for the whole skill-activation
    contract: it proves the prefix reached agent.run (and therefore the
    model) AND that it survives serialization for turn 2 to see. Inspecting
    `ai_message_history` via `ModelMessagesTypeAdapter` uses pydantic-ai's
    stable public API.
    """
    from app.models.chat import ChatSession
    from app.services.ai.send_message import send_message_streaming
    from pydantic_ai.messages import ModelMessagesTypeAdapter
    from pydantic_ai.models.test import TestModel
    from pydantic_ai import Agent
    from sqlalchemy import text as sa_text

    session = ChatSession(org_id=test_org.id, user_id=test_user.id, title="New Chat")
    db_session.add(session)
    await db_session.flush()

    with patch("app.services.ai.send_message.build_chat_agent") as mock_build:

        async def _build(*_a, **_kw):
            from app.services.ai.deps import ChatDeps
            return Agent(TestModel(), deps_type=ChatDeps)

        mock_build.side_effect = _build

        async for _ in send_message_streaming(
            db_session,
            session,
            user_content="draft me a protocol",
            user_id=test_user.id,
            is_org_admin=False,
            skill_id="new-protocol",
        ):
            pass

    await db_session.refresh(session)

    rows = (
        await db_session.execute(
            sa_text(
                "SELECT content FROM chat_messages "
                "WHERE session_id = :sid AND role = 'user'"
            ),
            {"sid": str(session.id)},
        )
    ).fetchall()
    assert any(r.content == "draft me a protocol" for r in rows), (
        "Persisted user message must be the clean text"
    )

    assert session.ai_message_history, "ai_message_history must be populated"
    msgs = ModelMessagesTypeAdapter.validate_python(session.ai_message_history)
    user_prompts: list[str] = []
    for m in msgs:
        for part in getattr(m, "parts", []):
            if getattr(part, "part_kind", None) == "user-prompt":
                user_prompts.append(part.content)
    assert any("[skill:new-protocol]" in p for p in user_prompts), (
        f"Prefix not found in serialized history user-prompts: {user_prompts!r}"
    )
