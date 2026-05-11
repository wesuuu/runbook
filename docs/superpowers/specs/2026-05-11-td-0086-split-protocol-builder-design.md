# TD-0086: Split protocol_builder subagent into protocol_creator + protocol_editor

**Date**: 2026-05-11
**Status**: Approved (pending plan)
**ClickUp**: [TD-0086](https://app.clickup.com/t/86e1awk1g)

## Problem

The `protocol_builder` subagent (`backend/app/services/ai/subagents/protocol_builder/`) handles both protocol creation (new protocols, new unit ops, initial roles) and editing of existing drafts (step mutations, reorder, role changes, unit-op scope elevation). It carries ~20 tools and a single 322-line prompt that has to cover every operation. Because the parent chat agent always dispatches to the same package, every turn pays the union cost of the entire tool surface and prompt — even when the user is only doing one or the other.

Splitting it into a `protocol_creator` and a `protocol_editor` subagent lets each operate with a tighter prompt and smaller tool surface, which means we can route them to a cheaper model without losing reliability. The parent agent picks the right one per turn instead of paying the union cost every time.

## Goals

- Two new subagent packages, each with a focused prompt and disjoint mutation tool set.
- Independent provider/model resolution per subagent via `get_model("protocol_creation", ...)` and `get_model("protocol_editing", ...)`.
- Parent chat agent dispatches correctly between the two with no behavioral regression.
- Existing `protocol_builder/` package stays on disk untouched this cycle; a follow-up task deletes it after benchmarks confirm the new ones are at parity or better.

## Non-Goals

- Deleting `protocol_builder/` (separate follow-up).
- Tuning the new defaults below the initial choice based on real benchmark data (separate follow-up).
- Adding new tools or changing the behavior of any existing tool.
- Touching `research_library` or `run_planner` subagents.

## Design

### Package layout

```
backend/app/services/ai/subagents/
├── protocol_builder/         # untouched this cycle; deleted in a follow-up task
├── protocol_creator/
│   ├── __init__.py           # re-exports `build`
│   ├── config.py             # SubAgentConfig wiring
│   └── prompt.md             # "design a new protocol from a user brief"
├── protocol_editor/
│   ├── __init__.py
│   ├── config.py
│   └── prompt.md             # "modify an existing draft per user request"
└── shared/
    └── protocols/
        ├── __init__.py
        └── tools.py          # full set of 20 protocol tool functions
```

`shared/protocols/tools.py` holds the complete set of tool functions (lifted from `protocol_builder/tools.py`). Each new subagent's `config.py` imports the disjoint subset it needs.

#### Tool surfaces

**protocol_creator** (8 tools):
- Reads: `list_projects`, `list_protocols`, `get_protocol`, `list_unit_ops`, `list_protocol_roles`
- Mutations: `create_unit_op`, `create_protocol`, `create_draft`

**protocol_editor** (17 tools):
- Reads: `list_projects`, `list_protocols`, `get_protocol`, `list_unit_ops`, `list_protocol_roles`
- Validation: `validate_protocol`
- Metadata: `update_protocol_metadata`
- Step mutations: `add_protocol_step`, `update_protocol_step`, `remove_protocol_step`, `reorder_protocol_steps`, `replace_step_unit_op`
- Role mutations: `add_protocol_role`, `update_protocol_role`, `remove_protocol_role`
- Unit op mutations: `update_unit_op`, `elevate_unit_op_scope`

Both subagents share the same 5 read tools so they can each scope their own work without dispatching back to the parent. No tool function is duplicated — both subagents import from the same module.

### Provider/model wiring

Two new capabilities are added to follow the existing pattern in `.claude/rules/backend-ai.md` ("Adding a New AI Capability"):

1. **`models/ai.py`** — extend `SUPPORTED_CAPABILITIES` with `"protocol_creation"` and `"protocol_editing"`. Add matching entries to `DEFAULT_CONFIGS`:
   ```python
   "protocol_creation": {"provider": "ollama", "model_name": "gpt-oss:120b-cloud"},
   "protocol_editing":  {"provider": "ollama", "model_name": "gpt-oss:120b-cloud"},
   ```
2. **`core/config.py`** — add four env-var fields to `Settings`:
   ```python
   ai_protocol_creation_provider: str = ""
   ai_protocol_creation_model: str = ""
   ai_protocol_editing_provider: str = ""
   ai_protocol_editing_model: str = ""
   ```
   No new provider-level credential fields are needed — Ollama is already wired (`settings.ollama`) and is the default for both capabilities.
3. **`settings.context_window_defaults`** — confirm `gpt-oss:120b-cloud` is present; if not, add it so compaction does not silently fall back to 8192 every turn.
4. **`backend/settings.example.yaml`** — add commented-out example entries under "AI capability routing" alongside the existing `ai_protocol_generation_*` lines:
   ```yaml
   # ai_protocol_creation_provider: ollama
   # ai_protocol_creation_model: gpt-oss:120b-cloud
   # ai_protocol_editing_provider: ollama
   # ai_protocol_editing_model: gpt-oss:120b-cloud
   ```

Per-capability env var override remains `BATCHRITE_AI_PROTOCOL_CREATION_{PROVIDER,MODEL}` / `BATCHRITE_AI_PROTOCOL_EDITING_{PROVIDER,MODEL}`, identical to the existing chat capabilities.

### `chat_agent.py` changes

```python
# imports
from app.services.ai.subagents import (
    protocol_creator,
    protocol_editor,
    research_library,
    run_planner,
)
# protocol_builder is no longer imported — its package stays on disk but is unwired

# build_chat_agent()
chat_model       = await get_model("chat", db, org_id=org_id)
subagent_model   = await get_model("chat_subagent", db, org_id=org_id)
creation_model   = await get_model("protocol_creation", db, org_id=org_id)
editing_model    = await get_model("protocol_editing", db, org_id=org_id)
summary_model    = await get_model("chat_summary", db, org_id=org_id)
context_window   = await get_context_window("chat", db, org_id=org_id)

key = _cache_key(chat_model, subagent_model, creation_model, editing_model,
                 summary_model, context_window)

subagents = [
    research_library.build(subagent_model),
    protocol_creator.build(creation_model),
    protocol_editor.build(editing_model),
    run_planner.build(subagent_model),
]
```

`_cache_key` expands to include both protocol-model strings so two orgs with the same chat/subagent/summary tuple but different protocol-capability resolutions get distinct cached agents.

### Chat agent prompt (`prompts/chat_agent.md`)

The single `protocol_builder` bullet (line 5) and dispatch heuristic (line 19) are split into two:

- **protocol_creator** — when the user wants to create a new protocol or new custom unit op.
- **protocol_editor** — when the user wants to inspect, modify, validate, or scope-change an existing protocol, its steps/roles, or an existing custom unit op.

The dispatch heuristic gets two lines instead of one, with the disambiguator being "does a protocol already exist that the user wants to change?"

### Subagent prompts

`protocol_creator/prompt.md` and `protocol_editor/prompt.md` are written fresh — they are NOT split copies of `protocol_builder/prompt.md`. Each focuses tightly on its operation:

- **Creator prompt**: protocol design from a user brief — scoping, naming, role discovery, step authoring, unit-op creation when needed, draft creation. References only the 8 tools it owns.
- **Editor prompt**: modifying an existing draft — locating the draft, making the requested mutation, validating, handling role/scope changes. References only the 16 tools it owns.

The existing `protocol_builder/prompt.md` is kept on disk unchanged for reference during the benchmark cycle.

## Testing

Per `.claude/rules/testing.md` (backend pytest-asyncio):

1. **Update `tests/unit/test_chat_agent_factory.py`** — `fake_get_model` must return values for `protocol_creation` and `protocol_editing`; assertion still passes that `build_chat_agent` returns a non-None Agent.
2. **New `tests/unit/test_subagents_protocol_creator.py`** — asserts:
   - `protocol_creator.build("openai:gpt-4.1-mini")` returns a `SubAgentConfig`
   - `name == "protocol_creator"`
   - `model == "openai:gpt-4.1-mini"`
   - The tool function set (by `__name__`) equals exactly the 8 listed above.
3. **New `tests/unit/test_subagents_protocol_editor.py`** — same shape, asserting the 17-tool set.
4. **Run the full backend suite** (`pytest`) before claiming completion — covers cache-key changes, chat-agent construction, and any indirect imports.

No integration tests are added; existing chat integration tests continue to exercise the dispatch path through the live LLM and would catch a broken subagent.

## Migration

None. No DB schema, no data backfill. The change is pure code:

- Adding `protocol_creation` and `protocol_editing` capabilities is additive — no existing rows reference them.
- Operators who have set `AiProviderConfig` rows for `chat_subagent` continue to drive `research_library` and `run_planner`. To override the new capabilities they add new rows; otherwise `DEFAULT_CONFIGS` applies (Pro+) or `ai_protocol_*_provider/model` env vars take effect.

## Rollout

1. Implement on the worktree branch.
2. Run full backend suite + start dev server, sanity-check `POST /chat/messages` with a "create a new protocol" prompt and an "edit step 2's duration on protocol X" prompt to confirm dispatch.
3. User verification — explicit sign-off per `/implement-task` flow.
4. Update `.claude/rules/backend-ai.md` if the package layout note needs to mention `subagents/shared/` (currently the rules list only the direct subagent packages).
5. Commit + push from the worktree.

## Open Questions

None at design time. The `gpt-oss:120b-cloud` model name is the user-specified default; if a real model string differs (`gpt-oss:120b` without the `-cloud` suffix, for example), it is corrected during implementation when the line is added to `DEFAULT_CONFIGS`.

## Follow-Ups (separate tasks)

- Delete `protocol_builder/` package once benchmarks confirm parity.
- Tune protocol_creation and protocol_editing defaults below `gpt-oss:120b-cloud` if benchmarks show headroom.
