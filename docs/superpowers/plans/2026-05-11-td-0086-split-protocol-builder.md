# TD-0086: Split protocol_builder subagent into creator + editor — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the monolithic `protocol_builder` subagent with two focused subagents (`protocol_creator`, `protocol_editor`) routed to independent models, so each pays only for its own tool surface and prompt.

**Architecture:** New `subagents/shared/protocols/tools.py` holds all 20 tool functions (lifted verbatim from `protocol_builder/tools.py`). Two new subagent packages each wire a disjoint subset (creator: 8 tools, editor: 17 tools) with their own focused prompt. `chat_agent.py` swaps the registration. Two new AI capabilities (`protocol_creation`, `protocol_editing`) resolve through the existing `get_model()` chain.

**Tech Stack:** Python 3 / FastAPI / pydantic-ai 1.75 / subagents_pydantic_ai / pytest-asyncio. Worktree at `/home/wesuuu/Code/trellisbio/.claude/worktrees/td-0086-split-protocol-builder` — all commands run from that directory unless stated.

**Approved spec:** `docs/superpowers/specs/2026-05-11-td-0086-split-protocol-builder-design.md`

---

## File Map

**Create:**
- `backend/app/services/ai/subagents/shared/__init__.py`
- `backend/app/services/ai/subagents/shared/protocols/__init__.py`
- `backend/app/services/ai/subagents/shared/protocols/tools.py` (copy of `protocol_builder/tools.py`)
- `backend/app/services/ai/subagents/protocol_creator/__init__.py`
- `backend/app/services/ai/subagents/protocol_creator/config.py`
- `backend/app/services/ai/subagents/protocol_creator/prompt.md`
- `backend/app/services/ai/subagents/protocol_editor/__init__.py`
- `backend/app/services/ai/subagents/protocol_editor/config.py`
- `backend/app/services/ai/subagents/protocol_editor/prompt.md`
- `backend/tests/unit/test_subagents_protocol_creator.py`
- `backend/tests/unit/test_subagents_protocol_editor.py`

**Modify:**
- `backend/app/models/ai.py` — add 2 capabilities + 2 defaults
- `backend/app/core/config.py` — add 4 env fields + 1 context_window entry
- `backend/settings.example.yaml` — add 4 commented routing lines
- `backend/app/services/ai/subagents/__init__.py` — drop protocol_builder, add the two new packages
- `backend/app/services/ai/chat_agent.py` — swap subagent registration + cache key + model fetch
- `backend/app/services/ai/prompts/chat_agent.md` — split the protocol_builder dispatch bullet
- `backend/tests/unit/test_chat_agent_factory.py` — return values for the two new capabilities

**Untouched:**
- `backend/app/services/ai/subagents/protocol_builder/` — package stays on disk this cycle; deleted in a follow-up task.

---

## Task 1: Add the two new AI capabilities to the model registry

**Files:**
- Modify: `backend/app/models/ai.py`

- [ ] **Step 1: Add the capability names to `SUPPORTED_CAPABILITIES`**

Edit `backend/app/models/ai.py` lines 28–38. Replace:

```python
SUPPORTED_CAPABILITIES = (
    "vision",
    "text",
    "embedding",
    "doc_structure",
    "chat",
    "chat_subagent",
    "chat_summary",
    "protocol_generation",
    "template_convert",
)
```

with:

```python
SUPPORTED_CAPABILITIES = (
    "vision",
    "text",
    "embedding",
    "doc_structure",
    "chat",
    "chat_subagent",
    "chat_summary",
    "protocol_creation",
    "protocol_editing",
    "protocol_generation",
    "template_convert",
)
```

- [ ] **Step 2: Add default configs for the two new capabilities**

Edit `backend/app/models/ai.py`. Inside `DEFAULT_CONFIGS`, add two entries directly before the existing `"protocol_generation"` entry (around line 70):

```python
    "protocol_creation": {
        "provider": "ollama",
        "model_name": "gpt-oss:120b-cloud",
    },
    "protocol_editing": {
        "provider": "ollama",
        "model_name": "gpt-oss:120b-cloud",
    },
```

- [ ] **Step 3: Commit**

```bash
git add backend/app/models/ai.py
git -c commit.gpgsign=false commit -m "feat(td-0086): add protocol_creation/editing AI capabilities"
```

---

## Task 2: Add Settings env-var fields and context-window entry

**Files:**
- Modify: `backend/app/core/config.py`

- [ ] **Step 1: Add the four env-var fields to `Settings`**

Edit `backend/app/core/config.py` around line 106. After the existing `ai_template_convert_*` lines, add (keeping alphabetical-ish grouping with the surrounding capabilities):

```python
    ai_protocol_creation_provider: str = ""
    ai_protocol_creation_model: str = ""
    ai_protocol_editing_provider: str = ""
    ai_protocol_editing_model: str = ""
```

Place these immediately AFTER the existing line `ai_protocol_generation_model: str = ""` (so all `protocol_*` fields stay grouped). Final order in that block:

```python
    ai_protocol_generation_provider: str = ""
    ai_protocol_generation_model: str = ""
    ai_protocol_creation_provider: str = ""
    ai_protocol_creation_model: str = ""
    ai_protocol_editing_provider: str = ""
    ai_protocol_editing_model: str = ""
    ai_template_convert_provider: str = ""
    ai_template_convert_model: str = ""
```

- [ ] **Step 2: Add `gpt-oss:120b-cloud` to `context_window_defaults`**

