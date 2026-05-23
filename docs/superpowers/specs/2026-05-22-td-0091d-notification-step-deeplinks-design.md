# TD-0091d — Notification step-level deep links

**Date:** 2026-05-22
**Status:** Spec
**Parent:** [TD-0091] In-app notification system — QA audit remediation
**Sibling:** [TD-0091b] Notification inbox — UX, observability & test coverage

---

## Problem

Notifications resolve to a run/experiment/protocol/project URL, but not to a
specific step within a run. A "Deviation logged at step 3" notification opens
the run page generally; the user has to hunt for the step.

The model has no place to put a step id:

```python
class Notification(...):
    entity_type: Mapped[str]              # "run" | "experiment" | ...
    entity_id:   Mapped[uuid.UUID]
    # no payload, no secondary entity, no step pointer
```

The `Notification` row is consumed by
`backend/app/services/core/notifications/links.py::resolve_notification_urls`,
which appends `f"/projects/{slug}/runs/{slug}"` to the org segment. There's
nothing to anchor on below run.

This came out of TD-0091b verification — the user wanted the
"Deviation logged" link to anchor on the exact step.

## Scope

A vertical slice across all four layers, establishing the contract before
producers come online:

1. **Schema** — add a `payload JSONB NOT NULL DEFAULT '{}'` column to
   `notifications`.
2. **Resolver** — when `entity_type == "run"` and `payload.step_id` is set,
   append `#step-<id>` to the resolved URL.
3. **Producer API** — extend the `send_notification` wrapper to accept an
   optional `payload: dict | None = None`. Existing 5 call sites unchanged.
4. **Run page** — on mount, read the URL fragment, scroll the matching step
   into view, apply a 1.5s outline-fade highlight. In PLANNED and
   COMPLETED/EDITED states the step row is in the DOM; in ACTIVE state the
   `RoleWizard` advances its page index to the matching step for the
   assignee. Observer view is a no-op.

## Non-goals

- **Producer wiring for specific events.** This task does *not* update the
  existing 5 `send_notification` call sites to populate `payload.step_id`.
  Step-scoped event producers (F-0080 sign-off review queue, F-0093
  investigation workspace, future deviation producers) will add their own
  step ids when they come online; this task just makes the field available.
- **Step-level permissions.** The run page's existing object-level check
  already gates everything below it.
- **Observer view step granularity.** Observers see role-level progress
  only; the fragment is honored where step rows actually render.
- **Backfill.** The default `'{}'` covers existing rows. No data migration
  required.

## Acceptance criteria

- Alembic migration applied; `alembic heads` returns a single head.
- `Notification.payload` is `JSONB NOT NULL DEFAULT '{}'`.
- `send_notification(..., payload={"step_id": ...})` persists the payload
  on each created `Notification`; omitting `payload` keeps the default.
- `resolve_notification_urls` appends `#step-<step_id>` when
  `entity_type == "run"` and `payload.step_id` is a non-empty string;
  no anchor otherwise.
- Run page in PLANNED state: a deep link to a present step scrolls the
  EBR row into view and applies the highlight; an unknown step id no-ops.
- Run page in COMPLETED/EDITED state: same behavior on the
  `RunResultsSummary` rows.
- Run page in ACTIVE state for the role assignee: the `RoleWizard`
  initializes on the matching step's page index and the wizard step
  receives the highlight. ACTIVE observer view ignores the fragment.
- Unit tests in `backend/tests/unit/test_notification_links.py` cover
  payload-present and payload-absent paths.
- Frontend test covers mount-with-fragment scroll + highlight for the
  EBR table (PLANNED state).
- `.claude/rules/backend-services.md` documents the `payload.step_id`
  contract for future producers.

---

## Architecture

### Backend

**Model.** Add one column to `Notification` in
`backend/app/models/notifications.py`:

```python
payload: Mapped[dict[str, Any]] = mapped_column(
    JSONB, default=dict, server_default="{}", nullable=False
)
```

The column is intentionally schemaless. Documented well-known keys:

| Key       | Type   | Meaning                                                          |
|-----------|--------|------------------------------------------------------------------|
| `step_id` | string | Stable id of a step within `entity_type == "run"`'s graph snapshot. |

Future keys land here as siblings (signoff_id, attachment_id, comment_id)
without further migrations.

**Migration.** Alembic autogenerate, then review:

