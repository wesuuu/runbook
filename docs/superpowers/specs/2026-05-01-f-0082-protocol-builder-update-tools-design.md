# F-0082 — Protocol Builder Subagent Update Tools

## Goal

Expand the `protocol_builder` chat subagent so it can update existing protocols, manage protocol roles, and modify/elevate custom unit ops. Today it can only create new protocols and patch a single step's metadata.

## Scope guardrail (Option A)

**Mutating tools operate on DRAFT-status protocols only.** If a protocol is `APPROVED` or `PENDING_APPROVAL`, mutating tools return a clean error: *"Protocol is published — create a draft in the protocol editor first."* Draft-version materialization, the "edit existing draft vs. start a new draft" decision flow, and arbitrary edge re-wiring (`update_protocol_edges`) are deferred. No role-control gating yet — project EDIT permission is the only check.

This drops the `NeedsTargetDecision` pattern entirely and avoids touching the inline draft logic in `api/endpoints/protocols.py`.

## New tools (all in `subagents/protocol_builder/tools.py`)

| Tool | Mutates? | Service delegate |
|---|---|---|
| `list_protocols` | no | `services/protocols/lookup.py:list_protocols` |
| `get_protocol` | no | `services/protocols/lookup.py:get_protocol_full` |
| `update_protocol_metadata` | yes (DRAFT-only) | `services/protocols/creation.py:update_protocol_metadata` |
| `add_protocol_step` | yes (DRAFT-only) | `services/protocols/graph.py:add_step` |
| `remove_protocol_step` | yes (DRAFT-only) | `services/protocols/graph.py:remove_step` |
| `reorder_protocol_steps` | yes (DRAFT-only) | `services/protocols/graph.py:reorder_steps` |
| `replace_step_unit_op` | yes (DRAFT-only) | `services/protocols/graph.py:replace_step_unit_op` |
| `list_protocol_roles` | no | `services/protocols/roles.py:list_roles` |
| `add_protocol_role` | yes (DRAFT-only) | `services/protocols/roles.py:add_role` |
| `update_protocol_role` | yes (DRAFT-only) | `services/protocols/roles.py:update_role` |
| `remove_protocol_role` | yes (DRAFT-only) | `services/protocols/roles.py:remove_role` |
| `update_unit_op` | yes | `services/protocols/unit_ops.py:update_unit_op_definition` |
| `elevate_unit_op_scope` | yes (admin for org) | `services/protocols/unit_ops.py:elevate_unit_op_scope` |

