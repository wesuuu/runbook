"""Chat agent factory — composes capabilities + subagents.

Returns a fresh Agent per request scope. Globalization is in Task 23.
"""
from pathlib import Path
from uuid import UUID

from pydantic_ai import Agent
from pydantic_ai_summarization import ContextManagerCapability
from sqlalchemy.ext.asyncio import AsyncSession
from subagents_pydantic_ai import SubAgentCapability

from app.core.config import settings
from app.services.ai.ai_config import get_context_window, get_model
from app.services.ai.deps import ChatDeps
from app.services.ai.runtime.compaction import (
    CompactionState,
    make_compaction_hooks,
)
from app.services.ai.runtime.token_counting import tiktoken_counter
from app.services.ai.subagents import (
    protocol_builder,
    research_library,
    run_planner,
)

_PROMPTS_DIR = Path(__file__).parent / "prompts"
_CHAT_PROMPT = (_PROMPTS_DIR / "chat_agent.md").read_text()
_SUMMARY_PROMPT = (_PROMPTS_DIR / "summarization.md").read_text()


async def build_chat_agent(
    db: AsyncSession,
    org_id: UUID,
    compaction_state: CompactionState,
) -> Agent[ChatDeps, str]:
    """Build the chat agent for a given org's request scope."""
    chat_model = await get_model("chat", db, org_id=org_id)
    subagent_model = await get_model("chat_subagent", db, org_id=org_id)
    summary_model = await get_model("chat_summary", db, org_id=org_id)
    context_window = await get_context_window("chat", db, org_id=org_id)

    subagents = [
        research_library.build(subagent_model),
        protocol_builder.build(subagent_model),
        run_planner.build(subagent_model),
    ]

    on_before, on_after = make_compaction_hooks(compaction_state)

    return Agent(
        chat_model,
        instructions=_CHAT_PROMPT,
        deps_type=ChatDeps,
        capabilities=[
            SubAgentCapability(
                subagents=subagents,
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
        ],
        tools=[],
    )