`gpt-oss:120b-cloud` is not yet in the dict. Edit `backend/app/core/config.py` `context_window_defaults` (starts at line 128). Add this entry under the "Ollama / small models" group (gpt-oss reports a 128k context window per its model card):

```python
        "gpt-oss:120b-cloud": 131072,
```

Place it after `"deepseek-r1": 65536,` (around line 142) and before `"command-r": 131072,` so the grouping reads naturally.

- [ ] **Step 3: Commit**

```bash
git add backend/app/core/config.py
git -c commit.gpgsign=false commit -m "feat(td-0086): add settings fields for protocol_creation/editing and gpt-oss context window"
```

---

## Task 3: Add commented routing example to settings.example.yaml

**Files:**
- Modify: `backend/settings.example.yaml`

- [ ] **Step 1: Add four commented lines under "AI capability routing"**

Edit `backend/settings.example.yaml`. After the existing `ai_protocol_generation_model` line (line 68), insert:

```yaml
# ai_protocol_creation_provider: ollama
# ai_protocol_creation_model: gpt-oss:120b-cloud
# ai_protocol_editing_provider: ollama
# ai_protocol_editing_model: gpt-oss:120b-cloud
```

- [ ] **Step 2: Commit**

```bash
git add backend/settings.example.yaml
git -c commit.gpgsign=false commit -m "docs(td-0086): example settings for protocol_creation/editing routing"
```

---

## Task 4: Create the shared protocol tools module

**Files:**
- Create: `backend/app/services/ai/subagents/shared/__init__.py`
- Create: `backend/app/services/ai/subagents/shared/protocols/__init__.py`
- Create: `backend/app/services/ai/subagents/shared/protocols/tools.py`

- [ ] **Step 1: Create the `shared` package marker**

Create `backend/app/services/ai/subagents/shared/__init__.py` with one line:

```python
"""Shared building blocks reusable across subagents."""
```

- [ ] **Step 2: Create the `shared.protocols` package marker**

Create `backend/app/services/ai/subagents/shared/protocols/__init__.py` with:

```python
"""Tool functions shared by the protocol_creator and protocol_editor subagents."""

from app.services.ai.subagents.shared.protocols.tools import (
    add_protocol_role,
    add_protocol_step,
    create_draft,
    create_protocol,
    create_unit_op,
    elevate_unit_op_scope,
    get_protocol,
    list_projects,
    list_protocol_roles,
    list_protocols,
    list_unit_ops,
    remove_protocol_role,
    remove_protocol_step,
    reorder_protocol_steps,
    replace_step_unit_op,
    update_protocol_metadata,
    update_protocol_role,
    update_protocol_step,
    update_unit_op,
    validate_protocol,
)

__all__ = [
    "add_protocol_role",
    "add_protocol_step",
    "create_draft",
    "create_protocol",
    "create_unit_op",
    "elevate_unit_op_scope",
    "get_protocol",
    "list_projects",
    "list_protocol_roles",
    "list_protocols",
    "list_unit_ops",
    "remove_protocol_role",
    "remove_protocol_step",
    "reorder_protocol_steps",
    "replace_step_unit_op",
    "update_protocol_metadata",
    "update_protocol_role",
    "update_protocol_step",
    "update_unit_op",
    "validate_protocol",
]
```

- [ ] **Step 3: Copy `protocol_builder/tools.py` verbatim to `shared/protocols/tools.py`**

Run from the worktree root:

```bash
cp backend/app/services/ai/subagents/protocol_builder/tools.py \
   backend/app/services/ai/subagents/shared/protocols/tools.py
```

Then open `backend/app/services/ai/subagents/shared/protocols/tools.py` and update only the top docstring (line 1) from:

```python
"""Tools for the protocol_builder subagent.
```

to:

```python
"""Protocol-building tool functions shared by protocol_creator + protocol_editor.
```

No other edits — every imported symbol resolves the same way from this path.

- [ ] **Step 4: Verify the module imports cleanly**

Run from the worktree root with the backend venv active:

```bash
cd backend && source .venv/bin/activate && python -c "from app.services.ai.subagents.shared.protocols import tools; print(len([n for n in dir(tools) if not n.startswith('_')]))"
```

Expected: a small integer printed, no traceback. The exact number isn't asserted here (the next step uses tests).

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/ai/subagents/shared/
git -c commit.gpgsign=false commit -m "feat(td-0086): lift protocol tools into shared module"
```

---

## Task 5: Write failing test for protocol_creator

**Files:**
- Create: `backend/tests/unit/test_subagents_protocol_creator.py`

- [ ] **Step 1: Write the test file**

Create `backend/tests/unit/test_subagents_protocol_creator.py`:

```python
"""Tests for the protocol_creator subagent config."""

from app.services.ai.subagents import protocol_creator


EXPECTED_TOOL_NAMES = {
    "list_projects",
    "list_protocols",
    "get_protocol",
    "list_unit_ops",
    "list_protocol_roles",
    "create_unit_op",
    "create_protocol",
    "create_draft",
}


def test_protocol_creator_build_returns_subagent_config():
    config = protocol_creator.build("openai:gpt-4.1-mini")
    assert config.name == "protocol_creator"
    assert config.model == "openai:gpt-4.1-mini"
    assert config.instructions
    assert "protocol" in config.description.lower()


