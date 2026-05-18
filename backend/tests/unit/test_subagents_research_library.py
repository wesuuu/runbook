"""Tests for research_library subagent tools and config."""

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from pydantic_ai import RunContext

from app.services.ai.deps import ChatDeps, RetrievedChunk
from app.services.ai.subagents.research_library import build
from app.services.ai.subagents.research_library.tools import (
    list_documents,
    read_section,
    search_documents,
)


def make_ctx() -> RunContext[ChatDeps]:
    deps = ChatDeps(
        db=AsyncMock(),
        org_id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        is_org_admin=False,
    )
    ctx = MagicMock(spec=RunContext)
    ctx.deps = deps
    return ctx


def test_build_returns_subagent_config_with_required_fields():
    cfg = build("openai:gpt-4.1-mini")
    assert cfg["name"] == "research_library"
    assert "description" in cfg
    assert "instructions" in cfg
    assert cfg["model"] == "openai:gpt-4.1-mini"
    tools = cfg["agent_kwargs"]["tools"]
    assert search_documents in tools
    assert read_section in tools
    assert list_documents in tools


@pytest.mark.asyncio
async def test_search_documents_appends_to_sources(monkeypatch):
    ctx = make_ctx()
    fake_chunks = [
        RetrievedChunk(
            document_id=uuid.uuid4(),
            document_title="t",
            chunk_id=uuid.uuid4(),
            chunk_index=0,
            page_number=None,
            content="c",
            score=0.5,
        ),
    ]

    async def fake_retrieve(*args, **kwargs):
        return fake_chunks

    monkeypatch.setattr(
        "app.services.ai.subagents.research_library.tools.retrieve_relevant_chunks",
        fake_retrieve,
    )
    result = await search_documents(ctx, query="hello")
    assert result.total == 1
    assert ctx.deps.sources == fake_chunks
    assert ctx.deps.tool_calls[-1]["tool"] == "search_documents"
    assert ctx.deps.tool_calls[-1]["subagent"] == "research_library"


@pytest.mark.asyncio
async def test_search_documents_returns_no_results_message_when_empty(monkeypatch):
    ctx = make_ctx()

    async def fake_retrieve(*args, **kwargs):
        return []

    monkeypatch.setattr(
        "app.services.ai.subagents.research_library.tools.retrieve_relevant_chunks",
        fake_retrieve,
    )
    result = await search_documents(ctx, query="hello")
    assert result.total == 0
    assert "No matching" in result.message
