"""Chat agent factory — composes capabilities + subagents.

Agents are cached per (chat_model, subagent_model, summary_model, context_window)
tuple. Per-request CompactionState is passed through a mutable _LiveState
indirection so cached compaction hooks always read the current request's state.
"""

import functools
from pathlib import Path
from typing import Any, Callable
from uuid import UUID

from pydantic_ai import Agent, Tool
from pydantic_ai.tools import DeferredToolRequests
from pydantic_ai_skills import SkillsCapability
from pydantic_ai_summarization import ContextManagerCapability
from sqlalchemy.ext.asyncio import AsyncSession
from subagents_pydantic_ai import SubAgentCapability

from app.core.config import settings
from app.services.ai.ai_config import get_context_window, get_model
from app.services.ai.cache_settings import CHAT_AGENT_MODEL_SETTINGS
from app.services.ai.deps import ChatDeps
from app.services.ai.runtime.compaction import CompactionState
from app.services.ai.runtime.token_counting import tiktoken_counter
from app.services.ai.subagents import (
    protocol_creator,
    protocol_editor,
    protocol_knowledgebase,
    research_library,
    run_planner,
)
from app.services.ai.tools.external_protocols import (
    create_protocol_from_external_source,
)

_PROMPTS_DIR = Path(__file__).parent / "prompts"
_CHAT_PROMPT = (_PROMPTS_DIR / "chat_agent.md").read_text()
_SUMMARY_PROMPT = (_PROMPTS_DIR / "summarization.md").read_text()

# Module-level agent cache: (chat_model, subagent_model, summary_model,
# context_window) -> (Agent, _LiveState)
_AGENT_CACHE: dict[tuple[str, ...], tuple[Agent, "_LiveState"]] = {}


class _LiveState:
    """Mutable indirection so cached compaction hooks see the current request's
    CompactionState. Each request calls live.set(state) immediately before
    agent.run(); hooks close over the _LiveState object (not the state value).
    """

    def __init__(self) -> None:
        self._state: CompactionState | None = None

    def set(self, state: CompactionState) -> None:
        self._state = state

    @property
    def state(self) -> CompactionState | None:
        return self._state


def _wrap_tool_with_events(tool: Callable[..., Any]) -> Callable[..., Any]:
    """Wrap a subagent tool so it emits tool_start / tool_end events via
    `ctx.deps.tool_event_callback`.

    We do this at the tool layer rather than via `event_stream_handler` on the
    subagent Agent because setting that handler forces pydantic-ai to call the
    model in streaming mode, which some providers (e.g. Ollama's
    gpt-oss:120b-cloud) reject with HTTP 400 on multi-turn tool dialogs.

    `functools.wraps` copies `__wrapped__`, which `inspect.signature` follows
    so pydantic-ai still derives the correct LLM-facing tool schema.
    """
    tool_name = getattr(tool, "__name__", None) or "unknown"

    @functools.wraps(tool)
    async def wrapped(ctx: Any, *args: Any, **kwargs: Any) -> Any:
        cb = getattr(ctx.deps, "tool_event_callback", None)
        if cb is not None:
            await cb("tool_start", tool_name)
        try:
            return await tool(ctx, *args, **kwargs)
        finally:
            if cb is not None:
                await cb("tool_end", tool_name)

    return wrapped


def _cache_key(
    chat_model: Any,
    subagent_model: Any,
    creation_model: Any,
    editing_model: Any,
    summary_model: Any,
    context_window: int,
) -> tuple[str, ...]:
    return (
        str(chat_model),
        str(subagent_model),
        str(creation_model),
        str(editing_model),
        str(summary_model),
        str(context_window),
    )


