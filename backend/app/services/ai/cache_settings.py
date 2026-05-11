"""Shared model_settings for chat-agent prompt caching.

Anthropic-native models (``anthropic:claude-...``) honor the ``anthropic_cache_*``
keys via pydantic-ai's ``AnthropicModelSettings``. Other providers ignore them
silently, so it is safe to pass these settings unconditionally — they only take
effect when the resolved model is an Anthropic native one.

To activate caching, set the capability provider to ``anthropic`` (not
``openrouter``):

    BATCHRITE_AI_CHAT_PROVIDER=anthropic
    BATCHRITE_AI_CHAT_MODEL=claude-sonnet-4-5
    BATCHRITE_AI_CHAT_SUBAGENT_PROVIDER=anthropic
    BATCHRITE_AI_CHAT_SUBAGENT_MODEL=claude-haiku-4-5
    BATCHRITE_AI_CHAT_SUMMARY_PROVIDER=anthropic
    BATCHRITE_AI_CHAT_SUMMARY_MODEL=claude-sonnet-4-5
    BATCHRITE_ANTHROPIC__API_KEY=sk-ant-...

When active, Anthropic caches the system prompt + tool definitions for 5 minutes
and serves them at ~10% of the normal input price on follow-up calls. The
subagent's 4k-token prompt and ~3k of tool schemas dominate per-step token
spend, so the savings are substantial inside multi-step auto-fix loops.
"""

from __future__ import annotations

from typing import Any

CHAT_AGENT_MODEL_SETTINGS: dict[str, Any] = {
    "anthropic_cache_instructions": True,
    "anthropic_cache_tool_definitions": True,
}