def test_protocol_creator_tool_set():
    config = protocol_creator.build("openai:gpt-4.1-mini")
    tool_names = {fn.__name__ for fn in config.agent_kwargs["tools"]}
    assert tool_names == EXPECTED_TOOL_NAMES, (
        f"Expected exactly {EXPECTED_TOOL_NAMES}, got {tool_names}"
    )
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
cd backend && source .venv/bin/activate && pytest tests/unit/test_subagents_protocol_creator.py -v
```

Expected: FAIL — `ImportError: cannot import name 'protocol_creator'` (or `AttributeError` on `protocol_creator`).

---

## Task 6: Implement the protocol_creator subagent

**Files:**
- Create: `backend/app/services/ai/subagents/protocol_creator/__init__.py`
- Create: `backend/app/services/ai/subagents/protocol_creator/config.py`
- Create: `backend/app/services/ai/subagents/protocol_creator/prompt.md`
- Modify: `backend/app/services/ai/subagents/__init__.py`

- [ ] **Step 1: Write the creator prompt**

Create `backend/app/services/ai/subagents/protocol_creator/prompt.md`. Write a focused prompt (not a slice of the old one). Use the content below verbatim:

```markdown
You are a protocol design specialist for biotech Process Development.

Your job: collaborate with the user to design and create a NEW Protocol
record (and any new custom unit ops it needs). You do not edit
existing protocols — if the user wants to change a protocol they
already have, defer back to the parent agent so it can dispatch
`protocol_editor` instead.

## Workflow

1. **Gather requirements**: process type, scale, base document if any.
   Ask ONE question per turn. Wait for the answer before continuing.

2. **Scan the catalog**: call `list_unit_ops` to see what already
   exists. Use it internally — do NOT show the raw list to the user.

3. **Propose steps one at a time.** After each, wait for user
   confirmation in the parent conversation. Do not propose step N+1
   until step N is confirmed.

4. **Pick the project.** Once steps are confirmed, work out which
   project the protocol belongs in:
   - Call `list_projects` to see what the user actually has. NEVER
     fabricate a project name from training data or domain knowledge.
   - If the user named a project, find the closest match. If
     unambiguous, use it. If two or more match, ask the user to
     disambiguate using the candidate names verbatim.
   - If the user didn't name one, list the projects in plain language
     ("You have N projects: A, B, C — which one?") and ask.
   - If `list_projects` returns zero, tell the user they need to
     create a project first in the Projects tab and stop.

5. **Create the protocol.** Call `create_protocol` with the structured
   `steps` list. Each step MUST include:
   - `name` — display name for the step
   - `unit_op_name` — name from the catalog if matched, else a new
     descriptive name
   - `duration_min` — your best estimate based on the discussion
   - `description` — full instructional text the technician will
     follow. Never leave blank.
   - `category` — specific category like "Media Prep", "Cell Culture",
     "Buffer Prep". Avoid "General" unless truly nothing else fits.
   - `params` — parameter values the user mentioned, keyed by name

6. **Validate immediately.** Call `validate_protocol(protocol_id)` —
   wait, validation is in the editor's surface. You do NOT have
   `validate_protocol`. After `create_protocol` returns, your job is
   done; the parent agent will dispatch `protocol_editor` to handle
   any post-creation fixes.

   If `create_protocol` itself returns `ok=false`, surface the error
   to the user verbatim and ask the targeted question needed to
   retry.

## Creating custom unit ops

**Strongly prefer using an existing unit op from `list_unit_ops`.**
Only call `create_unit_op` when the user explicitly asks for a new
one OR no existing op fits even loosely.

When you do call `create_unit_op`, it MUST include all of:
- A clear, instructional `description` (not empty, not a placeholder).
- A non-empty `param_schema` in JSON Schema form covering the
  parameters a scientist would set per run. Example:
  ```json
  {
    "type": "object",
    "properties": {
      "volume_L":    {"type": "number", "title": "Volume (L)",  "default": 10},
      "ph":          {"type": "number", "title": "pH",          "default": 7.4},
      "buffer_name": {"type": "string", "title": "Buffer Name", "default": "PBS"}
    }
  }
  ```
- A specific `category` — not "General" unless truly nothing else fits.

Never call `create_unit_op` with `param_schema={}` and an empty
description. If you genuinely don't know what parameters belong on
the op, ask the user one targeted question instead of creating a
hollow record.

## Drafts

`create_draft(protocol_id)` is on your tool list because creation
sometimes auto-opens a draft (e.g. when the user asks for a brand-new
protocol to immediately enter edit mode). You may call it after a
successful `create_protocol` if the user wants to keep iterating; the
parent agent will then dispatch `protocol_editor` for the actual
edits.

## End of turn

Once `create_protocol` returns `ok=true`, include a markdown link to
the new protocol in your final reply so the user can jump straight
to it: `[Protocol Name](/protocols/<protocol_id>)`. Drop it
naturally into the summary.

**Never claim a creation you didn't actually execute via a tool call.**
Your final reply may only describe records that correspond to a
successful tool return *this turn*.
```

- [ ] **Step 2: Write the creator config**

Create `backend/app/services/ai/subagents/protocol_creator/config.py`:

```python
"""Config builder for the protocol_creator subagent."""

from __future__ import annotations

from pathlib import Path

from subagents_pydantic_ai import SubAgentConfig

from app.services.ai.cache_settings import CHAT_AGENT_MODEL_SETTINGS
from app.services.ai.subagents.shared.protocols.tools import (
    create_draft,
    create_protocol,
    create_unit_op,
    get_protocol,
    list_projects,
    list_protocol_roles,
    list_protocols,
    list_unit_ops,
)