```python
op.add_column(
    "notifications",
    sa.Column(
        "payload",
        postgresql.JSONB(astext_type=sa.Text()),
        nullable=False,
        server_default=sa.text("'{}'::jsonb"),
    ),
)
```

No data migration needed (the server default covers existing rows). No
new index — the column is consumed at read time by the resolver, never
queried.

**Service wrapper.** Extend `send_notification` in
`backend/app/services/core/notifications/__init__.py`:

```python
async def send_notification(
    db: AsyncSession,
    event_type: str,
    org_id: UUID,
    entity_type: str,
    entity_id: UUID,
    recipients: list[UUID],
    context: dict,
    payload: dict | None = None,        # NEW — defaults preserve all callers
) -> None:
    ...
    for user_id in recipients:
        notif = Notification(
            user_id=user_id,
            event_type=event_type,
            entity_type=entity_type,
            entity_id=entity_id,
            title=title_personal,
            message=body_personal,
            payload=payload or {},      # NEW
        )
        db.add(notif)
```

The wrapper docstring will document the `payload.step_id` contract for
step-scoped events on a run.

**Resolver.** In `links.py::resolve_notification_urls`, after the
existing `result[n.id] = f"/{org_slug}{path}"` line, append a fragment
for run notifications carrying a `step_id`:

```python
url = f"/{org_slug}{path}"
if (
    (n.entity_type or "").lower() == "run"
    and isinstance(n.payload, dict)
):
    step_id = n.payload.get("step_id")
    if isinstance(step_id, str) and step_id:
        url = f"{url}#step-{step_id}"
result[n.id] = url
```

Fragment over query string: not sent to the server, survives reloads,
and we already serve a SPA. The id is stringified directly — step ids
are stable strings inside the run graph snapshot, not opaque enough to
need a separate encoder.

### Frontend

The run page has three rendering branches keyed off `run.status`:

| Status        | Component(s)                              | Step rows in DOM? |
|---------------|-------------------------------------------|-------------------|
| PLANNED       | EBR `<Table.Root>` in `+page.svelte`      | Yes — all steps   |
| ACTIVE        | `RoleWizard.svelte` (assignee)            | One step at a time |
| ACTIVE        | `RunObserverView.svelte` (non-assignee)   | None              |
| COMPLETED / EDITED | `RunResultsSummary.svelte`           | Yes — all steps   |

**Shared helper.** New module
`frontend/src/lib/utils/stepDeepLink.ts`:

```typescript
/** Read #step-<id> from the URL hash. Returns null when absent or malformed. */
export function readStepFragment(hash: string): string | null {
  const m = /^#step-(.+)$/.exec(hash);
  return m ? m[1] : null;
}

/**
 * Scroll the element with data-step-id={stepId} into view and apply a
 * 1.5s highlight. No-op if the element isn't in the DOM. Idempotent —
 * cancels any prior highlight on the same element.
 */
export async function focusStep(stepId: string): Promise<void> { ... }
```

`focusStep` waits one microtask, finds
`[data-step-id="<stepId>"]`, calls `scrollIntoView({behavior: 'smooth',
block: 'center'})`, toggles a `.step-deeplink-target` class for
1.5 seconds, then removes it. The class is defined in the page's
scoped style so consumers don't have to know the rule.

**Three integration points** (one per state with rows):

1. **EBR table** (`+page.svelte`, PLANNED state). Each `<Table.Row>`
   gets `data-step-id={step.id}`. An `onMount` effect reads the
   fragment and calls `focusStep`.
2. **`RunResultsSummary.svelte`** (COMPLETED/EDITED). Same
   `data-step-id` attribute on each step card. Same `onMount` effect.
3. **`RoleWizard.svelte`** (ACTIVE, assignee). Wizard already tracks a
   `currentStepIdx` rune (`let currentStepIdx = $state(0)` at
   `RoleWizard.svelte:72`). New `initialStepId?: string` prop. On
   mount, if the prop is set and matches a step in the assignee's
   page list, set `currentStepIdx` to that index and call
   `focusStep` after the page renders. The wizard step container
   gets `data-step-id` so the highlight finds it. If the step id
   isn't in this assignee's page list (it belongs to another role),
   no-op.

The mount-time read of `window.location.hash` is centralized in
`+page.svelte` once per state branch — each branch passes
`stepIdFromHash` down as needed.

### Why a fragment, not a query