The existing `update_protocol_step` gains the same DRAFT-only guard and an optional `role_id` parameter (sets the node's `parentId`).

`add_protocol_step` also accepts optional `role_id` so the agent can build out a role's step chain in one call.

## Service-layer additions

### `services/protocols/lookup.py` (new)

```python
async def list_protocols(
    db, *, user_id, org_id, project_id: UUID | None = None
) -> list[ProtocolListItem]
async def get_protocol_full(
    db, *, user_id, protocol_id: UUID
) -> ProtocolFull
```

`ProtocolListItem` carries id, name, project name, status, version_number, has_draft (bool — informational only). `ProtocolFull` carries metadata + the full graph + roles. Both filter by what the user has READ permission on. No DB-level "draft of v(N+1) exists" probe in the read path — `has_draft` is a single grouped subquery.

### `services/protocols/graph.py` (new)

Pure graph mutations. Each function is a thin wrapper over `_require_draft_and_edit_perm(protocol, user_id)` plus a deterministic transform of `protocol.graph["nodes"]` and `protocol.graph["edges"]`.

```python
async def add_step(
    db, *, user_id, protocol_id, name, unit_op_name,
    duration_min=30, description="", category="General",
    params=None, after_step_index: int | None = None,
    role_id: UUID | None = None,
) -> Protocol
async def remove_step(db, *, user_id, protocol_id, step_index) -> Protocol
async def reorder_steps(
    db, *, user_id, protocol_id, ordered_step_indices: list[int]
) -> Protocol
async def replace_step_unit_op(
    db, *, user_id, protocol_id, step_index, new_unit_op_name
) -> Protocol
```

Step indices reference unit-op nodes only (Process Start excluded), 0-based. Edge re-wiring on add/remove/reorder maintains the linear chain (`prev → new → next`); arbitrary DAG topologies aren't reshaped — the linear chain is the only structural mode supported here. `_require_draft_and_edit_perm` raises `ValueError("Protocol is published — create a draft first.")` on `APPROVED`/`PENDING_APPROVAL`.

### `services/protocols/creation.py` (extend)

```python
async def update_protocol_metadata(
    db, *, user_id, protocol_id,
    name: str | None = None, description: str | None = None,
) -> Protocol
```

DRAFT-only. Same permission helper.

### `services/protocols/roles.py` (new)

```python
async def list_roles(db, *, user_id, protocol_id) -> list[ProtocolRole]
async def add_role(db, *, user_id, protocol_id, name, color="#94a3b8", sort_order=None) -> ProtocolRole
async def update_role(db, *, user_id, role_id, name=None, color=None, sort_order=None) -> ProtocolRole
async def remove_role(db, *, user_id, role_id) -> None
```

`add_role`'s default `sort_order` is `max(existing) + 1`. Mutating ops require DRAFT status on the parent protocol + project EDIT.

### `services/protocols/unit_ops.py` (extend)

```python
async def update_unit_op_definition(
    db, *, user_id, org_id, is_org_admin, unit_op_id,
    name=None, category=None, description=None,
    param_schema=None, result_schema=None,
) -> UnitOpDefinition

async def elevate_unit_op_scope(
    db, *, user_id, org_id, is_org_admin, unit_op_id,
) -> UnitOpDefinition
```

Permission rules mirror `create_unit_op_definition`:
- **update** of an org-scoped op requires `is_org_admin`. Project-scoped requires project EDIT.
- **elevate** is project → org only. Requires `is_org_admin`. Sets `project_id=NULL`. Refuses if op is already org-scoped or globally scoped. Name-collision check against existing org-scoped ops with the same name.
- Both refuse on library-override rows (`source_library_slug` set) with a clear error — those are managed by the library-subscription flow.

## Tool-layer conventions

- Each tool is ≤30 lines: arg coercion (`UUID(str)`), service call, `tool_calls.append(...)`, return `@dataclass`.
- Result dataclasses include a `summary: str` for the agent to relay verbatim. On expected errors (not-found, perm denied, published, name-collision), tools catch `ValueError` and return a result with `ok=False, summary="..."` rather than raising — the agent surfaces that to the user. Unexpected exceptions propagate.
- All registered in `subagents/protocol_builder/config.py:build()`.

## Prompt update

`prompt.md` gets a new "Editing existing protocols" section:

1. Use `list_protocols` to find the right one. Prefer name + project disambiguation.
2. Use `get_protocol` before any mutation to know the current step list and roles.
3. Mutating tools refuse on published protocols — relay the message to the user, don't try to work around it.
4. To add a chain of steps to a role, call `add_protocol_role` first, then `add_protocol_step(..., role_id=...)` per step.
5. Unit op edits respect the scope ladder; `elevate_unit_op_scope` is org-admin-only and one-way (project → org).

## Tests

**Unit tests for the service layer** (TDD — write first):
- `tests/unit/test_protocols_lookup.py`: list filters by perm, includes has_draft flag, get_protocol_full returns nested roles.
- `tests/unit/test_protocols_graph.py`: add/remove/reorder/replace happy paths, indices out of range, non-DRAFT refusal, edge chain integrity, role parent assignment.
- `tests/unit/test_protocols_roles.py`: CRUD, sort_order auto-assignment, non-DRAFT refusal.
- Extend `tests/unit/test_protocols_unit_ops.py`: update happy paths, non-admin can't update org-scoped, elevate happy path, elevate refuses non-admin / already-org / library-override.
- Extend `tests/unit/test_protocols_creation.py`: `update_protocol_metadata` happy + non-DRAFT.

**Tool-layer tests** in `tests/unit/test_subagents_protocol_builder.py`: per new tool — service is monkeypatched, assert arg mapping, `tool_calls` audit append, dataclass shape, and the `ok=False` translation when the service raises `ValueError`.

## Out of scope (explicit)

- Draft-version materialization / `NeedsTargetDecision` flow (deferred).
- Arbitrary edge re-wiring (`update_protocol_edges`).
- "Inline graph node → UnitOpDefinition" promotion.
- Role-control gating (no role-perm model exists yet).
- Frontend changes — chat surfaces these tools through existing message rendering. No new UI components.
- Modifying the existing endpoint draft logic in `api/endpoints/protocols.py`.