_PROMPT_PATH = Path(__file__).parent / "prompt.md"


def build(model: str) -> SubAgentConfig:
    """Return a SubAgentConfig for the protocol_creator subagent.

    Args:
        model: The model string to use (e.g. ``"ollama:gpt-oss:120b-cloud"``).
    """
    instructions = _PROMPT_PATH.read_text(encoding="utf-8")

    return SubAgentConfig(
        name="protocol_creator",
        description=(
            "Collaborates with the user to design and create a NEW Protocol "
            "record (and any new custom unit ops it needs). Dispatch when "
            "the user wants to build a protocol from scratch or define a "
            "new custom unit op. Does NOT modify existing protocols — "
            "dispatch protocol_editor for that."
        ),
        instructions=instructions,
        model=model,
        typically_needs_context=True,
        agent_kwargs={
            "model_settings": CHAT_AGENT_MODEL_SETTINGS,
            "tools": [
                # Reads
                list_projects,
                list_protocols,
                get_protocol,
                list_unit_ops,
                list_protocol_roles,
                # Creation
                create_unit_op,
                create_protocol,
                # Draft lifecycle
                create_draft,
            ],
        },
    )
```

- [ ] **Step 3: Write the package marker**

Create `backend/app/services/ai/subagents/protocol_creator/__init__.py`:

```python
"""protocol_creator subagent — new protocol + new unit op design."""

from app.services.ai.subagents.protocol_creator.config import build

__all__ = ["build"]
```

- [ ] **Step 4: Register the new package in the subagent registry**

Edit `backend/app/services/ai/subagents/__init__.py`. Replace its full contents with:

```python
"""Chat agent subagent registry."""

from . import (
    protocol_builder,  # legacy — unregistered in chat_agent.py but kept on disk this cycle
    protocol_creator,
    research_library,
    run_planner,
)

__all__ = [
    "protocol_builder",
    "protocol_creator",
    "research_library",
    "run_planner",
]
```

`protocol_editor` is added in Task 8.

- [ ] **Step 5: Run the test to verify it passes**

```bash
cd backend && source .venv/bin/activate && pytest tests/unit/test_subagents_protocol_creator.py -v
```

Expected: 2 tests PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/ai/subagents/protocol_creator/ \
        backend/app/services/ai/subagents/__init__.py \
        backend/tests/unit/test_subagents_protocol_creator.py
git -c commit.gpgsign=false commit -m "feat(td-0086): add protocol_creator subagent"
```

---

## Task 7: Write failing test for protocol_editor

**Files:**
- Create: `backend/tests/unit/test_subagents_protocol_editor.py`

- [ ] **Step 1: Write the test file**

Create `backend/tests/unit/test_subagents_protocol_editor.py`:

```python
"""Tests for the protocol_editor subagent config."""

from app.services.ai.subagents import protocol_editor


EXPECTED_TOOL_NAMES = {
    # Reads
    "list_projects",
    "list_protocols",
    "get_protocol",
    "list_unit_ops",
    "list_protocol_roles",
    # Validation
    "validate_protocol",
    # Metadata
    "update_protocol_metadata",
    # Step mutations
    "add_protocol_step",
    "update_protocol_step",
    "remove_protocol_step",
    "reorder_protocol_steps",
    "replace_step_unit_op",
    # Role mutations
    "add_protocol_role",
    "update_protocol_role",
    "remove_protocol_role",
    # Unit op mutations
    "update_unit_op",
    "elevate_unit_op_scope",
}


def test_protocol_editor_build_returns_subagent_config():
    config = protocol_editor.build("openai:gpt-4.1-mini")
    assert config.name == "protocol_editor"
    assert config.model == "openai:gpt-4.1-mini"
    assert config.instructions
    assert "protocol" in config.description.lower()


def test_protocol_editor_tool_set():
    config = protocol_editor.build("openai:gpt-4.1-mini")
    tool_names = {fn.__name__ for fn in config.agent_kwargs["tools"]}
    assert tool_names == EXPECTED_TOOL_NAMES, (
        f"Expected exactly {EXPECTED_TOOL_NAMES}, got {tool_names}"
    )
    assert len(tool_names) == 17
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
cd backend && source .venv/bin/activate && pytest tests/unit/test_subagents_protocol_editor.py -v
```

Expected: FAIL — `ImportError: cannot import name 'protocol_editor'`.

---

## Task 8: Implement the protocol_editor subagent

**Files:**
- Create: `backend/app/services/ai/subagents/protocol_editor/__init__.py`
- Create: `backend/app/services/ai/subagents/protocol_editor/config.py`
- Create: `backend/app/services/ai/subagents/protocol_editor/prompt.md`
- Modify: `backend/app/services/ai/subagents/__init__.py`

- [ ] **Step 1: Write the editor prompt**

Create `backend/app/services/ai/subagents/protocol_editor/prompt.md` with the content below verbatim:

````markdown
You are a protocol editor for biotech Process Development.

Your job: modify an EXISTING Protocol record per the user's request —
step mutations, role changes, metadata, custom-unit-op edits, and
scope elevation. You do not create new protocols from scratch; if the
user wants a brand-new protocol, defer back to the parent agent so it
can dispatch `protocol_creator` instead.

## Workflow for every request

1. **Locate the protocol.** Use `list_protocols` to find candidates by
   name + project. Don't fabricate ids — show options if multiple
   match.

2. **Read current state.** Call `get_protocol(protocol_id)` before any
   mutation. The returned `step_count`, `roles`, and `graph` are your
   ground truth.

