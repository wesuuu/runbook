# F-0089 — Library-Sourced Protocol Generation Design

**Status:** Draft
**Date:** 2026-05-18
**ClickUp:** F-0089 (86e1ef8d1)

## Problem

Protocol creation chat can ground new protocols on the public OpenWetWare
knowledgebase (F-0084) or generate from scratch, but cannot ground on the
user's own indexed research library. The `research_library` subagent exists
and can search/read the org's documents, but `protocol_creator` and
`protocol_editor` can't reach it. There is also no UX affordance forcing the
user to pick a source up front, so the agent picks (or skips) silently.

## Goals

1. Let protocol_creator ground new drafts on the indexed library and cite
   source document titles.
2. Force the user to pick a source — Library, OpenWetWare, From scratch, or
   Search all — before any generation begins.
3. Keep the existing F-0084 OpenWetWare path working without regression.
4. Verify the library subagent's indexing-status filter and add tests.

## Non-Goals

- **No skill on `protocol_editor`.** The skill's job is to force the source
  decision before drafting begins. Editing happens mid-conversation against
  an open protocol — surfacing a four-option picker on every "add a wash
  step" is friction. The editor consumes library context via the existing
  `research_library` dispatch path through shared `ChatDeps.sources`. If
  explicit-provenance edits become a real pain point post-launch, add an
  `edit-protocol` skill then. (Acceptance criterion "Wire into Protocol
  Creator/Editor" is read as "editor can also consume library citations
  when relevant" rather than "user-facing source picker on both".)
- No changes to retrieval ranking, chunking, or the document_chunks schema.
  TD-0085 owns that.
- No new frontend components — reuse the existing `ChatSkillButtons`.
- No tool renames — `TOOL_LABELS` stays as-is.
- No feature flag — this is just a new skill choice.

## Architecture

### Subagent topology — sibling orchestration

All four subagents live at the same level under chat_agent. The chat_agent
orchestrates the sequence; subagents stay single-purpose. This mirrors the
proven F-0084 OpenWetWare pattern.

```
chat_agent (orchestrator on chat_model — strongest tier)
├── research_library              (search/read library)
├── protocol_knowledgebase        (F-0084 OpenWetWare; HITL)
├── protocol_creator              (draft new protocol from brief)
├── protocol_editor               (edit existing protocol)
└── run_planner
```

`SubAgentCapability.max_nesting_depth` stays at 1.

### Why sibling, not nested

Lower-tier `subagent_model` / `creation_model` (e.g. Kimi K2) handles
single-decision tasks well but degrades on multi-step meta-reasoning
("decide if I need grounding → formulate query → interpret chunks →
re-search → draft → cite"). Sibling orchestration narrows each subagent
to one job:

- **research_library**: "search this topic, return chunks." One decision.
- **protocol_creator**: "given these chunks pre-loaded in the brief, draft
  a protocol that cites them." One decision.
- **chat_agent** (runs on the strongest `chat_model`): follows the skill's
  recipe to wire the two together.

Orchestration logic moves out of subagent model reasoning and into a
skill prompt the orchestrator follows. We accept that protocol_creator
can't iteratively refine its searches — for v1 this is acceptable; user
iterates in chat instead.

### Skills via `pydantic-ai-skills`

We use the `pydantic-ai-skills 0.6.0` package (already installed) rather
than building custom skill-prefix plumbing. The framework provides a
`SkillsCapability` that integrates into the existing `capabilities=[...]`
API on the chat Agent.

**How it works:**

1. `SkillsCapability(directories=['./skills'])` is added to the chat agent
   alongside the existing `SubAgentCapability` and
   `ContextManagerCapability`.
2. The framework auto-injects a system-prompt header listing available
   skills by name + description (progressive disclosure — full content is
   not in the system prompt).
3. The framework exposes `load_skill(skill_name)`, `list_skills()`,
   `read_skill_resource()`, and `run_skill_script()` tools to the agent.
4. When the model decides a skill applies (or is told to use it), it
   calls `load_skill("new-protocol")`. The full SKILL.md body comes back
   wrapped in `<skill><instructions>...</instructions></skill>` tags.
5. The loaded content lives in conversation history as a tool result —
   persists across turns, survives compaction the same way other tool
   outputs do. No custom plumbing required.

**What we don't build (deleted from earlier spec drafts):**

- No `skill_id` plumbing through `send_message_streaming`.
- No SKILL.md frontmatter parsing in `send_message.py`.
- No turn-1-only prefix injection logic.
- No frontend `active_skill_id` state.

**What we keep:**

- The existing `GET /chat/skills` endpoint stays. Frontend uses it to
  render skill chips. (Its parsing is independent of `pydantic-ai-skills`
  — it reads our project-specific `icon` field from frontmatter and lists
  skills for the UI. The same SKILL.md file serves both consumers.)
- `ChatMessageCreate.skill_id` stays in the schema. Activation is wired
  through two complementary mechanisms (see "Skill activation" below).

### Skill activation — server-prefix + prompt guardrail

Two paths reach the same end state (`load_skill("new-protocol")` called
deterministically by the model on the first relevant turn):

**Path C — chip click (deterministic, server-composed prefix).** When
the frontend posts a message with `skill_id="new-protocol"`,
`send_message.py` prepends `[skill:new-protocol] ` to the
**model-visible** message text before invoking the agent. The user-visible
chat history stays clean — the chip badge in the composer (per the mock)
is the user's affordance, the prefix is a model directive. The
chat_agent.md instruction handles dispatch: *"If a user message begins
with `[skill:<id>]`, load that skill immediately on the first tool call
before doing anything else."*

**Path B — typed request (prompt-guarded, model judgment).** When the
user types something like "draft me a new protocol for media prep"
without clicking the chip, the model decides. A short named section in
`chat_agent.md` keeps this precise:

```
## Skill: new-protocol
Load `new-protocol` only when the user is asking to *create* a new
protocol, signaled by either:
  - a `[skill:new-protocol]` prefix on their message, OR
  - an unambiguous creation request ("draft", "create", "make me a
    new protocol", "build a protocol for X").
Do NOT load `new-protocol` for:
  - questions about existing protocols (summarize, explain, what does
    step 3 do)
  - edits to an open protocol (add a wash step, change the temperature)
  - general library lookups (what SOPs do we have for lyophilization)
Once loaded, follow the skill's instructions for the turn that
requested creation. If a subsequent turn shifts to non-creation work,
proceed without re-loading.
```

The two paths exist because the chip is a strong intent signal that
shouldn't be left to model judgment, and typed requests need a
discretion layer with explicit anti-patterns. Lower-tier subagent
models (Kimi K2) are exactly the ones that would mis-activate without
this guardrail.

### Skill file: `backend/app/services/ai/skills/new-protocol/SKILL.md`

Frontmatter declares `name`, `description`, and our project-specific
`icon` field. Body instructs the agent to:

1. Offer four choices in plain text: Library, OpenWetWare, From scratch,
   Search all.
2. Not dispatch any subagent until the user has chosen.
3. Route based on the choice. The three explicit options are
   **hard-scoped** — picking Library does not silently escalate to
   OpenWetWare or scratch. "Search all" is the dedicated heuristic option
   for users who want the agent to figure it out.

   - **Library** → dispatch `research_library` with the topic; then
     dispatch `protocol_creator` with the returned chunks pre-loaded in
     the brief under a `grounding:` section. If `research_library`
     returns an empty list, do NOT fall through. Reply with: *"No
     matching library documents. Want me to run Search all instead?"*
     and stop. One-click redirect to the heuristic, no silent
     escalation.
   - **OpenWetWare** → existing F-0084 path (`protocol_knowledgebase`
     HITL, then `protocol_creator`). Empty result → same hard-stop +
     redirect-prompt pattern.
   - **From scratch** → direct `protocol_creator` dispatch with no
     grounding.
   - **Search all** → the heuristic home. v1 heuristic = research_library
     first; if empty, protocol_knowledgebase (HITL); if still empty,
     scratch. Future heuristics (topic-based routing, multi-source
     merging) land here without touching the explicit options.

   "Empty" means the retrieval tool returned zero results — not "the
   LLM judged the chunks irrelevant." The subagent does not discard
   hits.

### Prompt updates

`backend/app/services/ai/prompts/chat_agent.md` — two additions: (1) the
`[skill:<id>]` prefix dispatch instruction (Path C), and (2) the
`## Skill: new-protocol` guardrail block (Path B). Both are documented in
the "Skill activation" section above.

`backend/app/services/ai/subagents/protocol_creator/prompt.md` —
addition: when the brief contains a `grounding:` section with document
titles + chunk content, draft the protocol from those chunks and append
a citation footer to the protocol description in this exact format:

```
Grounded in: {n} library document(s):
- {doc_title_1}
- {doc_title_2}
```

Document titles only (copy verbatim from the brief). No page numbers
(null in the markdown-chunked pipeline), no quotes, no chunk indices.
Do NOT call any retrieval tools — chat_agent handles retrieval before
dispatching. The chat UI's citations sidebar populates automatically
from `ChatDeps.sources` (set by `search_documents`); no extra work
required for that.

`protocol_editor/prompt.md` is unchanged. Editor stays un-skilled per
"Non-Goals".

### Frontend — composer "skill mode"

The mock (`docs/superpowers/specs/mockups/f0089-library-sourced-protocol.html`)
shows the chip as a persistent badge on the composer rather than a
one-shot send. Current behavior in `chat-store.svelte.ts:685` is
auto-send — the chip click shoves the skill name into the textarea and
immediately calls `sendMessage(skill.name)`. We replace that with a
sticky-active pattern so the user can type their actual brief before
sending.

**State change in `chat-store.svelte.ts`:**

- Add module-level `let activeSkill = $state<ChatSkill | null>(null)`.
- Add `getActiveSkill()` and `clearActiveSkill()` exports.
- Rewrite `activateSkill(skill)` to set `activeSkill = skill` and focus
  the textarea — no auto-send.
- `sendMessage()` (no args) reads `activeSkill` and passes its `name` as
  the `skill_id` body field. After the SSE `done` event resolves,
  `activeSkill` clears (one-message scope; user re-clicks the chip if
  they want a second skill-grounded turn). This matches the source-picker
  semantics: the skill governs *the turn that requested creation*, not
  every subsequent turn.

**UI changes in `ChatPanel.svelte`:**

- When `activeSkill !== null`, render a badge row directly above the
  textarea showing `<skill icon> <Skill Name> ✕`. The ✕ calls
  `clearActiveSkill()`. Badge styling matches the mock — `bg-accent/10
  text-accent border-accent/40 rounded-md` with the lucide icon mapped
  from `skill.icon`.
- Apply accent-tinted border + ring to the textarea wrapper when
  `activeSkill` is set: `border-accent ring-1 ring-accent/30`. Returns to
  default `border-border/60 focus:ring-primary/30` when cleared.
- `ChatSkillButtons` calls `activateSkill` as today; the button now
  visually toggles. When `activeSkill?.name === skill.name`, the chip
  renders with `aria-pressed="true"` + accent background.

**No new components.** Badge is inline JSX in `ChatPanel.svelte`. The
existing `ChatSkillButtons` is reused as-is (only the parent's `active`
prop wiring is new).

**Out of scope for v1:** structured source-picker card UI. The four-option
picker in the mock is rendered as **plain assistant text from the
SKILL.md instructions** — the user replies "Library" / "OpenWetWare" /
"From scratch" / "Search all" in chat, no special component. Upgrading
to a click-able card is a follow-up if the plain-text picker proves
ambiguous in usability testing.

### `chat_agent.py` changes

One addition to the cached `Agent(...)` construction at chat_agent.py:201:

```python
from pydantic_ai_skills import SkillsCapability

capabilities=[
    SubAgentCapability(...),         # unchanged
    ContextManagerCapability(...),   # unchanged
    SkillsCapability(directories=[settings.skills_dir]),  # NEW
],
```

`auto_reload=False` (default) — skills are loaded once per cached agent
instance; cache key already varies by `(chat_model, subagent_model,
summary_model, context_window)`, which is fine for our use.

### Library indexing-status filter

`research_library.list_documents` currently returns documents in all
statuses (the LEFT JOIN at tools.py:280 has no status filter). Add a
filter to return only the documents listed in `VIEWABLE_STATUSES`
(`INDEXED`, `ENRICHED`, `READY` — already defined at
`backend/app/models/library.py:69–71`). `search_documents` already routes
through `retrieve_relevant_chunks` which only matches indexed chunks, so
no change there.

## Testing

### Unit tests

`tests/unit/test_subagents_research_library.py` — extend:
- `test_list_documents_filters_to_viewable_statuses` — seed docs in
  multiple statuses (e.g. UPLOADED, INDEXING, INDEXED, ENRICHED, READY,
  FAILED); assert only INDEXED/ENRICHED/READY come back.

`tests/unit/test_subagents_protocol_creator.py` — extend or create:
- `test_prompt_includes_grounding_instruction` — assert prompt.md text
  contains the "cite chunks pre-loaded in your brief" instruction so it
  doesn't silently drift.

`tests/unit/test_chat_agent_prompt_guardrail.py` — new:
- `test_chat_agent_prompt_includes_skill_prefix_dispatch_rule` — assert
  `chat_agent.md` contains the `[skill:<id>]` prefix dispatch
  instruction (Path C wiring stays intact).
- `test_chat_agent_prompt_includes_new_protocol_guardrail` — assert the
  `## Skill: new-protocol` section is present with the listed
  do/do-not bullets (Path B guardrail stays intact).

`tests/unit/test_skills_capability_loads_new_protocol.py` — new:
- `test_skills_capability_discovers_new_protocol_skill` — instantiate the
  chat agent, assert `new-protocol` is in the skills list exposed by the
  capability.
- `test_skill_md_has_required_frontmatter` — parse
  `backend/app/services/ai/skills/new-protocol/SKILL.md`; assert `name`, `description`,
  `icon` are present and that the body is non-empty.

### Integration tests

`tests/integration/test_library_sourced_protocol_creation.py` — new:
- `test_skill_id_triggers_server_side_prefix` — POST a chat message with
  `skill_id="new-protocol"`; assert the model-visible message text
  (captured via TestModel/FunctionModel) starts with `[skill:new-protocol] `
  while the persisted user message text in the DB stays clean
  (Path C wiring).
- `test_library_source_flow_end_to_end` — seed an indexed doc with chunks,
  invoke chat with `skill_id="new-protocol"` and a Library reply, mock
  the LLM (TestModel/FunctionModel) to deterministically call
  `load_skill("new-protocol")`, then `task("research_library", ...)`,
  then `task("protocol_creator", ...)`. Assert:
  (a) research_library was dispatched,
  (b) protocol_creator received chunks in its brief,
  (c) the created protocol's description cites the seeded doc title.
- `test_library_empty_result_offers_search_all_redirect` — seed no
  matching docs; Library path; assert the assistant reply prompts the
  "run Search all instead?" redirect and does NOT silently dispatch
  protocol_knowledgebase or proceed to scratch.
- `test_search_all_falls_through_library_then_openwetware` — seed no
  library matches; Search all path; assert library searched first,
  then OpenWetWare HITL invoked.
- `test_openwetware_source_flow_still_works` — F-0084 regression. Pick
  OpenWetWare, mock protocol_knowledgebase HITL, assert no
  research_library call.
- `test_from_scratch_source_skips_research` — pick From scratch, assert
  neither research subagent invoked.

### Mocking boundary

Mock at the **LLM model layer** (pydantic-ai TestModel/FunctionModel) so
SkillsCapability discovery, SubAgentCapability dispatch, deps cloning,
and event surfacing are all exercised against real framework code.

### Lower-tier model performance evaluation

Sibling orchestration was chosen partly to keep cognitive load low on the
`subagent_model` / `creation_model` (e.g. Kimi K2). The browser
verification step must explicitly evaluate this:

1. Run the Library flow end-to-end against a seeded indexed doc using
   the default models. Confirm the protocol cites the doc title.
2. If the configured `creation_model` is a lower-tier model (Kimi K2 or
   equivalent), run the same flow and verify protocol_creator did not
   hallucinate citations, drop chunks, or skip the brief-grounding step.
3. Compare draft quality (protocol step coherence, parameter realism) to
   the From-scratch baseline on the same topic — Library-grounded should
   be visibly better, not just longer.

Record findings in the QA agent's report. If lower-tier performance is
poor, the lever is the SKILL.md recipe (more explicit chunk formatting,
more directive grounding language in protocol_creator's prompt).

### Compaction-survival checkpoint

The skill block (`<skill id="new-protocol"><instructions>...`) lives in
conversation history as a tool-result message. When
`ContextManagerCapability` summarizes older turns at the 60% threshold,
that block is just text — there is no built-in instruction telling the
summarizer to preserve `<skill>` blocks verbatim. If it gets summarized,
later turns lose the source-picker contract silently.

Verification adds a fourth check:

4. Click the chip, generate a library-grounded protocol, then continue
   chatting until compaction fires (or force-trigger via a long history
   replay). Ask a follow-up creation-adjacent question. Inspect the
   agent's effective context: is `<skill id="new-protocol">` still
   present, or did it get summarized?

If the skill survives → no extra work. If it gets summarized → the
mitigation is one of: (a) add a `<skill>`-preserve directive to the
summarizer prompt, or (b) re-inject the skill content on every turn
where `skill_id` is set in the request payload. Pick the lighter-touch
option based on what we observe; don't pre-engineer either.

### Frontend tests

`frontend/src/lib/chat-store.test.ts` — extend:
- `activateSkill_sets_active_state_without_sending` — call
  `activateSkill(skill)`; assert `getActiveSkill()` returns the skill,
  no network request was made, `messageInput` was not overwritten with
  the skill name (legacy auto-send behavior is gone).
- `sendMessage_attaches_active_skill_id_then_clears` — set active skill,
  call `sendMessage()`, intercept the request body, assert
  `body.skill_id === skill.name`; assert `activeSkill` is null after the
  `done` event resolves.
- `clearActiveSkill_resets_state` — set active skill, call
  `clearActiveSkill()`; assert `getActiveSkill()` returns null and the
  next `sendMessage()` body has no `skill_id`.

No Playwright e2e for v1 — covered indirectly by the integration test
that POSTs `skill_id` and asserts the server-side prefix.

### Skipped

- No pgvector ANN tests (TD-0085 territory).
- No `ChatSkillButtons.svelte` unit tests — only callsite wiring
  changes, behavior is exercised through `chat-store.test.ts`.

## Affected Files

**Backend (modified):**
- `app/services/ai/chat_agent.py` — add `SkillsCapability` to
  `capabilities=[...]`
- `app/services/ai/prompts/chat_agent.md` — add `[skill:<id>]` prefix
  dispatch rule + `## Skill: new-protocol` guardrail block
- `app/services/ai/send_message.py` — when the incoming
  `ChatMessageCreate.skill_id` is set, prepend `[skill:<skill_id>] ` to
  the **model-visible** message text (UserPrompt content) before the
  agent run. The persisted `ChatMessage.content` in the DB stays clean.
- `app/services/ai/subagents/protocol_creator/prompt.md` — grounding
  instruction
- `app/services/ai/subagents/research_library/tools.py` —
  `VIEWABLE_STATUSES` filter on `list_documents`

**Backend (new):**
- `backend/app/services/ai/skills/new-protocol/SKILL.md`
- `tests/unit/test_skills_capability_loads_new_protocol.py`
- `tests/unit/test_subagents_protocol_creator.py` (if absent)
- `tests/unit/test_chat_agent_prompt_guardrail.py`
- `tests/integration/test_library_sourced_protocol_creation.py`

**Frontend (modified):**
- `frontend/src/lib/chat-store.svelte.ts` — sticky-active skill state
  (`activeSkill`, `getActiveSkill`, `clearActiveSkill`); rewrite
  `activateSkill` to set state instead of auto-sending; `sendMessage`
  reads `activeSkill.name` for `skill_id`; clears on `done` event.
- `frontend/src/lib/components/ai/ChatPanel.svelte` — render skill
  badge above textarea when `activeSkill` is set; accent border/ring on
  composer in skill mode; pressed-state on the active chip in
  `ChatSkillButtons`.

**Frontend (unchanged):** `ChatSkillButtons.svelte` already accepts
`onactivate` — only callsite wiring changes. No new components.

**Rules / CLAUDE.md:**
- Small addition to `.claude/rules/backend-ai.md` documenting
  `SkillsCapability` as a third capability alongside SubAgent and
  ContextManager.
- No Feature flags table change.

## Risks & Open Questions

- **Lower-tier model behavior.** Sibling orchestration trades iterative
  retrieval refinement for cognitive simplicity. If creation_model
  hallucinates citations or drops chunks in the brief, the lever is the
  SKILL.md recipe (chunk formatting) and `protocol_creator/prompt.md`
  (directive grounding language). Verified during browser verification.
- **Chunk-passing payload size.** Library chunks pre-loaded in the brief
  consume context. The `top_k=8` default in research_library is fine; if
  briefs balloon, drop to `top_k=4` or summarize chunks before passing.
- **Existing `/chat/skills` endpoint and `SkillsCapability` use the same
  directory.** Both parse the same SKILL.md files independently. As long
  as our SKILL.md has both the `name`/`description` (used by both) and
  `icon` (only used by `/chat/skills` for UI rendering), the dual
  consumption works cleanly. Validated by the unit test that asserts
  required frontmatter fields.
- **Cached agent picks up skill changes only on cache invalidation.**
  `auto_reload=False` is intentional — cache key already varies by
  model/context-window so new skills require a process restart in dev or
  a model config change in prod. Acceptable for v1; the `/chat/skills`
  endpoint reads from disk every request so the UI stays fresh.
