# Chat Agent Inventory

**Status:** read-only audit (Phase 1 of TD-0081). No code changes.
**Scope:** everything in `backend/app/services/ai/` plus `backend/skills/` and the chat HTTP surface.
**Goal:** map every tool, prompt, subagent, and workflow; show the call graph; flag what is and is not "the chat agent."

---

## 1. What lives in `app/services/ai/`

| File | Lines | What it actually is | Used by |
|---|---:|---|---|
| `chat_service.py` | 1263 | The chat agent: prompt + tools + RAG + session CRUD + compaction + sanitization, all tangled. | `api/endpoints/chat.py` |
| `ai_config.py` | 347 | Provider/model resolution (`get_model`, `get_context_window`). Shared infrastructure. | Every AI-using service. Not chat-specific. |
| `ai_provider_validation.py` | 63 | One-shot validator: instantiate a `pydantic_ai` provider to check credentials. | `api/endpoints/ai.py` |
| `embedding.py` | 185 | `embed_texts` / `embed_query` over Ollama / OpenAI-compatible. | `chat_service` (RAG), `document_processor`, `library` endpoint. |
| `ai_vision.py` | 421 | Vision agent (image analysis, doc text extraction). | `batch_record_extractor`, `protocol_importer`, `template_converter`. |
| `protocol_generator.py` | 302 | LLM-driven protocol generator (`generate_protocol_from_chat`) + graph-build helpers (`build_graph`, `match_unit_op`, `extract_params`). | `build_graph` is called by `create_protocol_tool` in chat. **`generate_protocol_from_chat` has no callers** other than its unit test. |
| `sop_generator.py` | 262 | An `FPDF` subclass that renders an SOP PDF. Pure document/PDF code. **Misnamed** — has nothing to do with AI. | Re-exported from `services/documents/pdf.py`. |
| `__init__.py` | 0 | empty | — |

**Implication for the reorg.** Only `chat_service.py` plus parts of `protocol_generator.py` belong to "the chat agent." `ai_config`, `ai_provider_validation`, `embedding`, and `ai_vision` are peer AI infrastructure used across the app. `sop_generator.py` is mislocated and unrelated.

---

## 2. Inside `chat_service.py` — components by responsibility

The file mixes ~7 distinct concerns. Listed in the order they appear:

### 2.1 Prompts
- `SYSTEM_PROMPT` (lines 25–43). Main agent persona + rules + a hardcoded conditional ("WHEN THE USER WANTS TO CREATE A PROTOCOL → call `load_skill('generate-protocol')`"). RAG citation rules baked in here.
- `SUMMARIZATION_PROMPT` (lines 45–48). Used only by the compaction subagent in `_generate_summary`.

### 2.2 Constants
- `RAG_TOP_K = 8`, `RAG_MAX_CONTEXT_CHARS = 12000`, `RAG_MIN_SCORE = 0.05`, `LLM_MAX_TOKENS = 16384`. RAG/runtime tuning.

### 2.3 Dataclasses / Pydantic models
- `RetrievedChunk` (dataclass) — internal RAG result.
- `ChatDeps` (dataclass) — pydantic-ai `RunContext` payload: `db`, `org_id`, `user_id`, `is_org_admin`, plus mutable accumulators `sources` and `tool_calls` populated by tool calls.
- Tool result schemas: `DocumentChunkResult`, `SearchDocumentsResult`, `SectionChunk`, `DocumentSectionResult`, `DocumentListItem`, `ListDocumentsResult`, `UnitOpInfo`, `ListUnitOpsResult`, `CreateUnitOpResult`, `CreateProtocolResult`.

### 2.4 Tools (6 total — all defined in this file)

