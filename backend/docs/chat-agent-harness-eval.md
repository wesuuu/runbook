# Chat Agent Harness Evaluation

**Status:** Phase 1.5 of TD-0081. Read-only research.
**Companion docs:** `chat-agent-inventory.md` (Phase 1).
**Goal:** decide whether to adopt an existing harness for the chat agent reorg, and if so, which one.

---

## TL;DR — Recommendation (revised after live venv probe)

**Adopt à la carte: install `subagents-pydantic-ai` and `pydantic-ai-summarization` directly. Skip `pydantic-deep`.**

1. **`SubAgentCapability`** (`subagents-pydantic-ai`) — for the research / protocol_builder / run_planner pattern.
2. **`ContextManagerCapability`** (`pydantic-ai-summarization`, NOT `summarization-pydantic-ai` — different import name; it's the same package) — replaces our home-grown compaction. Use its `on_before_compress` / `on_after_compress` callbacks (verified signatures: `(messages, cutoff_index) -> None` and `(messages) -> str | None`) to keep writing our audit-visible `ChatMessage(role=SUMMARY)` records.
3. **Skip `pydantic-deep`.** Probed live (Apr 2026): it forces `DeepAgentDeps` (8 opinionated fields including `backend`, `files`, `todos`, `uploads`, `ask_user`), defaults to filesystem-based history archive at `.pydantic-deep/messages.json` (wrong for a server-side multi-tenant library), and has ~10 capability flags defaulting to ON (TODO, filesystem, memory, plan, web search, web fetch, etc.). Its 4418-char `BASE_PROMPT` references its own framework. We'd be fighting it.
4. **Skip the LangChain/OpenAI/Anthropic frameworks** (LangGraph, deepagents, Claude Agent SDK, OpenAI Agents SDK, CrewAI, AutoGen). All disqualified because they force migration off pydantic-ai (rewrite of `ai_config` provider chain, all schemas, all tools, `ai_vision`, `protocol_generator`, embedding service).
5. **Defer** memory, checkpoints, planner subagent, teams, web tools, code execution. None fit current requirements.

Why à la carte beats the bundle: capabilities layer onto `Agent(model, tools=[...], deps_type=ChatDeps, capabilities=[...])` with **zero changes** to our deps shape. Verified by building such an agent in a throwaway venv — `isinstance(ChatDeps(...), SubAgentDepsProtocol)` returns `True` after adding two lines (`subagents: dict` field + `clone_for_subagent` method). No `DeepAgentDeps` inheritance, no filesystem state, no opinionated `BASE_PROMPT`.

---

## 1. Decision criteria

Derived from the inventory document. Anything that breaks one of the must-haves is disqualified.

| # | Criterion | Why it matters |
|---|---|---|
| 1 | **pydantic-ai compatibility** | We have `Agent(model, tools=[...], deps_type=ChatDeps)` everywhere. Migrating off pydantic-ai means rewriting `ai_config` provider chain (14 providers), all output schemas, all tool functions, `ai_vision`, `protocol_generator`, the embedding service. Massive scope explosion. **Must-have.** |
| 2 | **Multi-provider via `ai_config`** | Per-org provider resolution from DB (Anthropic, OpenAI, Ollama, Groq, Mistral, OpenRouter, etc.). A harness that locks us to one provider breaks our product. **Must-have.** |
| 3 | **Async / asyncpg / SQLAlchemy compatible** | Codebase is fully async; `ChatDeps.db` is `AsyncSession`. **Must-have.** |
| 4 | **Per-request dependency injection** | Tools and subagents need `db`, `org_id`, `user_id`, `is_org_admin`, mutable `sources` list. Globals don't work — each request has a fresh DB session. **Must-have.** |
| 5 | **Subagent dispatch pattern** | The single feature we'd otherwise reinvent. Want: parent agent → tool call → specialist agent with own prompt and tools, returns synthesized output, shares deps and usage. **Must-have.** |
| 6 | **Audit-visible context management** | Our compaction writes `ChatMessage(role=SUMMARY)` records that surface in the chat UI and audit log. A harness that summarizes opaquely loses that. **Strong preference**, not a hard block. |
| 7 | **Production maturity** | P1 quality fix; can't ship a flaky framework. Want active maintenance, real adopters, license that allows commercial use. |
| 8 | **Lightweight dependency tree** | We don't want Docker, Playwright, LangChain core, web search, browser automation, file-execution sandboxes. None map to our domain (Postgres + biotech). |
| 9 | **Layered, not all-or-nothing** | The reorg is incremental. Want capabilities we can adopt one at a time, not a new framework that owns the agent loop. |

---

## 2. Candidate survey

Evaluated against the criteria above.

### 2.1 Pydantic-AI Capabilities API (first-party)

`pydantic-ai` itself ships a first-class **Capabilities** mechanism (released 2026). The `pydantic-ai-harness` umbrella repo is the official capability library, maintained by the Pydantic team.

```python
agent = Agent(
    'anthropic:claude-sonnet-4-6',
    instructions='...',
    capabilities=[Thinking(effort='high'), WebSearch()],
    tools=[...],          # existing tools work unchanged
    deps_type=ChatDeps,   # existing DI works unchanged
)
```

Capabilities subclass `AbstractCapability` and hook into the agent lifecycle (`before_run`, `after_model_request`, `wrap_tool_execute`, etc.) and/or contribute toolsets. They have access to `RunContext` so they can read `ctx.deps`.

| Criterion | Fit |
|---|---|
| pydantic-ai compatibility | ✅ Native — *is* pydantic-ai |
| Multi-provider | ✅ Inherits pydantic-ai's provider model |
| Async / SQLAlchemy | ✅ Same as our existing code |
| Per-request DI | ✅ `RunContext[Deps]` flows through capabilities |
| Subagent dispatch | ✅ via `SubAgentCapability` (see §2.2) |
| Audit-visible compaction | 🟡 We can keep our own; or use a custom Capability subclass that writes our `ChatMessage(role=SUMMARY)` |
| Maturity | 🟡 First-party but pre-1.0 — minor releases may break APIs |
| Dep tree | ✅ Minimal — just adds `pydantic-ai-harness` |
| Layered adoption | ✅ One capability at a time |

**Recommendation:** the foundation. Use this. The remaining question is *which* capabilities.

### 2.2 `subagents-pydantic-ai` (third-party, vstorm)

Sub-package implementing `SubAgentCapability`. Not yet promoted to the first-party harness (the `pydantic-ai-harness` README lists subagents as "in progress" — so vstorm's package is the working implementation today).

Provides:
- A `task(name, prompt, ...)` tool surface for the parent agent
- `SubAgentConfig` for declarative subagent definitions (name, description, instructions, tools)
- Sync / async / auto execution modes (parallel subagents possible)
- Nested subagents (subagent-of-subagent)
- `clone_for_subagent` protocol on Deps for safe DI propagation
- Task cancellation (soft/hard)

```python
from subagents_pydantic_ai import SubAgentCapability, SubAgentConfig

agent = Agent(
    model,
    tools=[...],
    capabilities=[
        SubAgentCapability(subagents=[
            SubAgentConfig(
                name="researcher",
                description="Searches the org library and returns cited findings.",
                instructions="...",
                tools=[search_documents, read_section, list_documents],
            ),
            SubAgentConfig(
                name="protocol_builder",
                description="Multi-turn protocol creation from a discussion.",
                instructions="...",
                tools=[list_unit_ops, list_projects, create_protocol_from_spec],
            ),
        ]),
    ],
    deps_type=ChatDeps,
)
```

| Criterion | Fit |
|---|---|
| pydantic-ai compatibility | ✅ Native capability |
| Multi-provider | ✅ Each subagent gets a model — we resolve via `ai_config.get_model("chat", ...)` |
| Async / SQLAlchemy | ✅ |
| Per-request DI | ✅ `clone_for_subagent` is the contract — we implement it on `ChatDeps` |
| Subagent dispatch | ✅ This is the whole point |
| Audit-visible | 🟡 Subagent runs are observable via lifecycle hooks; we can log them |
| Maturity | 🟡 Pre-1.0, MIT, vstorm-maintained, active 2026 releases |
| Dep tree | ✅ Just pydantic-ai + this package |
| Layered adoption | ✅ Add when ready, drop a tool when the subagent absorbs it |

**Recommendation:** adopt. This is the single feature that justifies "harness" framing.

### 2.3 `pydantic-ai-summarization` (PyPI: `summarization-pydantic-ai`, vstorm)

> **Note on naming:** PyPI package is `summarization-pydantic-ai`; the import is `pydantic_ai_summarization`. Verified live.

Provides `ContextManagerCapability` (plus `SummarizationCapability`, `SlidingWindowCapability`, `LimitWarnerCapability`).

**Verified `ContextManagerCapability.__init__` parameters (from the installed package):**
- `max_tokens: int | None = None` — auto-resolves via `genai-prices`, falls back to 200k
- `compress_threshold: float = 0.9`
- `keep: ContextSize = ('messages', 0)` — by default only the summary survives (Claude-Code-style, matches our current behavior)
- `summarization_model: ModelType = 'openai:gpt-4.1-mini'` — overridable; we'd resolve via `ai_config.get_model("chat", db, org_id)`
- `token_counter` — pluggable (default heuristic; `tiktoken` extra for accurate counts)
- `summary_prompt: str` — fully customizable; default is a structured XML-style prompt
- `max_tool_output_tokens: int | None = None` — **in-flight tool output truncation**, with head/tail line preservation (`tool_output_head_lines=5`, `tool_output_tail_lines=5`)
- **`on_before_compress: (messages, cutoff_index) -> None`** — fires before compression, sees full message list and the cutoff
- **`on_after_compress: (messages) -> str | None`** — fires after compression with the post-compaction message list; if it returns a string, that gets prepended to the summary
- `on_usage_update` — token-count tracking
- `include_compact_tool: bool = False` — adds an agent-callable `compact_conversation` tool

| Criterion | Fit |
|---|---|
| pydantic-ai compatibility | ✅ Native capability |
| Multi-provider | ✅ Auto-detects context window via `genai-prices` |
| Async / SQLAlchemy | ✅ |
| Per-request DI | ✅ |
| Audit-visible | ✅ **Confirmed** via `on_before_compress` (capture cutoff + older-message ids) + `on_after_compress` (extract summary text from `messages[0]`) |
| Tool call/return integrity | ✅ "Safe Cutoff" preserves tool call/response pairs |
| Tool output truncation | ✅ Real win — our current code lets full 12k-char RAG chunks sit in history between compactions |
| Maturity | 🟡 Pre-1.0 (v0.1.4 verified installed), MIT |
| Dep tree | ✅ Adds only `genai-prices` |

**Implementation note for the audit-row writing.** Callbacks are sync. We capture state in the callback (summary text + boundary message IDs) and write the `ChatMessage(role=SUMMARY)` row in the calling code after `agent.run()` returns. This is cleaner than scheduling tasks from inside a sync hook.

**Recommendation:** **adopt.** The earlier "skip" verdict is reversed — verified callbacks resolve the audit-visibility concern. We get correctness fixes (tool pair integrity), a real new feature (in-flight tool output truncation), and lose the homebrew compaction code (~250 lines).

### 2.4 `pydantic-deep` / `pydantic-deepagents` (third-party, vstorm)

A **bundle** on top of the pydantic-ai capabilities ecosystem. Officially mentioned in the pydantic-ai docs' multi-agent guide as the community package that "brings these concepts together in a more opinionated way."

**Verified live (Apr 2026, v0.3.17, throwaway venv).** The default `pip install pydantic-deep` (no extras) installs ~33 deps. The heavy stuff (Docker, Playwright, document parsers, FastAPI, CLI) is correctly off by default — only opt-in via extras like `[sandbox]`, `[browser]`, `[liteparse]`. So the dependency-weight argument was overblown.

**However, probing `create_deep_agent` and `DeepAgentDeps` revealed three real blockers for our use case:**

**Blocker 1 — `DeepAgentDeps` is opinionated and prescriptive.** The deps dataclass it requires has these fields:
```python
@dataclass
class DeepAgentDeps:
    backend: BackendProtocol             # filesystem / state backend
    files: dict[str, FileData]            # in-agent virtual filesystem
    todos: list[Todo]                     # TODO list
    subagents: dict[str, Any]             # subagent registry
    uploads: dict[str, UploadedFile]
    ask_user: Any                         # human-in-the-loop callback
    context_middleware: Any
    share_todos: bool
```
Our `ChatDeps` carries `db: AsyncSession`, `org_id`, `user_id`, `is_org_admin`, `sources`, `tool_calls`. To use `pydantic-deep`, we'd either subclass `DeepAgentDeps` (inheriting all eight fields we don't want, including the filesystem state) or substitute a different deps shape (which the framework wasn't designed for). Neither is clean.

**Blocker 2 — Filesystem state on by default.** `create_deep_agent(...)` defaults to `include_filesystem=True`, `include_history_archive=True`, `history_messages_path='.pydantic-deep/messages.json'`, and a default `StateBackend` that writes state to disk. For a server-side library serving multiple orgs and users concurrently across async requests, shared filesystem state is wrong: race conditions, lost-on-restart, doesn't fit our DB-as-source-of-truth model. We'd need to plug in a custom no-op or in-memory `BackendProtocol` and disable ~10 flags that all default to `True`.

**Blocker 3 — Opinionated `BASE_PROMPT`.** A 4418-character system prompt that introduces the agent as "a Deep Agent — an autonomous AI assistant built on pydantic-deep (powered by Pydantic AI)" and references the framework's own tools and behaviors. Our chat agent has its own persona ("Batchrite AI, a concise assistant for biotech Process Development scientists"). We can override via `instructions=...`, but the framework's tools and subagents may reference the base behavior in their own descriptions — replacing it risks incoherence we'd discover one tool at a time.

**Defaults we'd need to flip OFF** if we used the bundle: `include_todo`, `include_filesystem`, `include_skills`, `include_builtin_subagents`, `include_plan`, `include_memory`, `include_history_archive`, `web_search`, `web_fetch`, `cost_tracking`, `thinking='high'`. That's 10+ flags just to get back to a normal chat agent.

| Criterion | Fit |
|---|---|
| pydantic-ai compatibility | ✅ Native |
| Multi-provider | ✅ |
| Per-request DI | ❌ **`DeepAgentDeps` is required**; can't substitute our `ChatDeps` cleanly |
| Subagent dispatch | ✅ (uses `subagents-pydantic-ai` under the hood) |
| Audit-visible | 🟡 Achievable but fights default filesystem state |
| Default install weight | ✅ Reasonable (extras are opt-in) |
| Default config sanity | ❌ ~10 flags need flipping; filesystem + history archive on by default; opinionated `BASE_PROMPT` |
| Layered adoption | ❌ All-or-nothing constructor |

**Recommendation:** skip. The à la carte capabilities (§2.1, §2.2, §2.3) give us 100% of the value we want with our existing `ChatDeps` shape and our existing system prompt. **The bundle's value-add is the `create_deep_agent` constructor that wires capabilities together — we don't need it because the wiring (~5 lines) is already trivial.** Verified live: `Agent(model, instructions=SYSTEM_PROMPT, capabilities=[SubAgentCapability(...), ContextManagerCapability(...)], deps_type=ChatDeps, tools=[...])` constructs cleanly with our existing `ChatDeps` after adding two lines (`subagents: dict` field + `clone_for_subagent` method).

### 2.5 LangChain `deepagents` (third-party)

22k stars, MIT, built on **LangChain + LangGraph**. Planning, virtual filesystem, subagent dispatch with isolated context, async remote subagents.

| Criterion | Fit |
|---|---|
| pydantic-ai compatibility | ❌ LangChain stack — not pydantic-ai |
| Migration cost | ❌ Rewrite `ai_config` provider chain, all schemas, all tools |
| Multi-provider | ✅ LangChain abstraction |
| Async / SQLAlchemy | ✅ |
| Maturity | ✅ Most production-tested option, backed by LangChain |
| Dep tree | ❌ LangChain core + LangGraph + dependencies |

**Recommendation:** **disqualified** by criterion 1. Adopting it means leaving pydantic-ai.

### 2.6 Claude Agent SDK (Anthropic)

Built on top of the Claude Code CLI subprocess. Subagents, MCP, hooks, sessions, skills.

| Criterion | Fit |
|---|---|
| pydantic-ai compatibility | ❌ Own SDK |
| Multi-provider | ❌ **Anthropic-only** (plus Bedrock / Vertex / Foundry as deployment routes) |
| Async / SQLAlchemy | ✅ Async, but tools are filesystem/bash-oriented |
| Per-request DI | ❌ Tools are CLI-style; no native `Deps` injection equivalent |
| Subagent dispatch | ✅ |
| Audit-visible | 🟡 Hooks API |
| Dep tree | ❌ Bundles Claude Code CLI as dependency |
| Domain fit | ❌ Filesystem/bash/web — wrong primitives for a Postgres-backed biotech app |

**Recommendation:** **disqualified** by criteria 1 and 2. We can't lock chat to Anthropic.

### 2.7 OpenAI Agents SDK

Released March 2025, replaces Swarm. Multi-provider via OpenAI-compatible endpoints.

| Criterion | Fit |
|---|---|
| pydantic-ai compatibility | ❌ Own SDK |
| Multi-provider | 🟡 Works with any OpenAI-compatible endpoint, but tightest with OpenAI |
| Migration cost | ❌ Significant — leaves pydantic-ai |

**Recommendation:** disqualified by criterion 1.

### 2.8 LangGraph (LangChain)

Most mature multi-agent framework, graph-based workflow.

**Recommendation:** disqualified by criterion 1 (LangChain stack). Also: graph DSL is overkill for our 3-subagent topology.

### 2.9 CrewAI

Role-based, fast prototyping. Own framework.

**Recommendation:** disqualified by criterion 1.

### 2.10 AutoGen / Microsoft Agent Framework

AutoGen → maintenance mode (replaced by Microsoft Agent Framework). MAF is enterprise-stack heavy (Semantic Kernel inheritance).

**Recommendation:** disqualified by criterion 1 and dep weight.

### 2.11 smolagents (HuggingFace)

Code-execution focused. Wrong primitives for our domain.

**Recommendation:** disqualified.

---

## 3. Scoring matrix

| | pyd-ai Capabilities | subagents-pyd-ai | summarization-pyd-ai | pyd-deep bundle | LC deepagents | Claude Agent SDK | OpenAI Agents | LangGraph | CrewAI | AutoGen / MAF |
|---|:-:|:-:|:-:|:-:|:-:|:-:|:-:|:-:|:-:|:-:|
| pydantic-ai compat | ✅ | ✅ | ✅ | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ |
| Multi-provider | ✅ | ✅ | ✅ | ✅ | ✅ | ❌ | 🟡 | ✅ | ✅ | ✅ |
| Async / SQLAlchemy | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| Per-request DI | ✅ | ✅ | ✅ | 🟡 | 🟡 | ❌ | 🟡 | 🟡 | 🟡 | 🟡 |
| Subagent dispatch | (via §2.2) | ✅ | n/a | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| Audit-visible compaction | n/a | n/a | ❌ | ❌ | n/a | 🟡 | n/a | n/a | n/a | n/a |
| Maturity | 🟡 | 🟡 | 🟡 | 🟡 | ✅ | ✅ | ✅ | ✅ | ✅ | 🟡 |
| Dep weight | ✅ | ✅ | ✅ | ❌ | ❌ | ❌ | 🟡 | ❌ | 🟡 | ❌ |
| Layered adoption | ✅ | ✅ | ✅ | 🟡 | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ |

---

## 4. The integration story

What changes in our codebase, concretely.

**No migration.** `Agent(model, tools=[...], deps_type=ChatDeps)` keeps working. Capabilities are an additive `capabilities=[...]` argument. Our existing infrastructure stays intact:
- `ai_config.get_model()` continues to resolve providers per-org from DB
- `ChatDeps` keeps its dataclass shape (we add a `clone_for_subagent` method)
- `embedding`, RAG SQL, `ChatMessage` schema, sessions table — unchanged
- `ai_vision`, `protocol_generator.build_graph`, `sop_generator` — unchanged

**What gets added:**
- `pyproject.toml`: `subagents-pydantic-ai = "^0.x"` (and pydantic-ai-harness if we use built-ins from it)
- A `subagents/` directory with one `SubAgentConfig` per specialist:
  - `research_library` (consolidates `search_documents` + `read_section` + `list_documents`)
  - `protocol_builder` (replaces the `generate-protocol` skill + the fat `create_protocol_tool`)
  - `run_planner` (placeholder; new capability)
- `ChatDeps.clone_for_subagent(subagent_name)` to satisfy the protocol
- Chat agent's `tools=[...]` shrinks from 6 tools to maybe 1-2 plus `capabilities=[SubAgentCapability(...)]`

**What gets removed during migration:**
- Hardcoded `WHEN THE USER WANTS TO CREATE A PROTOCOL → load_skill('generate-protocol')` branch in `SYSTEM_PROMPT`. Replaced by the subagent's description, which the model uses for routing.
- The dual skill-injection paths (`load_skill` toolset + button-injected `skill_inject` text). Buttons trigger subagents directly with pre-filled context.
- Fat tool bodies in `create_protocol_tool` / `create_unit_op_tool`. Logic moves into the `protocol_builder` subagent (which calls thin tools that wrap REST endpoints or services).

**What stays as-is in this task:**
- `compact_history` and the `ChatMessage(role=SUMMARY)` audit trail
- `_sanitize_output` (provider-quirk specific; not a harness concern)
- The `pydantic_ai_skills` SkillsToolset — likely retired once subagents replace `generate-protocol`, but we keep it during migration for safety

---

## 5. Risks and mitigations

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Pre-1.0 breaking changes in `subagents-pydantic-ai` | Medium | Low | Pin to a specific minor version; revisit on minor bumps. Internal API surface for us is small (just `SubAgentConfig` + `SubAgentCapability` constructor). |
| `clone_for_subagent` semantics not documented for `AsyncSession` | Medium | Medium | The session is per-request and lives in the parent's DI scope. Subagents inherit the same session by default; verify in spike. If contention surfaces, give each subagent its own session (factory pattern already used in background tasks). |
| Subagent quality regression vs. current monolith | Medium | High | Run the 5-query regression suite (acceptance criteria) before flipping. If a subagent underperforms, fold it back into the main agent. |
| Skill / subagent overlap during transition | Low | Low | Keep both running until the subagent is proven; remove `generate-protocol` skill last. |
| Maintainer abandons `subagents-pydantic-ai` | Low | Medium | MIT-licensed; we can fork. The capability is small (a few hundred lines on top of pydantic-ai). The cost of forking is bounded. |

---

## 6. Adoption plan

A revised sequencing for the rest of TD-0081, replacing the original Phase 2-4 plan:

| Phase | Deliverable | Risk |
|---|---|---|
| **2 (was: target structure)** | Spike `research_library` as a `SubAgentCapability` on a branch. Measure: line-count delta, dep-tree growth, latency vs. tool-flat baseline, integration with `ChatDeps`. ≤4 hours. | Low — throwaway code. |
| **3 (was: incremental migration)** | If spike succeeds: implement target file structure (`chat_agent.py`, `subagents/`, `tools/`, `runtime/`), migrate research first, then protocol_builder, then run_planner. Each step preserves existing chat tests + manual smoke. | Medium — touches main chat flow. |
| **4 (TD-0063 + regression)** | Globalize the chat agent (no more per-turn instantiation; absorbs TD-0063). Run 5-query regression. Document quality changes. | Medium — could expose state-leak bugs from globalization. |

Original acceptance criteria survive intact; this just renames "subagents follow target structure" to "subagents are SubAgentConfigs registered via SubAgentCapability."

---

## 7. What we're not adopting (and why)

| Feature | Why not now |
|---|---|
| `ContextManagerMiddleware` (auto-compaction) | We have audit-visible compaction. Don't lose observability for a feature parity gain. |
| Persistent memory (MEMORY.md) | No requirement today. If we add per-user/per-org memory, do it as a Postgres-backed Capability that fits our data model. |
| Code execution / sandbox | Wrong domain. We don't run user code. |
| Filesystem tools | Wrong domain. Our agent operates over Postgres. |
| Web search / fetch | Org-internal tool, not a web research agent. |
| Browser automation | Not in scope. |
| Planner subagent | The current protocol skill already does step-by-step gating conversationally. Add a planner if a future capability needs explicit subtask tracking. |
| Checkpoints / fork conversations | Not a current product requirement. |
| Agent teams (shared TODO + bus) | Single-tenant chat agent. No team coordination requirement. |
| Cost tracking capability | Already covered by `ai_config` usage logging at the model level. |

These are not rejected on principle — they're rejected as scope creep for **this** task. Each can come back as its own task with its own brainstorm.

---

## 8. Sources

- [pydantic-ai Capabilities (official docs)](https://pydantic.dev/docs/ai/core-concepts/capabilities/)
- [pydantic/pydantic-ai-harness (GitHub)](https://github.com/pydantic/pydantic-ai-harness)
- [vstorm-co/subagents-pydantic-ai (GitHub)](https://github.com/vstorm-co/subagents-pydantic-ai)
- [vstorm-co/summarization-pydantic-ai (GitHub)](https://github.com/vstorm-co/summarization-pydantic-ai)
- [vstorm-co/pydantic-deepagents (GitHub)](https://github.com/vstorm-co/pydantic-deepagents)
- [langchain-ai/deepagents (GitHub)](https://github.com/langchain-ai/deepagents)
- [Claude Agent SDK overview](https://code.claude.com/docs/en/agent-sdk/overview)
- [pydantic-ai Multi-Agent Applications](https://ai.pydantic.dev/multi-agent-applications/)
- [Feature Request: First-class Context Compaction API (pydantic-ai #4137)](https://github.com/pydantic/pydantic-ai/issues/4137)
- DataCamp / pecollective / OpenAgents 2026 framework comparisons (LangGraph vs CrewAI vs AutoGen)

---

## 9. Questions for review

1. **Adopt the recommendation as written?** (à la carte: subagents only, keep our compaction, skip bundles)
2. **Spike scope:** start with `research_library` (simpler), or with `protocol_builder` (more end-to-end risk, but the actual P1 quality pain point)? My lean: `research_library` — quicker signal, lower blast radius if we abort.
3. **Pin policy:** pin `subagents-pydantic-ai` to a minor version (`~=0.x`) or to a specific patch? Pre-1.0 means minor bumps may break — I'd pin to a specific minor and bump deliberately.
4. **`pydantic-ai-harness` umbrella package:** install or import only the specific sub-packages we use? My lean: only the sub-packages, to keep the dependency surface explicit.