- Not sent to the server (URL stays out of access logs).
- Survives soft reloads and the browser's back/forward.
- The router doesn't have to know about it — pure client concern.
- Convention in the codebase: SvelteKit owns route params and
  searchParams; we don't have other route-level features attaching
  themselves to query.

---

## Testing

### Backend

`backend/tests/unit/test_notification_links.py`:

- Run + `payload={"step_id": "abc-123"}` → URL ends with `#step-abc-123`.
- Run + `payload={}` → URL is the bare run path (no anchor).
- Run + `payload={"step_id": ""}` → no anchor (empty string ignored).
- Run + `payload={"step_id": 42}` → no anchor (non-string ignored).
- Run + `payload=None` → no anchor (defensive; the column is NOT NULL
  but defend against in-memory `None` from tests).
- Experiment + `payload={"step_id": "abc"}` → no anchor (only run
  entity type honors step deep links).

Existing resolver tests are extended only where they construct
`Notification` instances — they receive `payload={}`.

`backend/tests/unit/test_notification_service.py` (extend the existing
file if present; otherwise add):

- `send_notification(..., payload={"step_id": "abc"})` persists the
  payload on every created `Notification`.
- `send_notification(...)` without `payload` defaults to `{}` (matches
  the column default).

### Frontend

`frontend/src/lib/utils/stepDeepLink.test.ts`:

- `readStepFragment("#step-abc")` → `"abc"`.
- `readStepFragment("#step-")` → `null`.
- `readStepFragment("#other")` → `null`.
- `readStepFragment("")` → `null`.
- `focusStep("abc")` calls `scrollIntoView` on the matching element
  and toggles the highlight class.
- `focusStep("missing")` is a silent no-op.

`frontend/src/routes/[org]/projects/[projectSlug]/runs/[slug]/+page.svelte`:
extend an existing test (or add `+page.test.ts`) to mount in PLANNED
state with `window.location.hash = "#step-<id>"` and assert the
matching row gets the highlight class.

`RoleWizard` test: mount with `initialStepId` for a step in the
assignee's page list and assert `currentStepIdx` lands on the right
page; mount with an unknown id and assert it stays at `0`.

---

## Risks & mitigations

- **Race between mount and step rendering.** EBR rows are rendered
  immediately on mount, but the wizard renders the current step lazily
  on page-index change. `focusStep` waits one microtask; if the wizard
  step is deeper than that, the wizard mount effect drives the call
  itself after `currentStepIndex` settles.
- **Unknown step id in the URL.** Silent no-op. Producers should be
  trusted to send valid ids; an arbitrary user pasting `#step-foo`
  loads the page as if the fragment were absent. No error toast.
- **Future payload schema drift.** The column is schemaless on purpose
  — siblings (signoff_id, attachment_id) can land without migrations.
  Validation happens at the producer (and at the resolver, which only
  reads `step_id` as a string).
- **Forward-compat with secondary entity routing.** If a future
  notification points to an experiment+run pair (rare today), it can
  store `payload.run_id` and the experiment resolver can opt in
  similarly. The contract is: each entity type's resolver decides
  which payload keys it honors.

---

## Files touched

Backend:
- `backend/app/models/notifications.py` (+1 column)
- `backend/alembic/versions/<new>_add_notification_payload.py` (new)
- `backend/app/services/core/notifications/__init__.py` (signature + persist)
- `backend/app/services/core/notifications/links.py` (resolver append)
- `backend/tests/unit/test_notification_links.py` (extend)
- `backend/tests/unit/test_notification_service.py` (extend or create)

Frontend:
- `frontend/src/lib/utils/stepDeepLink.ts` (new)
- `frontend/src/lib/utils/stepDeepLink.test.ts` (new)
- `frontend/src/routes/[org]/projects/[projectSlug]/runs/[slug]/+page.svelte`
  (EBR rows get `data-step-id`; mount effect; pass `initialStepId` to
  `RoleWizard`)
- `frontend/src/lib/components/run/RunResultsSummary.svelte`
  (step cards get `data-step-id`; mount effect)
- `frontend/src/lib/components/run/RoleWizard.svelte` (`initialStepId`
  prop; effect on mount)
- Frontend test for run page PLANNED-state scroll
- Frontend test for `RoleWizard` `initialStepId` page-index seed

Docs:
- `.claude/rules/backend-services.md` (notification payload contract)
- `CLAUDE.md` (mention `payload` column if it warrants a one-liner; skip
  if it doesn't)