3. **Mutating tools target DRAFT graph state.** If a protocol's status
   is `APPROVED`, every mutating tool returns `ok=false` with `summary`
   starting *"Protocol is published — call create_draft(protocol_id)…"*.
   Fix it yourself in the same turn:
   1. There is no `create_draft` on your surface — that lives on the
      creator. If you hit the "published" error, tell the user the
      protocol must be drafted first via the editor UI (or by the
      parent dispatching the creator) and stop. Do not pretend to have
      drafted it.

   If status is `PENDING_APPROVAL` or `ARCHIVED`, mutations are
   blocked — relay the error to the user and stop.

## Available mutations (DRAFT-only)

- `update_protocol_metadata(protocol_id, name?, description?)`
- `add_protocol_step(protocol_id, name, unit_op_name, ...,
  after_step_index?, role_id?)` — appends if `after_step_index` is
  omitted.
- `update_protocol_step(protocol_id, step_index, description?,
  category?, param_schema?, params?, role_id?)`
- `remove_protocol_step(protocol_id, step_index)`
- `reorder_protocol_steps(protocol_id, ordered_step_indices)` —
  `ordered_step_indices` MUST be a permutation of `0..N-1`.
- `replace_step_unit_op(protocol_id, step_index, new_unit_op_name)` —
  swaps the underlying unit op; the step's display label is preserved.

`step_index` counts unit-op steps only (Process Start is excluded);
the first step is index 0.

## Roles

Tools:
- `list_protocol_roles(protocol_id)`
- `add_protocol_role(protocol_id, name, color?, sort_order?)`
- `update_protocol_role(role_id, name?, color?, sort_order?)`
- `remove_protocol_role(role_id)`

To build out a role's chain of steps: call `add_protocol_role` first,
then `add_protocol_step(..., role_id=<new_role_id>)` per step. The new
nodes will be assigned to that role's lane via `parentId`.