def _make_live_hooks(
    live: _LiveState,
) -> tuple[
    Callable[..., None],
    Callable[..., str | None],
]:
    """Return (on_before, on_after) closures that read from live.state."""

    def on_before(messages: list, cutoff_index: int) -> None:
        state = live.state
        if state is None:
            return
        state.triggered = True
        state.summarized_message_count = cutoff_index

    def on_after(messages: list) -> str | None:
        # Lazy import to avoid circular imports at module load time
        from pydantic_ai.messages import ModelRequest, SystemPromptPart

        state = live.state
        if state is None:
            return None
        if messages:
            first = messages[0]
            if isinstance(first, ModelRequest):
                for part in first.parts:
                    if isinstance(part, SystemPromptPart):
                        state.summary_text = part.content
                        break
        return None  # don't modify the summary

    return on_before, on_after


def _reset_cache_for_tests() -> None:
    """Clear the module-level agent cache. Call from test fixtures only."""
    _AGENT_CACHE.clear()


async def build_chat_agent(
    db: AsyncSession,
    org_id: UUID,
    compaction_state: CompactionState,
) -> Agent[ChatDeps, str | DeferredToolRequests]:
    """Build (or return cached) the chat agent, wired to the current request's
    CompactionState via _LiveState indirection.

    The Agent is cached per (chat_model, subagent_model, summary_model,
    context_window) tuple. Two orgs that resolve to the same models share an
    Agent instance — safe because all per-request state lives in ChatDeps and
    CompactionState, not in the Agent itself.

    Subagent tool functions are wrapped at cache-construction time to emit
    tool_start / tool_end events via `ctx.deps.tool_event_callback`. The
    callback is set per-request in `send_message_streaming`.
    """
    chat_model = await get_model("chat", db, org_id=org_id)
    subagent_model = await get_model("chat_subagent", db, org_id=org_id)
    creation_model = await get_model("protocol_creation", db, org_id=org_id)
    editing_model = await get_model("protocol_editing", db, org_id=org_id)
    summary_model = await get_model("chat_summary", db, org_id=org_id)
    context_window = await get_context_window("chat", db, org_id=org_id)

    key = _cache_key(
        chat_model,
        subagent_model,
        creation_model,
        editing_model,
        summary_model,
        context_window,
    )

    if key not in _AGENT_CACHE:
        subagents = [
            research_library.build(subagent_model),
            protocol_creator.build(creation_model),
            protocol_editor.build(editing_model),
            run_planner.build(subagent_model),
            protocol_knowledgebase.build(subagent_model),
        ]

        # Wrap each subagent's tool functions so their tool calls surface in
        # the parent's SSE stream via ctx.deps.tool_event_callback.
        for sub in subagents:
            sub_kwargs = dict(sub.get("agent_kwargs") or {})
            tools = sub_kwargs.get("tools")
            if tools:
                sub_kwargs["tools"] = [_wrap_tool_with_events(t) for t in tools]
                sub["agent_kwargs"] = sub_kwargs

        live = _LiveState()
        on_before, on_after = _make_live_hooks(live)

        agent: Agent[ChatDeps, str | DeferredToolRequests] = Agent(
            chat_model,
            instructions=_CHAT_PROMPT,
            deps_type=ChatDeps,
            model_settings=CHAT_AGENT_MODEL_SETTINGS,
            capabilities=[
                SubAgentCapability(
                    subagents=subagents,
                    default_model=subagent_model,
                    include_general_purpose=False,
                    max_nesting_depth=1,
                ),
                ContextManagerCapability(
                    max_tokens=context_window,
                    compress_threshold=settings.compaction_threshold,
                    summarization_model=summary_model,
                    summary_prompt=_SUMMARY_PROMPT,
                    max_tool_output_tokens=2000,
                    token_counter=tiktoken_counter,
                    on_before_compress=on_before,
                    on_after_compress=on_after,
                ),
                SkillsCapability(
                    directories=[str(Path(settings.skills_dir))],
                ),
            ],
            tools=[
                Tool(
                    create_protocol_from_external_source,
                    requires_approval=True,
                ),
            ],
            output_type=[str, DeferredToolRequests],
        )
        _AGENT_CACHE[key] = (agent, live)

    agent, live = _AGENT_CACHE[key]
    live.set(compaction_state)
    return agent
