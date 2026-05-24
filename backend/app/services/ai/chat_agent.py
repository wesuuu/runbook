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
    app_help,
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
_CHAT_PROMPT_TEMPLATE = (_PROMPTS_DIR / "chat_agent.md").read_text()
_SUMMARY_PROMPT = (_PROMPTS_DIR / "summarization.md").read_text()

_EXTERNAL_PROTOCOLS_ONE_LINER = (
    "- `protocol_knowledgebase` — search {source_names} for public "
    "protocols the user doesn't already have."
)

_EXTERNAL_PROTOCOLS_DISPATCH_RULE = """\
1. **External / public protocol → `protocol_knowledgebase`.** If the user
   asks you to FIND, LOOK UP, SEARCH FOR, or GET a protocol they don't
   already have — anything like "find a protocol for X", "do you have a
   protocol for Y", "look up {source_names}", "I need a protocol for…",
   "is there a published protocol for…" — IMMEDIATELY call
   `task("protocol_knowledgebase", "<restated request>")`. This is the
   ONLY way to search {source_names}. You have no built-in knowledge of
   what's there.

When unsure between (1) and (2): if the user did NOT name a specific
existing protocol, default to (1) `protocol_knowledgebase` — searching
the public knowledge base is cheap and the right move when they're
asking "do you have…" or "find me…".\
"""

_EXTERNAL_PROTOCOLS_SECTION_TEMPLATE = """\
## External protocols ({source_names})

When the user asks for a public protocol, a protocol they don't have, or
something "from {source_names}", dispatch the `protocol_knowledgebase`
subagent. It returns a markdown list of candidates plus a fenced
`EXTERNAL_PROTOCOL_SOURCE` JSON block.

Surface the candidates to the user. Do NOT call any creation tool yet.

If `protocol_knowledgebase` reports the source is **unreachable** or an
**upstream outage** (rather than "no matching protocol"), relay that to
the user once and offer alternatives — search their library, or draft
from scratch. Do NOT re-dispatch `protocol_knowledgebase` to retry; the
outage will still be there. Re-dispatch at most twice for one request,
and only to refine a query that genuinely returned the wrong matches.

If the user wants to refine — different selection, different organism,
different steps — chat with them. You may re-dispatch
`protocol_knowledgebase` with a refined query. Reflect any user-requested
parameter overrides back at them in plain language before proceeding.

When the user explicitly confirms ("yes, convert it" / "create it" /
"draft this one"), you MUST first ask which project this protocol
belongs to so the user can see and confirm the destination on the
approval card. Phrase it tightly, e.g. "Which project should I put
this in?". Do NOT call the approval tool until the user answers.

Once you have a project name, call the parent tool
`create_protocol_from_external_source(source_url, title, project_name)`
using the chosen candidate's `source_url` and `title` from the
`EXTERNAL_PROTOCOL_SOURCE` block plus the user-supplied `project_name`.

**CRITICAL — never synthesize a `source_url`.** Only use a URL that
literally appears in the most recent `EXTERNAL_PROTOCOL_SOURCE` block.
If the user names a protocol that is NOT in the current candidate list,
you MUST re-dispatch `protocol_knowledgebase` with a refined query first,
wait for the new `EXTERNAL_PROTOCOL_SOURCE` block, and only then call
the approval tool with the URL from that block. Guessing a URL produces
a broken approval card.

The full payload is cached server-side when the subagent fetched the
page; you do NOT pass the JSON across this tool. This tool requires the
user's approval — the run will pause and a confirmation card is shown.
The user may inline-edit the procedure (add / remove / edit steps) on
that card before approving; their edits are applied server-side, so by
the time the tool body runs, the cached payload already reflects them
and the deviations array is populated. You do nothing special — just
hand the result off to protocol_creator.

After the tool returns a string starting with `EXTERNAL_PROTOCOL_APPROVED`,
the next line is the project name, the line after that is a JSON array of
deviations the user made on the approval card (possibly `[]`), and the
line after that is the payload JSON (already reflecting any edits).
Dispatch `protocol_creator` with a prompt of the form:

  "Draft a protocol in project <project_name> from the following external
  source. The payload steps are already the user-approved version — copy
  them verbatim. Cite the source URL in the description. If the
  deviations list is non-empty, note it under a 'Deviations from source'
  heading in the description. Deviations: <deviations JSON>.
  EXTERNAL_PROTOCOL_SOURCE:
  <payload JSON returned by the approval tool>"

Never call `create_protocol_from_external_source` without an explicit
in-turn user confirmation AND a project name. Never invent a payload —
the cached payload is the only source of truth.

### MANDATORY final reply after a successful import

When `protocol_creator` returns a successful result, your final reply to
the user MUST include BOTH of these as inline markdown links, with no
exceptions:

1. The `protocol_markdown_link` field from the `create_protocol` result,
   emitted verbatim. The server has computed the correct URL — do NOT
   construct your own.
2. A link to the original source page from the `EXTERNAL_PROTOCOL_SOURCE`
   payload's `source_url`, labeled by source:
{source_link_labels}

Example final reply:

  "Drafted [Heat-shock transformation of E. coli](/acme/protocols/heat-shock-transformation) in
  the Cell Culture project from the [{example_source_name} source]({example_source_url}).
  Three deviations from the source are recorded on the protocol description."

Do not just say "I created the protocol" without these links. Do not put
the URL in plain text — it must be a clickable markdown link.

### Handling rejection of the approval card

If the user rejects the approval card, the tool result will indicate
denial and the conversation continues. Briefly acknowledge in one
sentence ("Got it, skipped that protocol.") and invite them to pick a
different candidate from the previous `protocol_knowledgebase` search
or describe a different protocol. Do **not** propose the same candidate
again. There is no "rejection with reason" flow — corrections are
expressed by editing the approval card directly, not by rejecting.\
"""


