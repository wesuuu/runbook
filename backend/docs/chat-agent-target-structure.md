# Chat Agent — Target Structure

**Status:** Phase 2 of TD-0081. Design document; no code changes yet.
**Companion docs:**
- `chat-agent-inventory.md` — what's in `app/services/ai/` today (Phase 1)
- `chat-agent-harness-eval.md` — why we adopt à la carte capabilities (Phase 1.5)

This doc is the contract for the migration. After approval, Phase 3 implements it file-by-file.

---

## 1. Role of the chat agent

The chat agent is **the central orchestrator** for three specialist capabilities. It owns the conversation, the system prompt, the tool list (currently empty — see below), and the message history. It does **not** carry domain logic.

The three specialists, dispatched as subagents:
- **`research_library`** — answers factual questions from the org's document library, returns synthesized answers with `[1], [2]` citations.
- **`protocol_builder`** — multi-turn collaboration that ends in a draft `Protocol` artifact.
- **`run_planner`** — gathers requirements for an upcoming run (placeholder folder; full implementation deferred to a follow-up task).

The chat agent has **zero direct tools**. Every capability is a subagent. The chat agent's job is routing: "given the user's message, which specialist should handle this?" The specialist returns a synthesized result, and the chat agent presents it to the user.

This shape gives us:
- A short, focused system prompt (no per-capability branching like today's `WHEN THE USER WANTS TO CREATE A PROTOCOL → load_skill('generate-protocol')`)
- A clean context window (specialists return summaries, not raw RAG chunks)
- Mechanical extension: adding a new capability is a new folder under `subagents/`, plus one line in the registry

---

## 2. Capability classification

Four concepts; each plays a different role.

| Concept | What it is | When to use | Where it lives |
|---|---|---|---|
| **Tool** | Thin async function. One purpose, single DB/REST/service call, structured I/O. Stateless. | Atomic capabilities a subagent can stitch together. | `subagents/<name>/tools.py` for owner-specific tools; `tools/<domain>.py` for cross-subagent shared tools. |
| **Subagent** | Specialist with own system prompt, own tool list, own LLM call. Invoked from the chat agent via the `task(...)` tool that `SubAgentCapability` provides. | Multi-step reasoning, multiple tool calls, focused prompt. | `subagents/<name>/` folder. |
| **Workflow** | One-shot AI pipeline. Invoked by a REST endpoint or background job — **not** by the chat agent. Structured input → structured output. | When a flow is deterministic and not conversational (e.g., "extract a draft protocol from a finished chat"). | `workflows/<name>.py` |
| **Skill** | Markdown procedure overlaid onto the chat agent's prompt to bias behavior. No tools, no separate agent. | Pure prompting tweaks. **None at launch** — keep the door open via the directory structure but don't introduce until needed. | (no folder created until first skill exists) |

**Workflow vs. subagent in one sentence:** subagents are multi-turn and chat-invoked; workflows are one-shot and endpoint-invoked.

The original `generate-protocol` SKILL.md becomes the `protocol_builder` subagent. Skills as a runtime concept go away during the migration.

---

## 3. Directory layout

```
backend/app/services/ai/
├── __init__.py                         # public API: send_message, sessions CRUD
│
├── chat_agent.py                       # Agent factory — capabilities + subagent registry
├── send_message.py                     # orchestration: build → run → persist
├── sessions.py                         # ChatSession CRUD (no LLM)
├── deps.py                             # ChatDeps (satisfies SubAgentDepsProtocol)
│
├── prompts/                            # global prompts (not subagent-specific)
│   ├── chat_agent.md                   # main system prompt
│   └── summarization.md                # ContextManagerCapability prompt
│
├── subagents/
│   ├── __init__.py                     # re-exports research_library, protocol_builder, run_planner modules
│   │
│   ├── research_library/
│   │   ├── __init__.py                 # re-exports `build` from config
│   │   ├── config.py                   # build(model) -> SubAgentConfig (see §7.1)
│   │   ├── prompt.md                   # subagent's system prompt
│   │   └── tools.py                    # search_documents, read_section, list_documents
│   │
│   ├── protocol_builder/
│   │   ├── __init__.py
│   │   ├── config.py                   # build(model) -> SubAgentConfig
│   │   ├── prompt.md
│   │   └── tools.py                    # list_unit_ops, create_unit_op, create_protocol_from_spec
│   │
│   └── run_planner/                    # placeholder; stub build() + empty tools.py
│       ├── __init__.py
│       ├── config.py                   # build(model) -> SubAgentConfig (placeholder)
│       ├── prompt.md                   # marked "(placeholder)"
│       └── tools.py
│
├── tools/                              # tools used by 2+ subagents
│   ├── __init__.py
│   └── projects.py                     # list_projects, get_project_by_name (used by protocol_builder & run_planner)
│
├── runtime/                            # cross-cutting agent infrastructure
│   ├── __init__.py
│   ├── retrieval.py                    # retrieve_relevant_chunks + keyword fallback
│   ├── compaction.py                   # on_before_compress / on_after_compress callbacks
│   ├── sanitize.py                     # output cleanup regex
│   └── token_counting.py               # tiktoken-backed counter
│
├── workflows/                          # one-shot AI pipelines (REST/job invoked)
│   ├── __init__.py
│   └── protocol_generator.py           # dormant — see disposition header
│
└── (peer infrastructure — unchanged)
    ├── ai_config.py                    # provider resolution
    ├── ai_provider_validation.py       # provider credential validation
    ├── embedding.py                    # RAG embeddings
    └── ai_vision.py                    # vision agent (batch records, template converter)
```

Files not listed are removed during migration (e.g., the current monolithic `chat_service.py`).

---

## 4. The placement rule for tools

> A tool with **exactly one** subagent consumer lives in `subagents/<owner>/tools.py`. A tool used by **2+** subagents extracts to `tools/<domain>.py`.

The chat agent itself has zero direct tools, so it is never a consumer.

Today's mapping:

| Tool function | Owner |
|---|---|
| `search_documents`, `read_section`, `list_documents` | `subagents/research_library/tools.py` |
| `list_unit_ops`, `create_unit_op` | `subagents/protocol_builder/tools.py` |
| `create_protocol_from_spec` | `subagents/protocol_builder/tools.py` |
| `list_projects`, `get_project_by_name` | `tools/projects.py` (shared by `protocol_builder` and `run_planner`) |

When a tool starts owned-by-one and grows to needed-by-two, we extract — a one-file rename, no ambiguity.

---

## 5. The thin-tool rule

> Tool functions must call into a service or REST endpoint. **No business logic in the tool body.** Permission checks, validation, parsing, and persistence live in the underlying service.

Today's `create_protocol_tool` is ~100 lines: project name lookup, EDIT permission check, line-by-line steps text parser, unit op fetch, graph build, persist. After migration:

- `services/protocols/creation.py::create_protocol_from_spec(db, user_id, project_name, spec)` — owns all the logic
- `subagents/protocol_builder/tools.py::create_protocol_from_spec(ctx, project_name, spec)` — ~15 lines: unwrap deps, call the service, append to `tool_calls`, return result

Same rule applies to `read_section_tool` and `list_documents_tool` (currently raw SQL inline) — the SQL moves into a service or REST handler; the tool wraps it.

This rule is what makes future MCP exposure (F-0078) mechanical: an MCP tool is just another caller of the same service function.

---

## 6. `ChatDeps` shape

```python
# app/services/ai/deps.py
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID
from sqlalchemy.ext.asyncio import AsyncSession

@dataclass
class RetrievedChunk:
    document_id: UUID
    document_title: str
    chunk_id: UUID
    chunk_index: int
    page_number: int | None
    content: str
    score: float

@dataclass
class ChatDeps:
    """Per-request dependencies injected into pydantic-ai tools and subagents."""
    db: AsyncSession
    org_id: UUID
    user_id: UUID
    is_org_admin: bool
    sources: list[RetrievedChunk] = field(default_factory=list)
    tool_calls: list[dict] = field(default_factory=list)

    # Required by SubAgentDepsProtocol from subagents-pydantic-ai
    subagents: dict[str, Any] = field(default_factory=dict)

    def clone_for_subagent(self, max_depth: int = 0) -> "ChatDeps":
        """Create deps for a subagent run.

        - db / org_id / user_id / is_org_admin: shared (same request scope)
        - sources / tool_calls: shared so subagent citations and tool-call audit
          rows bubble up to the parent's audit/UI layer (mutated in place)
        - subagents: preserved when max_depth > 0 (nested dispatch allowed),
          wiped at max_depth == 0 (leaf subagent)

        `max_depth` is the framework-driven remaining nesting budget. When
        SubAgentCapability dispatches, it decrements this and calls clone again
        for the next level, so we don't manage the counter ourselves.
        """
        return ChatDeps(
            db=self.db,
            org_id=self.org_id,
            user_id=self.user_id,
            is_org_admin=self.is_org_admin,
            sources=self.sources,
            tool_calls=self.tool_calls,
            subagents={} if max_depth <= 0 else self.subagents,
        )
```

The `subagents` field and `clone_for_subagent` method are the two additions that satisfy `SubAgentDepsProtocol` from `subagents-pydantic-ai`. No inheritance. Verified live in the eval phase.

---

## 7. The chat agent factory

```python
# app/services/ai/chat_agent.py
from pathlib import Path
from uuid import UUID
from pydantic_ai import Agent
from sqlalchemy.ext.asyncio import AsyncSession
from subagents_pydantic_ai import SubAgentCapability
from pydantic_ai_summarization import ContextManagerCapability

from app.core.config import settings
from app.services.ai.ai_config import get_context_window, get_model
from app.services.ai.deps import ChatDeps
from app.services.ai.runtime.compaction import make_compaction_hooks, CompactionState
from app.services.ai.runtime.token_counting import tiktoken_counter
from app.services.ai.subagents import (
    research_library, protocol_builder, run_planner,
)

_PROMPTS_DIR = Path(__file__).parent / "prompts"
_CHAT_PROMPT = (_PROMPTS_DIR / "chat_agent.md").read_text()
_SUMMARY_PROMPT = (_PROMPTS_DIR / "summarization.md").read_text()


async def build_chat_agent(
    db: AsyncSession, org_id: UUID, compaction_state: CompactionState,
) -> Agent[ChatDeps, str]:
    """Build the chat agent for a given org's request scope.

    `compaction_state` is a per-request capture object that the orchestrator
    inspects after agent.run() returns, to write ChatMessage(role=SUMMARY).
    """
    chat_model       = await get_model("chat",           db, org_id=org_id)
    subagent_model   = await get_model("chat_subagent",  db, org_id=org_id)
    summary_model    = await get_model("chat_summary",   db, org_id=org_id)
    context_window   = await get_context_window("chat",  db, org_id=org_id)

    # Subagent configs are built per-request because their model resolves per-org.
    # See §7.1 for the builder pattern.
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
                max_nesting_depth=1,    # see §7.2 — allow one level of nesting
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
```

Notable:
- **No business logic.** Only configuration.
- **Per-org model resolution preserved** via `ai_config.get_model(...)`.
- **Three AI capability keys** (`chat`, `chat_subagent`, `chat_summary`) — see §7.1 for rationale and rollout.
- **Subagent configs built per-request** via `subagent_module.build(model)` — see §7.1.
- **`max_nesting_depth=1`** lets a subagent dispatch to a peer subagent — see §7.2.
- Returns a fresh agent **per request scope** for now. Globalizing the agent is TD-0063's goal — done in Phase 4 once we've verified the structure works. Premature globalization could mask state-leak bugs.

---

## 7.1. Per-subagent configuration (builder pattern + capability keys)

Every subagent module exports a **`build(model)` function** instead of a static config constant. The chat agent factory resolves models per-org and calls each builder at request time. This keeps `ai_config`'s multi-provider per-org chain intact for subagents.

```python
# subagents/research_library/config.py
from pathlib import Path
from typing import Any
from subagents_pydantic_ai import SubAgentConfig
from .tools import search_documents, read_section, list_documents

_PROMPT = (Path(__file__).parent / "prompt.md").read_text()

def build(model: Any) -> SubAgentConfig:
    return {
        "name": "research_library",
        "description": (
            "Use when the user asks a factual question that the organization's "
            "documents could answer. Returns a synthesized answer with [1], [2] "
            "citations referencing chunks. Do not use for general knowledge."
        ),
        "instructions": _PROMPT,
        "model": model,
        "agent_kwargs": {
            "tools": [search_documents, read_section, list_documents],
        },
        "typically_needs_context": True,
    }
```

```python
# subagents/__init__.py
from . import research_library, protocol_builder, run_planner

__all__ = ["research_library", "protocol_builder", "run_planner"]
```

### Capability keys (kept to three)

Earlier drafts of this doc proposed one capability key per subagent. That over-fits — every new subagent would mean a new `SUPPORTED_CAPABILITIES` row, a new `DEFAULT_CONFIGS` entry, new `Settings` env var fields, a new row in the frontend AI settings page. Three keys is the right starting bucket; we can split later if a specific subagent needs its own model.

| Capability key | Purpose | Suggested default |
|---|---|---|
| `chat` (existing) | The orchestrator. Just routes to subagents — fast model is fine. | A small/fast model (e.g., Haiku-tier) |
| `chat_subagent` (new) | Shared by `research_library`, `protocol_builder`, `run_planner`. Does the actual domain reasoning. | A stronger reasoning model (e.g., Sonnet-tier) |
| `chat_summary` (new) | Compaction summarizer used by `ContextManagerCapability`. Cheap terse extraction. | A small/fast model (e.g., Haiku-tier) |

When a specific subagent later proves it needs its own model, add a 4th key (e.g., `protocol_builder`). Or use the per-subagent escape hatch in §7.1.1 below — no new capability key needed for one-off tuning.

### 7.1.1. Escape hatch — per-subagent capability tuning

If a single subagent needs different runtime tuning (tighter context budget, output guardrails, etc.) without warranting its own capability key, attach capabilities via `agent_kwargs`:

```python
def build(model: Any) -> SubAgentConfig:
    return {
        "name": "protocol_builder",
        "instructions": _PROMPT,
        "model": model,
        "agent_kwargs": {
            "tools": [list_unit_ops, create_unit_op, create_protocol_from_spec],
            "capabilities": [
                ContextManagerCapability(max_tokens=50_000, max_tool_output_tokens=1000),
            ],
        },
    }
```

**Don't add per-subagent capabilities in this migration.** Land the structure first; tune when a real symptom appears.

### 7.1.2. System-level defaults stay intact

Existing tier behavior is unchanged. The provider resolution chain is still:
1. Org DB config (`AiProviderConfig` row)
2. Platform env vars (Pro+) — `BATCHRITE_AI_CHAT_SUBAGENT_PROVIDER`, etc.
3. Hardcoded `DEFAULT_CONFIGS` (Pro+)

Existing orgs without DB rows for `chat_subagent` / `chat_summary` fall through to platform/default, same as today's chain for `chat`. No data migration.

### 7.1.3. Frontend impact

Per `.claude/rules/backend-ai.md` and `api/endpoints/ai.py`, the AI settings page should iterate over the capabilities returned by the backend. **If it does, two new rows render automatically.** If capabilities are hardcoded in the frontend, two new rows need adding to the UI component. Phase 3 step 1 ends with a quick frontend verification — we'll know in 30 seconds which one it is.

---

## 7.2. Nested subagent dispatch

Subagents are peers, not parent-child. With `max_nesting_depth=1` set on `SubAgentCapability` and `ChatDeps.clone_for_subagent(max_depth)` preserving the registry when `max_depth > 0`, a subagent can dispatch to another subagent via the same `task(...)` tool the chat agent uses.

### Use case

`protocol_builder` is mid-flow and wants to look up similar protocols in the org library before suggesting a step. Two patterns:

| Pattern | Shape | When to use |
|---|---|---|
| **Direct tools** | `protocol_builder` registers `search_documents`, `read_section` in its own `tools.py` | Only when RAG is core to the subagent's identity |
| **Nested dispatch** | `protocol_builder` calls `task("research_library", "...")` mid-run | Default — composes existing subagents without duplication |

Default to **nested dispatch.** No code duplication; doc tools stay owned by `research_library`; `protocol_builder`'s prompt stays focused with one line: "if you need facts from the library, call `task('research_library', ...)`".

### Concrete trace

```
chat_agent.run("build a protocol for mAb seed train")
└─ task("protocol_builder", "build a protocol for mAb seed train")
   └─ protocol_builder.run(...)  [deps: max_depth=1, subagents={...} preserved]
      ├─ list_unit_ops()
      ├─ task("research_library", "what buffers does this org use for mAb seed train?")
      │  └─ research_library.run(...)  [deps: max_depth=0, subagents={} — leaf]
      │     ├─ search_documents("buffers mAb seed train")
      │     ├─ read_section(...)
      │     └─ returns synthesized cited answer
      ├─ create_protocol_from_spec(...)
      └─ returns "Created protocol with steps: ..."
```

The framework manages the depth countdown. We just set `max_nesting_depth=1` once on `SubAgentCapability` and preserve `subagents` in `clone_for_subagent` when `max_depth > 0`.

### What this preserves

- **Tool placement rule (§4) is unchanged.** Tools live with the subagent that owns them. Nesting is composition, not co-location.
- **Audit trail.** `deps.sources` and `deps.tool_calls` flow through all levels because the lists are shared (mutated in place). Citations from a deeply nested `research_library` still surface in the chat UI.
- **Subagent isolation.** Each subagent has its own prompt, its own tools, its own LLM call. Nesting doesn't couple them — `research_library` stays independently testable and reusable; `protocol_builder` just gets permission to call it.

### What this does NOT do

- **It does not put the nested call in the chat agent's history.** The parent's `ChatSession.ai_message_history` only records the outer `task("protocol_builder", ...)` and its return text. The inner `task("research_library", ...)` is hidden inside `protocol_builder`'s run — invisible to the parent. This is the right behavior for context-window hygiene; if we ever need deep visibility for debugging, we instrument via callbacks, not by inflating the parent's history.
- **It does not add new persistence.** Nested dispatch is purely runtime composition; no new state.

---

## 8. Send message orchestration

```python
# app/services/ai/send_message.py
from pydantic_ai.messages import ModelMessagesTypeAdapter

from app.models.chat import ChatMessage, ChatMessageRole
from app.services.ai.chat_agent import build_chat_agent
from app.services.ai.deps import ChatDeps
from app.services.ai.runtime.compaction import CompactionState
from app.services.ai.runtime.sanitize import sanitize_output


async def send_message(
    db: AsyncSession,
    session: ChatSession,
    user_content: str,
    user_id: UUID,
    is_org_admin: bool,
) -> tuple[ChatMessage, ChatMessage, list[RetrievedChunk]]:
    # 1. Persist user message
    user_msg = ChatMessage(
        session_id=session.id,
        role=ChatMessageRole.USER,
        content=user_content,
    )
    db.add(user_msg)
    await db.flush()
    if session.title == "New Chat":
        session.title = user_content[:100].strip()

    # 2. Build deps with a compaction-state observer
    compaction_state = CompactionState()
    deps = ChatDeps(
        db=db, org_id=session.org_id, user_id=user_id, is_org_admin=is_org_admin,
    )

    # 3. Run the agent
    agent = await build_chat_agent(db, session.org_id)
    message_history = (
        ModelMessagesTypeAdapter.validate_python(session.ai_message_history)
        if session.ai_message_history else None
    )
    result = await agent.run(
        user_content,
        deps=deps,
        message_history=message_history,
        # compaction callbacks write into compaction_state via closures
    )

    # 4. Persist any compaction summary captured during the run
    if compaction_state.summary_text:
        summary_msg = ChatMessage(
            session_id=session.id,
            role=ChatMessageRole.SUMMARY,
            content=compaction_state.summary_text,
            metadata_=compaction_state.audit_metadata(),
        )
        db.add(summary_msg)

    # 5. Persist assistant message + serialized history
    session.ai_message_history = ModelMessagesTypeAdapter.dump_python(
        result.all_messages(), mode="json",
    )
    metadata = build_message_metadata(deps.sources, deps.tool_calls, compaction_state)
    assistant_msg = ChatMessage(
        session_id=session.id,
        role=ChatMessageRole.ASSISTANT,
        content=sanitize_output(result.output),
        metadata_=metadata,
    )
    db.add(assistant_msg)
    await db.flush()
    return user_msg, assistant_msg, deps.sources
```

`CompactionState` is a small dataclass owned by `runtime/compaction.py`. The capability callbacks (`on_before_compress`, `on_after_compress`) are partial functions that close over a fresh `CompactionState` per request, so audit data flows back to the orchestrator without globals.

---

## 9. A subagent in detail — `research_library`

```python
# app/services/ai/subagents/research_library/config.py
from pathlib import Path
from typing import Any
from subagents_pydantic_ai import SubAgentConfig
from .tools import search_documents, read_section, list_documents

_PROMPT = (Path(__file__).parent / "prompt.md").read_text()


def build(model: Any) -> SubAgentConfig:
    """Build the research_library SubAgentConfig with a resolved model.

    Called by chat_agent.build_chat_agent at request time so the model
    resolves per-org via ai_config.
    """
    return {
        "name": "research_library",
        "description": (
            "Use when the user asks a factual question that the organization's "
            "documents could answer. Returns a synthesized answer with [1], [2] "
            "citations referencing chunks. Do not use for general knowledge."
        ),
        "instructions": _PROMPT,
        "model": model,
        "agent_kwargs": {
            "tools": [search_documents, read_section, list_documents],
        },
        "typically_needs_context": True,
    }
```

```python
# app/services/ai/subagents/research_library/__init__.py
from .config import build

__all__ = ["build"]
```

```python
# app/services/ai/subagents/research_library/tools.py
from pydantic_ai import RunContext
from app.services.ai.deps import ChatDeps
from app.services.ai.runtime.retrieval import retrieve_relevant_chunks


async def search_documents(
    ctx: RunContext[ChatDeps], query: str, max_results: int = 5,
) -> SearchDocumentsResult:
    """Search the organization's document library for relevant content."""
    chunks = await retrieve_relevant_chunks(
        ctx.deps.db, query=query, org_id=ctx.deps.org_id, top_k=max_results,
    )
    ctx.deps.sources.extend(chunks)
    ctx.deps.tool_calls.append({
        "tool": "search_documents",
        "subagent": "research_library",
        "query": query,
        "results": len(chunks),
    })
    return SearchDocumentsResult(...)


async def read_section(...): ...
async def list_documents(...): ...
```

Note the retry-with-shorter-query heuristic that's currently inside `search_documents_tool` moves into `runtime/retrieval.py` — that's a retrieval concern, not a tool concern. The tool body stays under ~15 lines.

```markdown
<!-- app/services/ai/subagents/research_library/prompt.md -->
You are a research specialist for an organization's document library.

Your job:
- Use `search_documents` to find relevant content. If a query returns nothing,
  try paraphrasing or shortening it once.
- Use `read_section` when you need more context around a promising chunk.
- Synthesize a concise answer with [1], [2] citation markers referencing the
  chunks you used.
- Never fabricate sources. If nothing matches, say so plainly:
  "I couldn't find anything about this in the library."
```

---

## 10. Compaction integration

```python
# app/services/ai/runtime/compaction.py
from dataclasses import dataclass, field
from typing import Any

from pydantic_ai.messages import ModelMessage, ModelRequest, SystemPromptPart


@dataclass
class CompactionState:
    """Per-request capture of compaction events; written to DB after agent.run()."""
    summary_text: str | None = None
    summarized_message_count: int = 0
    triggered: bool = False

    def audit_metadata(self) -> dict[str, Any]:
        return {
            "type": "summary",
            "summarized_message_count": self.summarized_message_count,
            # ... boundary message ids if available
        }


def make_compaction_hooks(state: CompactionState):
    """Return (on_before, on_after) closures for ContextManagerCapability."""

    def on_before(messages: list[ModelMessage], cutoff_index: int) -> None:
        state.triggered = True
        state.summarized_message_count = cutoff_index

    def on_after(messages: list[ModelMessage]) -> str | None:
        # Extract the summary text the capability injected as the new SystemPromptPart
        if messages:
            first = messages[0]
            if isinstance(first, ModelRequest):
                for part in first.parts:
                    if isinstance(part, SystemPromptPart):
                        state.summary_text = part.content
                        break
        return None  # don't modify the summary

    return on_before, on_after
```

`send_message.py` constructs `CompactionState`, calls `make_compaction_hooks(state)`, and passes the returned closures to `ContextManagerCapability`. After `agent.run()` completes, the orchestrator inspects `state` and writes the `ChatMessage(role=SUMMARY)` row. Audit visibility preserved; no async-from-sync gymnastics.

---

## 10.5. Conversation persistence with subagents

A subagent invocation is **stateless within a turn.** Each `task("<subagent>", ...)` call runs the subagent fresh: prompt → tool calls → final text → return. Subagents don't carry session-scoped memory of prior turns.

The chat agent is the conversation manager. The single source of truth is `ChatSession.ai_message_history` (the chat agent's serialized message history). Every user message, every `task(...)` call the chat agent makes, every text return from a subagent (as a tool return), and every text the chat agent writes to the user lives there. The subagent's *internal* turns (its system prompt, its calls to `list_unit_ops`, etc.) are NOT persisted — they're hidden behind the `task()` tool return.

### Why this works for multi-turn

The chat agent's prompt instructs it: when invoking a subagent that previously asked a question, restate all relevant prior context in the new `task()` prompt. The chat agent's LLM has access to its own prior history (including the subagent's earlier question as a tool return), so it knows what context to pass forward.

```
TURN 1 (user: "I want to build a protocol")
─────────────────────────────────────────────
chat_agent.run("I want to build a protocol", deps, message_history=loaded_session_history)
  ├─ chat agent's LLM calls: task("protocol_builder", "user wants to build a protocol")
  ├─ SubAgentCapability dispatches:
  │  protocol_builder.run(prompt, deps=parent_deps.clone_for_subagent(), message_history=None)
  │     ├─ subagent's LLM: I need more info. Asks: "What type of process?"
  │     └─ returns: "What type of process? (mAb, viral vector, fermentation)"
  ├─ tool return value comes back to the chat agent
  └─ chat agent's LLM emits: "What type of process? (mAb, viral vector, fermentation)"

After agent.run() returns, send_message.py serializes result.all_messages() and persists:
  ChatSession.ai_message_history = [
    UserPromptPart("I want to build a protocol"),
    ToolCallPart(name="task", args={"subagent": "protocol_builder", "prompt": "..."}),
    ToolReturnPart(name="task", content="What type of process? ..."),
    TextPart("What type of process? ..."),
  ]


TURN 2 (user: "monoclonal antibody")
────────────────────────────────────
ChatSession.ai_message_history (above) is loaded.

chat_agent.run("monoclonal antibody", deps, message_history=loaded)
  ├─ chat agent's LLM sees its full history including the prior task() exchange
  ├─ chat agent's LLM calls: task("protocol_builder",
  │       "user is building a protocol for monoclonal antibody production.
  │        prior context: process type = mAb production.
  │        now ask the next question.")
  ├─ SubAgentCapability dispatches a fresh protocol_builder run (no prior subagent state)
  │     └─ returns: "What scale? (bench, pilot, GMP)"
  └─ chat agent emits: "What scale? (bench, pilot, GMP)"
```

### Why this is the right default

- **One source of truth.** Conversation state lives only in `ChatSession.ai_message_history`. No parallel "subagent sessions" to keep in sync, no orphaned memory if a session is deleted, no confusion about which messages belong where.
- **Compaction is simple.** `ContextManagerCapability` operates on the chat agent's history. Subagent runs are bounded (a few tool calls then return), so subagent context never grows unbounded.
- **Audit trail is clean.** Every `task()` call and every subagent return is in the parent's history; the metadata UI already surfaces tool calls.
- **Reproducible.** The full transcript of what the user saw is in one place; what each subagent did is reproducible from its prompt at dispatch time.

### When this falls down (and what to do then)

This pattern handles "subagent asks clarifying questions" cleanly. Where it stops working:

| Symptom | Fix | Where it lands |
|---|---|---|
| Chat agent doesn't summarize prior context well enough; subagent loses track | Tighten the chat agent's prompt rules ("always include protocol-name, scale, and steps so far when calling protocol_builder") | `prompts/chat_agent.md` |
| Subagent has internal state too large to reconstruct from prompt every turn | Stateful subagent — store the subagent's `result.all_messages()` per-session in `ChatSession` JSONB under a per-subagent key, feed back as `message_history=` on next dispatch | Deferred (§16) |
| Tool calls inside a subagent need to bubble up to the UI in real time | Streaming | Deferred to F-0078 |

**Don't add stateful subagents in this migration.** Start with stateless because it's the simplest correct thing and our existing chat sessions are already shaped for it. Add per-subagent history only when a real symptom appears.

---

## 11. Migration mapping (file by file)

For each item in today's `app/services/ai/`, where it ends up after the migration.

### Inside `chat_service.py` (1263 lines, deleted at end of migration)

| Today (chat_service.py) | New home |
|---|---|
| `SYSTEM_PROMPT` (lines 25-43) | `prompts/chat_agent.md` (rewritten — drop hardcoded skill branching) |
| `SUMMARIZATION_PROMPT` (lines 45-48) | `prompts/summarization.md` |
| `RAG_TOP_K`, `RAG_MAX_CONTEXT_CHARS`, `RAG_MIN_SCORE`, `LLM_MAX_TOKENS` | `runtime/retrieval.py` (RAG constants) and `chat_agent.py` (LLM_MAX_TOKENS into `model_settings`) |
| `RetrievedChunk` dataclass | `deps.py` (alongside ChatDeps) |
| `ChatDeps` dataclass | `deps.py` (with new fields) |
| All 10 tool result Pydantic models | Co-located with the tool that returns them in `subagents/<owner>/tools.py` |
| `search_documents_tool` | `subagents/research_library/tools.py::search_documents` (retry logic → `runtime/retrieval.py`) |
| `read_document_section_tool` | `subagents/research_library/tools.py::read_section` (raw SQL → service or thin REST wrapper) |
| `list_documents_tool` | `subagents/research_library/tools.py::list_documents` (raw SQL → service or thin REST wrapper) |
| `list_unit_ops_tool` | `subagents/protocol_builder/tools.py::list_unit_ops` |
| `create_unit_op_tool` | `subagents/protocol_builder/tools.py::create_unit_op` (logic → `services/science/unit_ops.py`) |
| `create_protocol_tool` | `subagents/protocol_builder/tools.py::create_protocol_from_spec` (logic → `services/protocols/creation.py`) |
| `create_session`, `get_session`, `list_sessions`, `delete_session` | `sessions.py` |
| `send_message` | `send_message.py` |
| `retrieve_relevant_chunks`, `_keyword_search_chunks` | `runtime/retrieval.py` |
| `_get_skills_toolset` (lazy SkillsToolset) | **deleted** — subagents replace skills |
| `_sanitize_output` + regex constants | `runtime/sanitize.py` |
| `estimate_tokens`, `estimate_messages_tokens` | **deleted** — replaced by `ContextManagerCapability`'s pluggable token counter |
| `compact_history`, `_get_last_summary`, `_build_conversation_text`, `_generate_summary`, `_truncate_to_fit` | **deleted** — replaced by `ContextManagerCapability` + audit callbacks in `runtime/compaction.py` |
| `_call_llm` | **deleted** — orchestration is in `send_message.py`, agent construction in `chat_agent.py` |

### Other files in `app/services/ai/`

| Today | New home |
|---|---|
| `ai_config.py` | unchanged (peer infrastructure) |
| `ai_provider_validation.py` | unchanged |
| `embedding.py` | unchanged |
| `ai_vision.py` | unchanged |
| `sop_generator.py` | `workflows/sop_generator.py` |
| `protocol_generator.py` (whole file) | `workflows/protocol_generator.py` (with disposition header — see §12) |

### Outside `app/services/ai/`

| Today | New home |
|---|---|
| `services/documents/pdf.py::generate_sop_pdf` re-export | Update import path to `app.services.ai.workflows.sop_generator` |
| `api/endpoints/chat.py` | Update imports: `from app.services.ai import chat_service` → `from app.services.ai import sessions, send_message` (or import the public re-exports from `app/services/ai/__init__.py`) |
| `services/protocols/protocol_importer.py` (uses `ai_vision`) | Unchanged |
| `services/batch/batch_record_extractor.py` | Unchanged |

### Additions

- `services/protocols/creation.py` — new service: `create_protocol_from_spec(db, user_id, project_name, spec)`. Owns project lookup, permission check, steps parsing, graph build, persist.
- `services/science/unit_ops.py` — new service: `create_unit_op(db, user_id, org_id, scope, project_id, name, ...)`. Owns scope validation, permission check, duplicate detection, persist.
- New AI capability `chat_summary` — added to `SUPPORTED_CAPABILITIES` in `models/ai.py` so we can resolve a (cheaper) summarization model per org.
- New dependencies in `pyproject.toml`:
  - `subagents-pydantic-ai = "^0.2.2"`
  - `summarization-pydantic-ai = "^0.1.4"` (imports as `pydantic_ai_summarization`)
  - `tiktoken` (for the accurate token counter)

### Deletions

- `services/ai/chat_service.py` (whole file, after the new structure absorbs it)
- `pydantic_ai_skills` dependency from `pyproject.toml`
- The `generate-protocol` SKILL.md file in `backend/skills/` (after `protocol_builder` subagent replaces it)
- `protocol_generator.generate_protocol_from_chat` and `_call_generation_llm` — see §12

---

## 12. Disposition: the dormant `generate_protocol_from_chat` workflow

`workflows/protocol_generator.py` will carry a header at the top:

```python
"""One-shot protocol generation from a chat conversation.

DORMANT SINCE TD-0081 (Apr 2026).

This workflow is not currently invoked by any endpoint or background job.
It is preserved because:
  - The code is written and tested.
  - It represents a legitimate alternate UX path ("explore in chat, then
    formalize") that we may productize later.
  - Deleting and rebuilding later is more work than keeping it dormant.

Status: kept until we confirm the conversational `protocol_builder` subagent
performs well in production. Once validated, this file may be deleted along
with its unit test (`tests/unit/test_protocol_generator.py`).

DO NOT add new callers without first promoting this to a real product
feature with its own task and acceptance criteria.

The graph-building helpers (`build_graph`, `match_unit_op`, `extract_params`)
in this module ARE used by `subagents/protocol_builder/tools.py::create_protocol_from_spec`
and must not be removed without replacing them.
"""
```

The unit test (`tests/unit/test_protocol_generator.py`) keeps running so the code stays correct as `Protocol` schema evolves.

---

## 13. Endpoint contract — unchanged

`api/endpoints/chat.py` continues to expose the same routes:

```
GET    /chat/skills                    — reads filesystem (no chat_service involvement)
GET    /chat/config                    — reads ai_config (unchanged)
POST   /chat/sessions                  — sessions.create_session
GET    /chat/sessions                  — sessions.list_sessions
GET    /chat/sessions/{id}             — sessions.get_session
PATCH  /chat/sessions/{id}             — direct ChatSession update
DELETE /chat/sessions/{id}             — sessions.delete_session
POST   /chat/sessions/{id}/messages    — send_message.send_message
POST   /chat/notify-admin              — unchanged
```

Frontend changes: **none expected.** The `skill_id` parameter on `POST /messages` becomes a no-op (or is removed) once the dual skill-injection path is gone — one frontend wiring update if/when we remove the field. Document IDs and citations continue to flow through the `sources` field of `ChatCompletionResponse`.

---

## 14. Acceptance criteria (refresh from TD-0081)

- [x] Inventory document committed
- [x] Harness evaluation document committed with recommendation
- [x] Target structure design document committed *(this doc)*
- [ ] New dependencies added (`subagents-pydantic-ai`, `pydantic-ai-summarization`, `tiktoken`)
- [ ] `pydantic_ai_skills` dependency removed
- [ ] `app/services/ai/` follows the structure in §3
- [ ] Tools are thin wrappers (≤30 lines each, no permission/persist logic in tool bodies)
- [ ] Chat agent has zero direct tools; all capabilities are subagents
- [ ] Audit-visible compaction preserved (`ChatMessage(role=SUMMARY)` rows still written)
- [ ] All existing chat tests pass after the migration
- [ ] TD-0063 absorbed (chat agent built once per request, summarization subagent reused)
- [ ] 5-query regression check run before/after with quality changes documented
- [ ] `protocol_generator.py` carries the disposition header
- [ ] `generate-protocol` skill file deleted from `backend/skills/`

---

## 15. Migration sequencing (Phase 3 plan)

File-by-file. Behavior preserved at each step. Existing chat tests pass after every step.

| Step | Change | Risk |
|---|---|---|
| 1 | Add `subagents-pydantic-ai`, `pydantic-ai-summarization`, `tiktoken` to `pyproject.toml`. Run install. | Low — no code changes. |
| 2 | Create the empty new structure (`subagents/`, `tools/`, `runtime/`, `prompts/`, `workflows/`, `deps.py`, `chat_agent.py`, `send_message.py`, `sessions.py`). Existing `chat_service.py` keeps running unchanged. Add stubs and `__init__.py` files. | Low — additive. |
| 3 | Move pure utilities first (no agent involvement): `_sanitize_output` → `runtime/sanitize.py`; `retrieve_relevant_chunks` + `_keyword_search_chunks` → `runtime/retrieval.py`; `RetrievedChunk` + `ChatDeps` → `deps.py`. Update `chat_service.py` to import from the new homes. | Low — pure code motion; tests cover. |
| 4 | Create `services/protocols/creation.py` and `services/science/unit_ops.py` (thin extractions of logic currently in tool bodies). Test directly. | Low — new code with own tests. |
| 5 | Build `subagents/research_library/`. Run integration test that the chat agent (still using old `_call_llm` path) sees a flag-gated `task("research_library", ...)` tool. Verify deps flow. | Medium — first real subagent. |
| 6 | Build `subagents/protocol_builder/`. Test similarly. | Medium. |
| 7 | Stub `subagents/run_planner/` (placeholder config + empty tools). | Low. |
| 8 | Build `chat_agent.py` and `send_message.py`. Wire `api/endpoints/chat.py` to call `send_message.send_message`. Existing `chat_service.py` deleted. | High — single-step cutover; test coverage critical. |
| 9 | Move `sop_generator.py` and `protocol_generator.py` to `workflows/`. Update import paths in callers. Add disposition header to `protocol_generator.py`. | Low — pure code motion. |
| 10 | Delete `generate-protocol` SKILL.md and `pydantic_ai_skills` dependency. | Low. |
| 11 | Run 5-query regression suite. Document quality changes. Globalize chat agent if state-leak concerns absent → absorbs TD-0063. | Medium — globalization could expose request-scope assumptions. |

Each step ends with `pytest` green. Rollback at any step is `git revert`.

---

## 16. Out of scope (deferred to follow-up tasks)

- **Stateful subagents** — per-session subagent message histories stored under per-subagent JSONB keys. Add when (and only when) a real symptom shows that the chat agent can't reconstruct enough context via prompt restatement. See §10.5.
- **Deeper nesting** (`max_nesting_depth > 1`) — current ceiling is one level. Bump only if a multi-level dispatch pattern proves valuable; not preemptively.
- **Per-subagent capability keys in `ai_config`** — `chat_subagent` is shared by all three specialists today. Splitting to per-subagent keys (e.g., `protocol_builder` as its own capability) is a config-only change; do it when a specific subagent demonstrably needs its own model.
- **Per-subagent capability tuning** via `agent_kwargs.capabilities` — the escape hatch from §7.1.1 is available, but don't add per-subagent capability lists in this migration.
- Persistent memory (MEMORY.md-style cross-session memory)
- Checkpoints / fork conversations
- Agent teams / shared TODO lists
- Web search / fetch / browser automation
- Code execution sandbox
- Planner subagent (Claude-Code-style plan mode)
- MCP loopback exposure of subagents (F-0078 — depends on this task)
- Productizing `generate_protocol_from_chat` as a UI button
- Promoting from vstorm packages to first-party `pydantic-ai-harness` once those PRs (#178, #191) merge

---

*End of target structure. After approval, Phase 3 implementation follows §15.*