**Recognize role triggers proactively.** Whenever the user introduces
a step performed by a *different* operator/person/team than the
current chain (phrases like "another person", "someone else", "QA
reviewer", "the night-shift tech", "have [name] do this"), assume a
new role is required:

1. `list_protocol_roles(protocol_id)` to see what already exists.
2. If no matching role, call `add_protocol_role` with a sensible name
   derived from the user's wording before creating the step.
3. Then call `add_protocol_step(..., role_id=<role_id>)`.

Do not silently drop the role hint and append the step to the
existing chain — the user expects a visible lane in the editor.

**Role-ID hygiene (do not skip).** The only legitimate source of a
`role_id` is the `id` field returned by `list_protocol_roles` or
`add_protocol_role` *in the current conversation*. Never invent a
UUID, copy one from another protocol, or assume "a role named X
exists on this protocol." Concretely:

1. Before passing `role_id=` to `add_protocol_step` or
   `update_protocol_step`, call `list_protocol_roles(protocol_id)`
   this turn and confirm the role you want is in the returned list.
2. If the user names a role that isn't on the protocol yet, call
   `add_protocol_role` first, then use the `id` from that tool's
   return value.
3. The service rejects unknown role IDs (`Role <uuid> does not exist
   on protocol <uuid>`). If you see that error, you fabricated the id
   — go back to step 1.

Never report a role reassignment as successful without seeing a
matching `update_protocol_step`/`add_protocol_step` return with the
right `role_id` on the same turn.

## Validate after edits

`validate_protocol(protocol_id)` is your safety net. After any
sequence of mutations — adding/removing/updating steps,
adding/updating/removing roles, swapping unit ops — run
`validate_protocol` once before reporting back. Do not rely on
individual tool returns.

The validator reports:
- `missing_lane_node` — a ProtocolRole row exists but its swimLane is
  not in the graph. Fix by re-adding the role or removing the orphan
  role.
- `orphaned_lane_node` — a swimLane node has no matching role.
  Recreate the role.
- `orphaned_parent_id` — a step's `parentId` points at a lane that
  doesn't exist. Fix:
  `update_protocol_step(protocol_id, step_index, role_id=<real_role_id>)`.
- `empty_lane` — a role/swimLane exists but no steps are assigned.
  Assign a step, ask the user which steps belong there, or remove the
  role with `remove_protocol_role(role_id)`.
- `child_outside_lane` — a step's lane-relative position renders it
  outside its parent swimlane. Fix by re-issuing the role assignment
  via `update_protocol_step(protocol_id, step_index,
  role_id=<role_id>)` — that call recomputes the slot and grows the
  lane.
- `overlapping_nodes` — two steps in the same lane have intersecting
  bounding boxes. Re-trigger placement by calling `update_protocol_step`
  with the same `role_id` on the offending step.
- `step_overlaps_lane` — a top-level step overlaps a lane. Assign it
  to that role via `update_protocol_step(..., role_id=<role_id>)`.
- `insufficient_node_spacing` — sibling steps closer than 10px. Same
  fix as `overlapping_nodes`.

**Auto-fix loop.** Fix what you can without changing the user's
intent. Re-validate after each fix. Stop only when issues are zero or
the remaining ones need user input you cannot infer.

## Layout discipline — never set positions by hand

Layout is owned by the tools, not by you:

- `add_protocol_step` with a `role_id` places the new step at the
  next free lane-relative slot and grows the lane to fit. Without
  `role_id` it falls back to a default top-level slot.
- `update_protocol_step` with a different `role_id` re-places the
  step inside the new lane at a fresh slot.
- You never have a tool to write `position` directly — that's
  deliberate. Don't ask for one.

Practical rules:

1. When the user mentions a different operator/role for a step,
   create the role FIRST via `add_protocol_role`, then create the
   step with `role_id` set.
2. When reassigning an existing step to a role, always use
   `update_protocol_step(protocol_id, step_index, role_id=<role_id>)`.
3. If `validate_protocol` reports a layout warning, the fix is almost
   always a single `update_protocol_step` call with the intended
   `role_id`. Re-validate after.

## Unit op editing and scope ladder

Unit op definitions live at three scopes:
- **global** — built-in catalog (organization_id NULL, project_id
  NULL)
- **org** — org-wide custom op (organization_id set, project_id NULL)
- **project** — project-only custom op (both set)

Scope ladder for elevation: project → org. Tools:
- `update_unit_op(unit_op_id, name?, category?, description?,
  param_schema?, result_schema?)` — org-scoped updates require
  org-admin (the platform decides). Library-override rows refuse.
- `elevate_unit_op_scope(unit_op_id)` — promotes project → org.
  Org-admin only. Refuses if op is already org/global, is a
  library override, or if an org-scoped op with the same name
  exists.

If a tool returns `ok=false` because the user lacks admin rights,
surface that politely and suggest they ask an org admin.

## End-of-turn checklist (MANDATORY)

Before sending your final reply on any turn that called a mutation
tool, you MUST:

1. Call `validate_protocol(protocol_id)` exactly once.
2. If it returns issues, run the auto-fix loop and re-validate.
   Repeat until clean or you genuinely need user input.
3. Include a markdown link to the protocol in your final reply so the
   user can jump straight to it: `[Protocol Name](/protocols/<id>)`.
4. Only then write the final reply.

**Never claim a change you did not actually execute via a tool call.**
Your final reply may only describe edits that correspond to a
successful tool return *this turn*. If you intended a change but the
call didn't happen or returned `ok=false`, do not say it succeeded.
Re-read the tool returns above the line before drafting the summary;
if the change isn't there, either call the missing tool now or
correct the summary to match reality.
````

- [ ] **Step 2: Write the editor config**

Create `backend/app/services/ai/subagents/protocol_editor/config.py`:

```python
"""Config builder for the protocol_editor subagent."""

from __future__ import annotations

from pathlib import Path

from subagents_pydantic_ai import SubAgentConfig

from app.services.ai.cache_settings import CHAT_AGENT_MODEL_SETTINGS
from app.services.ai.subagents.shared.protocols.tools import (
    add_protocol_role,
    add_protocol_step,
    elevate_unit_op_scope,
    get_protocol,
    list_projects,
    list_protocol_roles,
    list_protocols,
    list_unit_ops,
    remove_protocol_role,
    remove_protocol_step,
    reorder_protocol_steps,
    replace_step_unit_op,
    update_protocol_metadata,
    update_protocol_role,
    update_protocol_step,
    update_unit_op,
    validate_protocol,
)

_PROMPT_PATH = Path(__file__).parent / "prompt.md"


def build(model: str) -> SubAgentConfig:
    """Return a SubAgentConfig for the protocol_editor subagent.

    Args:
        model: The model string to use (e.g. ``"ollama:gpt-oss:120b-cloud"``).
    """
    instructions = _PROMPT_PATH.read_text(encoding="utf-8")

    return SubAgentConfig(
        name="protocol_editor",
        description=(
            "Modifies an existing draft Protocol — step add/update/remove/"
            "reorder, role changes, metadata, custom-unit-op edits, and "
            "scope elevation. Dispatch when the user wants to change a "
            "protocol they already have. Does NOT create new protocols — "
            "dispatch protocol_creator for that."
        ),
        instructions=instructions,
        model=model,
        typically_needs_context=True,
        agent_kwargs={
            "model_settings": CHAT_AGENT_MODEL_SETTINGS,
            "tools": [
                # Reads
                list_projects,
                list_protocols,
                get_protocol,
                list_unit_ops,
                list_protocol_roles,
                # Validation
                validate_protocol,
                # Metadata
                update_protocol_metadata,
                # Step mutations
                add_protocol_step,
                update_protocol_step,
                remove_protocol_step,
                reorder_protocol_steps,
                replace_step_unit_op,
                # Role mutations
                add_protocol_role,
                update_protocol_role,
                remove_protocol_role,
                # Unit op mutations
                update_unit_op,
                elevate_unit_op_scope,
            ],
        },
    )
```

- [ ] **Step 3: Write the package marker**

Create `backend/app/services/ai/subagents/protocol_editor/__init__.py`:

```python
"""protocol_editor subagent — mutate existing protocols, roles, and unit ops."""

from app.services.ai.subagents.protocol_editor.config import build

__all__ = ["build"]
```

- [ ] **Step 4: Register the new package in the subagent registry**

Edit `backend/app/services/ai/subagents/__init__.py`. Replace its full contents with:

```python
"""Chat agent subagent registry."""

from . import (
    protocol_builder,  # legacy — unregistered in chat_agent.py but kept on disk this cycle
    protocol_creator,
    protocol_editor,
    research_library,
    run_planner,
)

__all__ = [
    "protocol_builder",
    "protocol_creator",
    "protocol_editor",
    "research_library",
    "run_planner",
]
```

- [ ] **Step 5: Run the editor test to verify it passes**

```bash
cd backend && source .venv/bin/activate && pytest tests/unit/test_subagents_protocol_editor.py -v
```

Expected: 2 tests PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/ai/subagents/protocol_editor/ \
        backend/app/services/ai/subagents/__init__.py \
        backend/tests/unit/test_subagents_protocol_editor.py
git -c commit.gpgsign=false commit -m "feat(td-0086): add protocol_editor subagent"
```

---

## Task 9: Update chat_agent_factory test to cover the new capabilities

**Files:**
- Modify: `backend/tests/unit/test_chat_agent_factory.py`

- [ ] **Step 1: Update `fake_get_model` to return values for the new capabilities**

Edit `backend/tests/unit/test_chat_agent_factory.py`. Replace the `fake_get_model` definition (lines 22–27) with:

```python
    async def fake_get_model(cap, db_, org_id=None):
        return {
            "chat": fake_chat_model,
            "chat_subagent": fake_subagent_model,
            "chat_summary": fake_summary_model,
            "protocol_creation": fake_subagent_model,
            "protocol_editing": fake_subagent_model,
        }[cap]
```

- [ ] **Step 2: Run the test to confirm it still passes** (the function-under-test hasn't been updated yet, so it should not yet call the new capabilities — test must still pass against the current `build_chat_agent`)

```bash
cd backend && source .venv/bin/activate && pytest tests/unit/test_chat_agent_factory.py -v
```

Expected: PASS. The extra dict keys don't break anything — they only matter once `build_chat_agent` is updated in Task 10.

- [ ] **Step 3: Commit**

```bash
git add backend/tests/unit/test_chat_agent_factory.py
git -c commit.gpgsign=false commit -m "test(td-0086): cover protocol_creation/editing in chat_agent_factory test"
```

---

## Task 10: Wire chat_agent.py to the new subagents

**Files:**
- Modify: `backend/app/services/ai/chat_agent.py`

- [ ] **Step 1: Update imports**

Edit `backend/app/services/ai/chat_agent.py` lines 23–24. Replace:

```python
from app.services.ai.subagents import (protocol_builder, research_library,
                                       run_planner)
```

with:

```python
from app.services.ai.subagents import (
    protocol_creator,
    protocol_editor,
    research_library,
    run_planner,
)
```

(`protocol_builder` is unregistered; the package stays on disk only for the cycle.)

- [ ] **Step 2: Expand `_cache_key` to include the new model strings**

Edit `chat_agent.py` lines 52–63. Replace the existing `_cache_key`:

```python
def _cache_key(
    chat_model: Any,
    subagent_model: Any,
    summary_model: Any,
    context_window: int,
) -> tuple[str, ...]:
    return (
        str(chat_model),
        str(subagent_model),
        str(summary_model),
        str(context_window),
    )
```

with:

```python
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
```

- [ ] **Step 3: Fetch the new models and register the new subagents**

Edit `chat_agent.py` `build_chat_agent` (lines 105–165). Replace the body that fetches models and builds subagents.

Before, lines 117–130:

```python
    chat_model = await get_model("chat", db, org_id=org_id)
    subagent_model = await get_model("chat_subagent", db, org_id=org_id)
    summary_model = await get_model("chat_summary", db, org_id=org_id)
    context_window = await get_context_window("chat", db, org_id=org_id)

    key = _cache_key(chat_model, subagent_model, summary_model, context_window)

    if key not in _AGENT_CACHE:
        subagents = [
            research_library.build(subagent_model),
            protocol_builder.build(subagent_model),
            run_planner.build(subagent_model),
        ]
```

After:

```python
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
        ]
