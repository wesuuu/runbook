"""Integration tests for F-0089 library-sourced protocol creation."""

import json
from unittest.mock import patch

import pytest
from httpx import AsyncClient
from pydantic_ai.messages import ModelMessage, ModelResponse, TextPart, ToolCallPart
from pydantic_ai.models.function import AgentInfo, DeltaToolCall, FunctionModel


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

    assert (
        captured["skill_id"] == "new-protocol"
    ), "Endpoint must forward skill_id to send_message_streaming"
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
    from pydantic_ai import Agent
    from pydantic_ai.messages import ModelMessagesTypeAdapter
    from pydantic_ai.models.test import TestModel
    from sqlalchemy import text as sa_text

    from app.models.chat import ChatSession
    from app.services.ai.send_message import send_message_streaming

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
    assert any(
        r.content == "draft me a protocol" for r in rows
    ), "Persisted user message must be the clean text"

    assert session.ai_message_history, "ai_message_history must be populated"
    msgs = ModelMessagesTypeAdapter.validate_python(session.ai_message_history)
    user_prompts: list[str] = []
    for m in msgs:
        for part in getattr(m, "parts", []):
            if getattr(part, "part_kind", None) == "user-prompt":
                user_prompts.append(part.content)
    assert any(
        "[skill:new-protocol]" in p for p in user_prompts
    ), f"Prefix not found in serialized history user-prompts: {user_prompts!r}"