| # | Function | What it does | "Thin" rating |
|---|---|---|---|
| 1 | `search_documents_tool` | Calls `retrieve_relevant_chunks` (also in this file). Has its own retry-with-shortened-query heuristic. Mutates `ctx.deps.sources`. | **Not thin** — embeds RAG retry logic. |
| 2 | `read_document_section_tool` | Inline raw SQL against `document_chunks` + `documents`. Mutates `ctx.deps.sources`. | **Not thin** — raw SQL in tool body. |
| 3 | `list_documents_tool` | Inline raw SQL against `documents`. | **Not thin** — raw SQL in tool body. |
| 4 | `list_unit_ops_tool` | SQLAlchemy `select` against `UnitOpDefinition` with org-scoping. | Borderline — small, but query lives in the tool. |
| 5 | `create_unit_op_tool` | Permission branching (`scope == 'org'/'project'`), duplicate check, build & insert `UnitOpDefinition`. | **Not thin** — full domain logic. |
| 6 | `create_protocol_tool` | Project-name lookup, EDIT permission check, line-by-line steps_text parser, fetch unit ops catalog, call `build_graph`, persist `Protocol`. | **Not thin** — heaviest tool by far; ~100 lines of business logic in a tool body. Also performs deferred imports. |

All six are registered together in `_call_llm` (lines 1182–1189).

### 2.5 Subagents / agent-as-toolset

- **`SkillsToolset`** (from `pydantic_ai_skills`). Lazy module-level singleton via `_get_skills_toolset()`. Exposes filesystem skills as tools. Currently surfaces 1 skill: `generate-protocol`. Registered as a `toolset` (not a tool) on the chat Agent.
- **Compaction subagent**. Inside `_generate_summary` a fresh `Agent(model, system_prompt=SUMMARIZATION_PROMPT)` is constructed for each summary call. Re-init on every compaction event (relevant to TD-0063).

The chat agent itself is the only **persistent** Agent — instantiated fresh inside `_call_llm` for each message.

### 2.6 Session CRUD (storage layer, not agent logic)
- `create_session`, `get_session`, `list_sessions`, `delete_session`. Plain DB operations, no LLM involvement.

### 2.7 Main message orchestration
- `send_message` (lines 575–659). Persists user message → calls `_call_llm` → builds metadata (sources, tool_calls, context_warning) → persists assistant message.
- `_call_llm` (lines 1138–1263). Resolves model, builds system prompt (appends `is_org_admin` + optional `skill_inject`), instantiates `Agent`, deserializes history, calls `compact_history`, optional `_truncate_to_fit` safety net, runs the agent, dedupes sources, serializes new history, sanitizes output.

### 2.8 RAG / retrieval
- `retrieve_relevant_chunks` — hybrid semantic+keyword pgvector query with character-budget truncation. Falls back to keyword-only when no embeddings exist or embedding service is down.
- `_keyword_search_chunks` — keyword-only path used as fallback.
- Both consume `embedding.embed_query` and `documents.document_processor._pad_embedding` via deferred imports.

### 2.9 Output sanitization
- `_sanitize_output` + three module-level regexes (`_THINK_PATTERN`, `_THOUGHT_HEADER_PATTERN`, `_BARE_JSON_PATTERN`). Strips `<think>` blocks, stripped "Thought Process:" headers, wraps bare JSON in code fences.

### 2.10 Token accounting + compaction
- `estimate_tokens`, `estimate_messages_tokens` (chars/4 heuristic; strips re-injected SystemPromptParts before counting).
- `compact_history` — checks budget, calls `_generate_summary`, persists `ChatMessage(role=SUMMARY)`, returns compacted history `[SystemPromptPart(summary), latest_message]`.
- `_get_last_summary`, `_build_conversation_text`, `_generate_summary`, `_truncate_to_fit` — helpers.

---

## 3. Skills (filesystem)

Path: `backend/skills/`. Discovery: `app.core.config.settings.skills_dir = "skills"`.

| Skill | Trigger paths | Mechanism |
|---|---|---|
| `generate-protocol` | (a) `SYSTEM_PROMPT` instructs the agent to `load_skill("generate-protocol")` when the user wants to create a protocol; (b) the frontend can pass `skill_id` on a message and `chat.py::send_chat_message` reads `SKILL.md` and injects the body into the system prompt as `skill_inject`. | Markdown file with YAML frontmatter (`name`, `description`, `icon`) and a step-by-step procedure. Loaded at runtime — either by `SkillsToolset` (when the model calls `load_skill`) or by direct file read in `chat.py` (button-triggered path). |

**Two injection paths for the same skill** is worth noting — the agent can also be told to load the skill via a tool, *and* the endpoint can pre-inject it into the system prompt. The two paths produce different message structures.