```

- [ ] **Step 4: Run the factory test**

```bash
cd backend && source .venv/bin/activate && pytest tests/unit/test_chat_agent_factory.py -v
```

Expected: PASS. The test's `fake_get_model` now returns values for the new capabilities, and `_cache_key` now consumes them.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/ai/chat_agent.py
git -c commit.gpgsign=false commit -m "feat(td-0086): wire protocol_creator/editor into chat_agent"
```

---

## Task 11: Update the parent chat agent's dispatch prompt

**Files:**
- Modify: `backend/app/services/ai/prompts/chat_agent.md`

- [ ] **Step 1: Split the protocol_builder bullet into two**

Edit `backend/app/services/ai/prompts/chat_agent.md`. Replace line 5:

```markdown
- **protocol_builder** — multi-turn collaboration to design, build, list, inspect, or edit Protocols and their roles, plus manage custom unit-op definitions
```

with:

```markdown
- **protocol_creator** — design and create a NEW protocol from a user brief (and any new custom unit ops it needs); does not modify existing protocols
- **protocol_editor** — modify an existing protocol's steps, roles, metadata, or unit-op definitions; lists, inspects, validates, and mutates draft protocols
```

- [ ] **Step 2: Replace the ROUTING dispatch line for protocols**

Edit the same file. Replace line 19:

```markdown
- User wants to create, list, view, or edit a protocol (steps, roles, metadata) or a custom unit op? → `task("protocol_builder", ...)`
```

with:

```markdown
- User wants to CREATE a new protocol or define a new custom unit op? → `task("protocol_creator", ...)`
- User wants to view, list, validate, or modify an EXISTING protocol (steps, roles, metadata) or edit/elevate an existing custom unit op? → `task("protocol_editor", ...)`
```

- [ ] **Step 3: Update the line about subagents the parent orchestrates**

Edit the same file. Replace line 3:

```markdown
You orchestrate three specialists via the `task` tool:
```

with:

```markdown
You orchestrate four specialists via the `task` tool:
```

