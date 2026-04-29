"""Tests for chat_agent.build_chat_agent — construction without LLM call."""
import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.ai.chat_agent import build_chat_agent
from app.services.ai.runtime.compaction import CompactionState


@pytest.mark.asyncio
async def test_build_chat_agent_returns_agent_with_capabilities():
    db = MagicMock()
    org_id = MagicMock()
    state = CompactionState()

    fake_chat_model = "openai:gpt-4.1-mini"
    fake_subagent_model = "openai:gpt-4.1-mini"
    fake_summary_model = "openai:gpt-4.1-mini"

    async def fake_get_model(cap, db_, org_id=None):
        return {
            "chat": fake_chat_model,
            "chat_subagent": fake_subagent_model,
            "chat_summary": fake_summary_model,
        }[cap]

    async def fake_get_context_window(cap, db_, org_id=None):
        return 100_000

    # SubAgentCapability and pydantic-ai Agent both eagerly resolve OpenAI
    # providers at construction time (before any LLM call). Supply a sentinel
    # key so the SDK does not raise "missing API key" during the unit test.
    with patch("app.services.ai.chat_agent.get_model", fake_get_model), \
         patch("app.services.ai.chat_agent.get_context_window", fake_get_context_window), \
         patch.dict(os.environ, {"OPENAI_API_KEY": "sk-test-unit"}):
        agent = await build_chat_agent(db, org_id, state)
    assert agent is not None