_EXTERNAL_PROTOCOLS_ABSOLUTE_RULES = (
    "- NEVER answer a \"find / look up / do you have a protocol for X\"\n"
    "  question from general knowledge without first dispatching\n"
    "  `protocol_knowledgebase`. Not even once. Not even if the protocol\n"
    "  seems common.\n"
    "- If `protocol_knowledgebase` returns nothing, THEN and only then may\n"
    "  you fall back to general knowledge with the ⚠️ prefix."
)


def _source_names(openwetware: bool, protocols_io: bool) -> str:
    if openwetware and protocols_io:
        return "OpenWetWare and protocols.io"
    if openwetware:
        return "OpenWetWare"
    if protocols_io:
        return "protocols.io"
    return ""


def _new_protocol_source_names(openwetware: bool, protocols_io: bool) -> str:
    """Return the source-picker option labels for the new-protocol skill's
    mid-flow text. When sources are enabled they appear before 'From scratch'.
    """
    parts = []
    if openwetware:
        parts.append("OpenWetWare")
    if protocols_io:
        parts.append("protocols.io")
    if parts:
        return " / ".join(parts) + " / "
    return ""


def _source_link_labels(openwetware: bool, protocols_io: bool) -> str:
    """Return the per-source link label lines for the mandatory-final-reply block."""
    lines = []
    if openwetware:
        lines.append(
            "   - openwetware.org → `[OpenWetWare source](<source_url>)`"
        )
    if protocols_io:
        lines.append(
            "   - protocols.io → `[protocols.io source](<source_url>)`"
        )
    return "\n".join(lines)


def _example_source(openwetware: bool, protocols_io: bool) -> tuple[str, str]:
    """Return (name, url) for the example final reply."""
    if openwetware:
        return (
            "OpenWetWare",
            "https://openwetware.org/wiki/Sauer:Heat_shock_transformation_of_E._coli",
        )
    return (
        "protocols.io",
        "https://www.protocols.io/view/example-protocol",
    )


def render_chat_agent_prompt(
    external_master_enabled: bool,
    openwetware_enabled: bool,
    protocols_io_enabled: bool,
) -> str:
    """Substitute placeholders in chat_agent.md based on which external
    protocol sources are enabled. Sources gated off are not mentioned —
    we never advertise capability the backend will refuse.
    """
    live_oww = external_master_enabled and openwetware_enabled
    live_pio = external_master_enabled and protocols_io_enabled
    if not (live_oww or live_pio):
        return (
            _CHAT_PROMPT_TEMPLATE
            .replace("{{external_protocols_one_liner}}", "")
            .replace("{{external_protocols_dispatch_rule}}", "")
            .replace("{{external_protocols_absolute_rules}}", "")
            .replace("{{external_protocols_section}}", "")
            .replace("{{new_protocol_source_names}}", "")
        )
    names = _source_names(live_oww, live_pio)
    one_liner = _EXTERNAL_PROTOCOLS_ONE_LINER.format(source_names=names)
    dispatch_rule = _EXTERNAL_PROTOCOLS_DISPATCH_RULE.format(source_names=names)
    link_labels = _source_link_labels(live_oww, live_pio)
    ex_name, ex_url = _example_source(live_oww, live_pio)
    section = _EXTERNAL_PROTOCOLS_SECTION_TEMPLATE.format(
        source_names=names,
        source_link_labels=link_labels,
        example_source_name=ex_name,
        example_source_url=ex_url,
    )
    np_names = _new_protocol_source_names(live_oww, live_pio)
    return (
        _CHAT_PROMPT_TEMPLATE
        .replace("{{external_protocols_one_liner}}", one_liner)
        .replace("{{external_protocols_dispatch_rule}}", dispatch_rule)
        .replace("{{external_protocols_absolute_rules}}", _EXTERNAL_PROTOCOLS_ABSOLUTE_RULES)
        .replace("{{external_protocols_section}}", section)
        .replace("{{new_protocol_source_names}}", np_names)
    )


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
    ext = settings.features.external_protocols
    return (
        str(chat_model),
        str(subagent_model),
        str(creation_model),
        str(editing_model),
        str(summary_model),
        str(context_window),
        # Flag state: rebuild the cached Agent when any of these flip,
        # so the rendered prompt reflects current capability. Without
        # this, a flag toggle silently no-ops until process restart.
        str(ext.enabled),
        str(ext.openwetware.enabled),
        str(ext.protocols_io.enabled),
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
            app_help.build(subagent_model),
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
            instructions=render_chat_agent_prompt(
                external_master_enabled=settings.features.external_protocols.enabled,
                openwetware_enabled=settings.features.external_protocols.openwetware.enabled,
                protocols_io_enabled=settings.features.external_protocols.protocols_io.enabled,
            ),
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
