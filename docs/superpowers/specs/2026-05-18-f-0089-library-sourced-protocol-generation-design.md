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

1. Let protocol_creator and protocol_editor ground drafts on the indexed
   library and cite source document titles.
2. Force the user to pick a source — Library, OpenWetWare, From scratch, or
   Search all — before any generation begins.
3. Keep the existing F-0084 OpenWetWare path working without regression.
4. Verify the library subagent's indexing-status filter and add tests.

## Non-Goals

- No changes to retrieval ranking, chunking, or the document_chunks schema.
  TD-0085 owns that.
- No new frontend components — reuse the existing `ChatSkillButtons` and
  `skill_id` plumbing.
- No tool renames — `TOOL_LABELS` stays as-is.
- No feature flag — this is just a new skill choice.

## Architecture

### Subagent topology

`research_library` keeps its existing config (name, tools, prompt). It is
registered in **two** places:

- **Top-level** sibling under `chat_agent` — so the agent can dispatch it
  directly for plain library searches and for the "Search all" fallback.
- **Nested** inside `protocol_creator` and `protocol_editor` — so those
  subagents can ground their drafts without round-tripping through
  chat_agent.

```
chat_agent
├── research_library              (sibling — for direct queries)
├── protocol_knowledgebase        (sibling — F-0084 OpenWetWare)
├── protocol_creator
│   └── research_library          (nested — for grounding)
├── protocol_editor
│   └── research_library          (nested — for grounded edits)
└── run_planner
```

`SubAgentCapability.max_nesting_depth` bumps from 1 → 2 to permit
chat_agent → protocol_creator → research_library.

### Wiring shape

```python
# protocol_creator/config.py
from app.services.ai.subagents.research_library.config import (
    create_research_library_subagent,
)
from subagents_pydantic_ai import create_subagent_toolset

def create_protocol_creator_subagent() -> SubAgentConfig:
    nested = [create_research_library_subagent()]
    return SubAgentConfig(
        name="protocol_creator",
        ...,
        agent_kwargs={
            "tools": [list_projects, list_protocols, ...],
            "toolsets": [create_subagent_toolset(nested)],
        },
        capability=SubAgentCapability(
            ...,
            max_nesting_depth=2,
        ),
    )
```

`protocol_editor/config.py` mirrors this.

`ChatDeps.clone_for_subagent` already preserves nested subagents and shared
state (sources, tool_calls, db session, org_id) when `max_depth > 0`. No
change needed in `deps.py`.

### Chat skill

A new skill file at `backend/skills/new-protocol/SKILL.md` defines the
source-picker contract. Frontmatter (`name`, `description`, `icon`) plus a
body that instructs the agent to:

1. Offer four choices in plain text: Library, OpenWetWare, From scratch,
   Search all.
2. Not dispatch any subagent until the user has chosen.
3. Route based on the choice:
   - **Library** → dispatch `protocol_creator` with `source=library` in the
     brief. protocol_creator calls its nested `research_library` and cites
     document titles in the description.
   - **OpenWetWare** → existing F-0084 path (`protocol_knowledgebase` HITL,
     then `protocol_creator`).
   - **From scratch** → existing direct `protocol_creator` path.
   - **Search all** → research_library first; if no relevant chunks, fall
     back to protocol_knowledgebase. Then dispatch protocol_creator.

### skill_id plumbing

`ChatMessageCreate.skill_id` already exists end-to-end (schema, frontend
chat-store, `/chat/skills` endpoint) but is currently ignored by the
backend agent. We wire it through:

- `app/api/endpoints/chat.py` passes `request.skill_id` to
  `send_message_streaming`.
- `send_message_streaming(... skill_id: Optional[str] = None)` reads
  `<settings.skills_dir>/<skill_id>/SKILL.md`, strips frontmatter, and
  prepends the body to the user message text **for that turn only**.
- Unknown skill_id → log warning, continue with unmodified message.

The skill body is not stored on the message row and is not added to the
system prompt — it's a per-turn instruction injection, scoped to the
invocation.

### Prompt updates

`backend/app/services/ai/prompts/chat_agent.md` — short addition telling
the agent that when a turn is prefixed with skill instructions, follow them
precisely; do not skip an instruction to ask the user a question, even if
the answer seems obvious.

`backend/app/services/ai/subagents/protocol_creator/prompt.md` — addition:
when the brief contains `source=library`, call the nested research_library
subagent via `task()` to gather grounding chunks; cite returned document
titles in the protocol description; if nothing relevant comes back, tell
the user and ask whether to proceed from scratch.

`backend/app/services/ai/subagents/protocol_editor/prompt.md` — same
pattern, scoped to edits rather than new-protocol drafting.