The skills directory has only this one skill today.

---

## 4. "Hardcoded workflows" named in the TD-0081 brief

The brief calls out three: SOP templating, batch record import, protocol generation. Status today:

| Workflow | Where it lives | Chat-invoked? | Notes |
|---|---|---|---|
| SOP templating | `app/services/ai/sop_generator.py` | **No.** Used only by `services/documents/pdf.py`. | This is an `FPDF` subclass; "AI" in the path is wrong. Not a chat workflow at all. |
| Batch record import | `app/services/batch/batch_record_extractor.py` (uses `ai_vision`) | **No.** Driven by its own endpoint `api/endpoints/batch_record_import.py`. | Already lives outside `services/ai/`. Independent agent (vision). |
| Protocol generation (conversational) | `chat_service.create_protocol_tool` + `protocol_generator.build_graph` + the `generate-protocol` skill | **Yes.** This is the live chat workflow. | The tool body is a hardcoded workflow inside the chat agent — exactly the "entanglement" the brief flags. |
| Protocol generation (one-shot) | `protocol_generator.generate_protocol_from_chat` | **No.** Has no callers other than `tests/unit/test_protocol_generator.py`. | Looks orphaned. Decision needed: revive (as a non-chat workflow) or remove. |

So **the only "hardcoded workflow" actually living inside the chat agent today is conversational protocol creation**. The other two are already separate — the reorg should make sure they stay separate, not pull them in.

---

## 5. Call graph

### 5.1 Outer (HTTP)

```
Frontend
└─ POST /chat/sessions/{id}/messages
   └─ chat.py::send_chat_message
      ├─ chat_service.get_session
      ├─ (optional) reads skills/{skill_id}/SKILL.md → skill_inject
      └─ chat_service.send_message
         └─ chat_service._call_llm

Other chat endpoints:
  GET    /chat/skills          → reads skills_dir directly (bypasses chat_service)
  GET    /chat/config          → ai_config.get_context_window / get_model_display_name
  POST   /chat/notify-admin    → no chat_service involvement
  POST   /chat/sessions        → chat_service.create_session
  GET    /chat/sessions        → chat_service.list_sessions
  GET    /chat/sessions/{id}   → chat_service.get_session
  PATCH  /chat/sessions/{id}   → direct ChatSession update (bypasses chat_service)
  DELETE /chat/sessions/{id}   → chat_service.delete_session
```

### 5.2 Inner (one chat turn)

```
chat_service.send_message
├─ save user ChatMessage
├─ auto-title from first message
└─ chat_service._call_llm
   ├─ ai_config.get_model("chat", db, org_id)              ── infrastructure
   ├─ ChatDeps(...)                                         ── per-turn state
   ├─ build system_prompt = SYSTEM_PROMPT
   │     + "USER CONTEXT: is_org_admin=…"
   │     + (optional) skill_inject
   ├─ _get_skills_toolset() → SkillsToolset (lazy singleton)
   ├─ Agent(model, system_prompt=…, tools=[6 tools], toolsets=[skills], deps_type=ChatDeps)
   │     ── AGENT INSTANTIATED PER TURN — relevant to TD-0063
   ├─ deserialize ai_message_history (best-effort)
   ├─ compact_history(...)
   │  ├─ estimate_messages_tokens                           ── if over budget…
   │  ├─ _get_last_summary (DB)
   │  ├─ _build_conversation_text(older_messages, prev_summary)
   │  ├─ _generate_summary
   │  │   └─ Agent(model, SUMMARIZATION_PROMPT).run(...)    ── compaction subagent (re-init each time)
   │  └─ persist ChatMessage(role=SUMMARY)
   ├─ _truncate_to_fit (hard-cap safety net)
   ├─ agent.run(user_content, deps, message_history, max_tokens=16384)
   │     During the run, the agent may call any of:
   │     ├─ search_documents_tool
   │     │   └─ retrieve_relevant_chunks
   │     │      ├─ embedding.embed_query (best-effort)
   │     │      ├─ pgvector hybrid SQL OR
   │     │      └─ _keyword_search_chunks (fallback)
   │     ├─ read_document_section_tool   (raw SQL)
   │     ├─ list_documents_tool          (raw SQL)
   │     ├─ list_unit_ops_tool           (SQLAlchemy)
   │     ├─ create_unit_op_tool          (permissions + insert)
   │     ├─ create_protocol_tool
   │     │   ├─ resolve project by name
   │     │   ├─ permissions.check_permission(EDIT)
   │     │   ├─ parse steps_text
   │     │   ├─ protocol_generator.build_graph
   │     │   └─ insert Protocol
   │     └─ SkillsToolset (filesystem skill loading; currently 1 skill: generate-protocol)
   ├─ dedupe sources by chunk_id
   ├─ serialize all_messages → ai_message_history
   └─ _sanitize_output(result.output)
```