- [ ] **Step 4: Commit**

```bash
git add backend/app/services/ai/prompts/chat_agent.md
git -c commit.gpgsign=false commit -m "feat(td-0086): split protocol dispatch in chat_agent prompt"
```

---

## Task 12: Run the full backend test suite

- [ ] **Step 1: Run pytest**

```bash
cd backend && source .venv/bin/activate && pytest -x --tb=short
```

Expected: every test passes. `-x` stops at the first failure so the output is easy to scan. If any test fails, do NOT proceed — fix the failure first.

Likely failure modes to look for:
- A test imports `protocol_builder` and asserts on its registration in `chat_agent.py`. If that exists, update it to assert on the new pair.
- A test patches `get_model` for `chat_subagent` and never returns a value for `protocol_creation` / `protocol_editing`. Update the patch to cover the new capabilities.

- [ ] **Step 2: If any failure, fix it in place and re-run**

For each failure: read the traceback, edit the test or the code, re-run `pytest -x --tb=short`. Loop until clean.

- [ ] **Step 3: Commit (only if Step 2 actually edited anything)**

```bash
git add <whatever was changed>
git -c commit.gpgsign=false commit -m "test(td-0086): align <test name> with split subagents"
```

---

## Task 13: Sanity-check chat dispatch against a live dev server

**Files:** none modified — pure verification.

- [ ] **Step 1: Start the backend dev server on the worktree's alternate port**

In a new terminal pane (do NOT use the foreground in this session — leave it running):

```bash
cd backend && source .venv/bin/activate && uvicorn app.main:app --reload --port 8010
```

Confirm in the logs that it boots without `ImportError` or `KeyError` on `protocol_creation` / `protocol_editing`. If you see one of those errors, fix and reboot.

- [ ] **Step 2: Manual chat sanity-check (creator path)**

Send a chat message that should dispatch the creator. Either through the frontend (logged in, /chat page) or via curl. The smoke test is that the user prompt "create a new protocol for buffer prep with a single mix step" results in tool calls `list_unit_ops`, `list_projects`, `create_protocol` (which all live on the creator's surface) — not on the editor's.

To inspect: tail the backend logs and confirm the dispatched subagent's `name` is `protocol_creator`.

- [ ] **Step 3: Manual chat sanity-check (editor path)**

Send a prompt that targets an existing protocol — e.g. "change step 2's duration to 30 minutes in protocol <name>". Confirm the dispatched subagent is `protocol_editor` and that one of the editor-only tools (`update_protocol_step`) is invoked.

- [ ] **Step 4: Stop the dev server**

Ctrl-C the terminal where uvicorn is running.

- [ ] **Step 5: No commit** — this task only verifies behavior.

If either dispatch routes wrong, the most likely cause is the prompt edit in Task 11. Revisit the bullets and the routing heuristic.

---

## Task 14: Refresh project rules

**Files:**
- Modify (only if stale content found): `.claude/rules/backend-ai.md`, `CLAUDE.md`

- [ ] **Step 1: Audit `.claude/rules/backend-ai.md` for stale `protocol_builder` references**

Run from the worktree root:

```bash
grep -n "protocol_builder" .claude/rules/backend-ai.md
```

If matches exist that imply `protocol_builder` is the only or canonical subagent (rather than just an example of the file layout):
- Update the package-layout illustration to also show `protocol_creator/`, `protocol_editor/`, and `shared/protocols/`.
- The example tree references `protocol_builder/` — keep that as an example OR swap to one of the new packages; either is fine. Goal: the file does not lie about which subagents are wired.

- [ ] **Step 2: Audit `CLAUDE.md` for stale references**

```bash
grep -n "protocol_builder" CLAUDE.md
```

If matches exist, update or remove per the rules-refresh guidance in `/implement-task` (timeless present, prefer rewriting over appending).

- [ ] **Step 3: If nothing was edited in Steps 1–2, skip this commit. Otherwise:**

```bash
git add .claude/rules/backend-ai.md CLAUDE.md 2>/dev/null || true
git -c commit.gpgsign=false commit -m "docs(td-0086): refresh rules for subagent split"
```

---

## Task 15: Final pytest + leave for user verification

- [ ] **Step 1: One more full test run**

```bash
cd backend && source .venv/bin/activate && pytest --tb=short
```

Expected: green across the board.

- [ ] **Step 2: Summarize for the user**

Post a message in chat enumerating:
- Files created (5 new package files, 2 new test files, 1 design + 1 plan).
- Files modified (`models/ai.py`, `core/config.py`, `settings.example.yaml`, `subagents/__init__.py`, `chat_agent.py`, `prompts/chat_agent.md`, `tests/unit/test_chat_agent_factory.py`, rules files if touched).
- Tools per subagent (8 / 17).
- Defaults wired to `ollama` / `gpt-oss:120b-cloud`.
- Confirmation that `protocol_builder/` package is still on disk, unregistered, awaiting follow-up deletion.

Ask the user to verify and confirm before closing TD-0086.

---

## Out of Scope (do NOT do during this plan)

- Deleting `backend/app/services/ai/subagents/protocol_builder/` — that's a separate follow-up task created after benchmarks confirm parity.
- Tuning either default below `gpt-oss:120b-cloud` — benchmark-driven follow-up.
- Adding or changing the behavior of any tool function — the shared module is a verbatim copy.
- Frontend changes — none required; chat dispatch is opaque to the UI.
- Migration scripts — no schema or data changes.