### Library indexing-status filter

`research_library.list_documents` currently returns documents in all
statuses. Add a filter to return only `VIEWABLE_STATUSES = {INDEXED,
ENRICHED, READY}` so the subagent doesn't surface unindexed or failed
documents to the LLM. `search_documents` already routes through
`retrieve_relevant_chunks` which only matches indexed chunks, so no change
there.

## Testing

### Unit tests

`tests/unit/test_subagents_research_library.py` — extend:
- `test_list_documents_filters_to_viewable_statuses` — seed docs in
  PENDING/INDEXED/ENRICHED/READY/FAILED; assert only the three viewable
  statuses come back.
- `test_search_documents_uses_retrieve_relevant_chunks` — mock retrieval,
  assert org_id and query are passed correctly.

`tests/unit/test_subagents_protocol_creator.py` — new or extend:
- `test_config_includes_research_library_nested_toolset` — assert
  `agent_kwargs["toolsets"]` wraps research_library.
- `test_capability_max_nesting_depth_is_2`.

`tests/unit/test_subagents_protocol_editor.py` — mirror the above.

`tests/unit/test_chat_agent_skill_prefix.py` — new:
- `test_send_message_with_skill_id_prefixes_skill_body`.
- `test_send_message_with_unknown_skill_id_logs_warning_and_continues`.
- `test_send_message_without_skill_id_unchanged`.

### Integration tests

`tests/integration/test_library_sourced_protocol_creation.py` — new:
- `test_library_source_flow_end_to_end` — seed an indexed doc with chunks,
  invoke chat with `skill_id="new-protocol"` and a Library reply, mock the
  LLM (TestModel/FunctionModel) to deterministically call
  `task("research_library", ...)` then `create_protocol(...)`, assert:
  (a) research_library was invoked nested under protocol_creator,
  (b) the protocol description cites the seeded doc title.
- `test_openwetware_source_flow_still_works` — F-0084 regression. Pick
  OpenWetWare, mock protocol_knowledgebase HITL, assert no research_library
  call.
- `test_from_scratch_source_skips_research` — pick From scratch, assert
  neither research subagent invoked.

### Mocking boundary

Mock at the **LLM model layer** (pydantic-ai TestModel/FunctionModel) — not
at `task()` — so subagent toolset construction, deps cloning, and
depth-counting are exercised for real.

### Skipped

- No pgvector ANN tests (TD-0085 territory).
- No frontend tests — `ChatSkillButtons` and `chat-store` unchanged.
- No load/concurrency tests on subagent nesting (library owns that).

## Affected Files

**Backend (modified):**
- `app/api/endpoints/chat.py` — pass skill_id through
- `app/services/ai/send_message.py` — accept skill_id, inject SKILL.md
- `app/services/ai/chat_agent.py` — bump max_nesting_depth to 2
- `app/services/ai/prompts/chat_agent.md` — follow-skill-instructions note
- `app/services/ai/subagents/protocol_creator/config.py` — nested toolset
- `app/services/ai/subagents/protocol_creator/prompt.md` — grounding note
- `app/services/ai/subagents/protocol_editor/config.py` — nested toolset
- `app/services/ai/subagents/protocol_editor/prompt.md` — grounding note
- `app/services/ai/subagents/research_library/tools.py` — VIEWABLE_STATUSES
  filter on list_documents

**Backend (new):**
- `backend/skills/new-protocol/SKILL.md`
- `tests/unit/test_chat_agent_skill_prefix.py`
- `tests/unit/test_subagents_protocol_creator.py` (if absent)
- `tests/unit/test_subagents_protocol_editor.py` (if absent)
- `tests/integration/test_library_sourced_protocol_creation.py`

**Frontend:** none.

**Rules / CLAUDE.md:** small note in `.claude/rules/conventions.md` about
nested subagent toolsets after implementation lands; no Feature flags table
change.

## Risks & Open Questions

- **Nesting depth math.** Need to confirm `max_nesting_depth=2` at the top
  level is correctly interpreted by `subagents_pydantic_ai` (i.e. depth
  counts the chain, not just the immediate child). Verified at
  implementation time by the integration test — if it fails with a "max
  depth exceeded" error we bump or fix.
- **Tool indicator UX.** Nested `task("research_library", ...)` calls may
  render as just "Using task…" in the chat thinking indicator. Acceptable
  for v1; file `/add_task` if it's confusing during QA.
- **Skill discovery.** Skills are read from `settings.skills_dir` at
  request time, not cached. Adding `new-protocol/SKILL.md` is sufficient
  for it to appear in `/chat/skills` and on the frontend skill chips.