---

## 6. Tests today

- `tests/unit/test_chat_service.py` — unit coverage for chat_service.
- `tests/integration/test_chat_api.py` — HTTP-level chat tests.
- `tests/unit/test_protocol_generator.py` — covers `generate_protocol_from_chat`, `build_graph`, `match_unit_op`, `extract_params`.
- `tests/unit/test_ai_config.py`, `tests/unit/test_ai_vision.py`, `tests/unit/test_embedding.py` — peer infrastructure.

These are the regression baseline for the migration phase.

---

## 7. Architectural smells (to address in role spec / target structure)

1. **`chat_service.py` mixes 7 concerns** (prompts, dataclasses, tools, RAG, session CRUD, compaction, sanitization). Each should be its own unit.
2. **Fat tools.** `create_protocol_tool` and `create_unit_op_tool` carry ~100 lines of permission/parse/persist logic. They should call services or REST endpoints, not embed logic. Same for the raw-SQL tools (`read_document_section_tool`, `list_documents_tool`).
3. **Two skill-injection paths** (`load_skill` toolset vs. `skill_inject` text from the endpoint). The model "sees" skills differently depending on path.
4. **Per-turn Agent instantiation** (TD-0063). Both the main chat agent and the summarization subagent are constructed on every call. Worth keeping in mind for the new structure.
5. **`build_graph` and friends in `protocol_generator.py`** are called directly by a tool. They are graph-shaping helpers, not really an "AI" service — candidate to move into `services/protocols/` or to live alongside the new protocol skill.
6. **`generate_protocol_from_chat` is dead code** in production. Either revive (e.g., as a /chat/sessions/{id}/generate-protocol REST workflow) or remove.
7. **Misplaced files in `services/ai/`**: `sop_generator.py` is a PDF builder; it belongs in `services/documents/` (already re-exported there). Worth moving as part of the cleanup.
8. **Implicit shared state via `ctx.deps`.** Tools mutate `deps.sources` and `deps.tool_calls`. This is fine as a pattern but should be documented in the role spec so future tools don't grow other side effects.
9. **System prompt has hardcoded workflow branching** ("WHEN THE USER WANTS TO CREATE A PROTOCOL → load_skill(...)"). If we add a second skill, the prompt grows N branches. Better: rely on the skill descriptions exposed by `SkillsToolset` and keep the system prompt skill-agnostic.

---

## 8. What's *not* in scope for this reorg

- `ai_vision.py`, `embedding.py`, `ai_config.py`, `ai_provider_validation.py` — peer infrastructure used by many services. Don't move.
- `batch_record_extractor.py` — already lives outside `services/ai/`. Leave alone.
- The chat HTTP layer (`api/endpoints/chat.py`) — only edit if tools become REST wrappers and we need new endpoints.

---

## 9. Open questions for the role spec / target structure phases

1. Should `create_protocol_tool` become a thin wrapper over a new `services/protocols/create_protocol_from_steps_text` (call-the-service) or over a new REST endpoint (call-the-API)? The brief says either is acceptable — pick one convention.
2. Should the compaction subagent be promoted to a peer module (`compaction.py`) or stay co-located with the chat agent?
3. Do we want a single skills-injection path (toolset only) or keep the dual path (toolset + button-injected text) for the foreseeable future?
4. `generate_protocol_from_chat` — keep, move, or delete?
5. Should `sop_generator.py` move to `services/documents/sop_generator.py` as part of this work, or in a follow-up?

---

*End of inventory. Next step: role spec — what the chat agent owns vs. delegates, plus the tool / subagent / workflow distinctions.*