def _scripted_model(script: list[ModelResponse]) -> FunctionModel:
    """FunctionModel that replays a fixed sequence of responses.

    Note: FunctionModel's cursor advances on EVERY model call, including
    subagent calls. The script must therefore include responses for the
    subagent runs we expect to be triggered, in order. Keep the script as
    short as possible and let the trailing default "done" cover overflow.

    The chat agent attaches an ``event_stream_handler`` so every model call
    is streamed; we therefore also supply a ``stream_function`` that yields
    the same scripted responses as deltas.
    """
    iteration = {"n": 0}

    def _next() -> ModelResponse:
        n = iteration["n"]
        iteration["n"] = n + 1
        if n < len(script):
            return script[n]
        return ModelResponse(parts=[TextPart(content="done")])

    async def call(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        return _next()

    async def stream_call(messages: list[ModelMessage], info: AgentInfo):
        response = _next()
        for idx, part in enumerate(response.parts):
            if isinstance(part, TextPart):
                yield part.content
            elif isinstance(part, ToolCallPart):
                args = part.args
                json_args = args if isinstance(args, str) else json.dumps(args)
                key = part.tool_call_id or f"call_{idx}"
                yield {
                    key: DeltaToolCall(
                        name=part.tool_name,
                        json_args=json_args,
                        tool_call_id=part.tool_call_id,
                    )
                }

    return FunctionModel(function=call, stream_function=stream_call)


@pytest.mark.asyncio
async def test_library_source_flow_dispatches_research_then_creator(
    client: AsyncClient, auth_headers: dict, test_org, test_user, db_session
) -> None:
    """Library happy path: user picks Library -> research_library is dispatched
    -> protocol_creator receives a brief with a ``grounding:`` section listing
    the retrieved document title and chunk text.

    This is the only integration test in the F-0089 source-path matrix. The
    other three source paths (OpenWetWare, From scratch, Search all) are
    covered by Task 1's SKILL.md routing tests, Task 4's chat_agent.md
    guardrail tests, Task 6's protocol_creator grounding tests, and Task 10's
    manual QA walk-through.
    """
    from app.models.library import Document, DocumentChunk, DocumentStatus

    doc = Document(
        org_id=test_org.id,
        uploaded_by_id=test_user.id,
        title="Lyophilization SOP v2",
        slug="lyophilization-sop-v2",
        original_filename="lyo.pdf",
        mime_type="application/pdf",
        file_size_bytes=1024,
        file_path="uploads/lyo.pdf",
        status=DocumentStatus.INDEXED.value,
    )
    db_session.add(doc)
    await db_session.flush()
    db_session.add(
        DocumentChunk(
            document_id=doc.id,
            chunk_index=0,
            content="Pre-freeze to -40C for 2 hours before applying vacuum.",
            token_count=10,
        )
    )
    await db_session.flush()

    captured: list[dict] = []

    async def fake_task(subagent_name: str, task: str):
        captured.append({"name": subagent_name, "task": task})
        if subagent_name == "research_library":
            return {
                "total": 1,
                "chunks": [
                    {
                        "document_id": str(doc.id),
                        "document_title": "Lyophilization SOP v2",
                        "content": "Pre-freeze to -40C for 2 hours.",
                        "score": 0.9,
                    }
                ],
                "message": "",
            }
        if subagent_name == "protocol_creator":
            return {
                "protocol_id": "created",
                "description": (
                    "Lyo protocol\n\nGrounded in: 1 library document(s):\n"
                    "- Lyophilization SOP v2"
                ),
            }
        return {}

    # Scripted parent model. The plan template included a `load_skill` call,
    # but since we replace the entire chat agent with a bare Agent (no
    # SkillsCapability), `load_skill` is not a registered tool. Skip straight
    # to the picker reply, then dispatch research_library, then
    # protocol_creator with a grounded brief.
    script_turn1 = [
        ModelResponse(
            parts=[
                TextPart(
                    content=(
                        "Pick a source: 1) Library 2) OpenWetWare "
                        "3) From scratch 4) Search all"
                    )
                )
            ]
        ),
    ]
    script_turn2 = [
        ModelResponse(
            parts=[
                ToolCallPart(
                    tool_name="task",
                    args={
                        "subagent_name": "research_library",
                        "task": "lyophilization",
                    },
                )
            ]
        ),
        ModelResponse(
            parts=[
                ToolCallPart(
                    tool_name="task",
                    args={
                        "subagent_name": "protocol_creator",
                        "task": (
                            "lyophilization protocol\n\n"
                            "grounding:\n- title: Lyophilization SOP v2\n"
                            "  chunks:\n"
                            "    - Pre-freeze to -40C for 2 hours."
                        ),
                    },
                )
            ]
        ),
        ModelResponse(
            parts=[TextPart(content="Created protocol grounded in your library.")]
        ),
    ]

    # Two independent scripts because each turn rebuilds the agent and we want
    # the cursor to restart per turn.
    scripts_iter = iter([script_turn1, script_turn2])

    with patch("app.services.ai.send_message.build_chat_agent") as mock_build:
        from pydantic_ai import Agent

        from app.services.ai.deps import ChatDeps

        async def _build(*_a, **_kw):
            script = next(scripts_iter, [])
            agent = Agent(_scripted_model(script), deps_type=ChatDeps)
            agent.tool_plain(fake_task, name="task")
            return agent

        mock_build.side_effect = _build

        sess_resp = await client.post("/chat/sessions", json={}, headers=auth_headers)
        assert sess_resp.status_code == 201
        session_id = sess_resp.json()["id"]

        async with client.stream(
            "POST",
            f"/chat/sessions/{session_id}/messages/stream",
            json={
                "content": "draft a lyophilization protocol",
                "skill_id": "new-protocol",
            },
            headers=auth_headers,
        ) as r1:
            assert r1.status_code == 200
            async for _ in r1.aiter_text():
                pass

        async with client.stream(
            "POST",
            f"/chat/sessions/{session_id}/messages/stream",
            json={"content": "Library"},
            headers=auth_headers,
        ) as r2:
            assert r2.status_code == 200
            async for _ in r2.aiter_text():
                pass

    dispatched_names = [c["name"] for c in captured]
    assert (
        "research_library" in dispatched_names
    ), f"Library path must dispatch research_library; got {dispatched_names}"
    assert (
        "protocol_creator" in dispatched_names
    ), f"Library path must dispatch protocol_creator; got {dispatched_names}"
    assert captured[0]["name"] == "research_library"
    assert captured[1]["name"] == "protocol_creator"
    creator_call = next(c for c in captured if c["name"] == "protocol_creator")
    assert "grounding:" in creator_call["task"].lower()
    assert "Lyophilization SOP v2" in creator_call["task"]
