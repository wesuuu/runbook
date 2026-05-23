# TD-0091d — Notification step-level deep links

**Date:** 2026-05-22
**Status:** Spec — hardened after review panel
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
   `notifications` with a size cap.
2. **Resolver** — when `entity_type == "run"` and `payload.step_id` is a
   string matching `^[A-Za-z0-9_-]{1,64}$`, append `#step-<id>` to the
   resolved URL.
3. **Producer API** — extend the `send_notification` wrapper to accept an
   optional `payload: dict | None = None`. Existing 5 call sites unchanged.
4. **Run page** — react to the URL fragment (`$page.url.hash`), scroll the
   matching step into view, apply a 1.5s outline-fade highlight (skipped
   under `prefers-reduced-motion`). In PLANNED and COMPLETED/EDITED states
   the step row is in the DOM; in ACTIVE state the `RoleWizard` advances
   its page index to the matching step *only when safe* (see below).
   Observer view is a no-op.

## Non-goals

- **Producer wiring for specific events.** This task does *not* update the
  existing 5 `send_notification` call sites to populate `payload.step_id`.
  Step-scoped event producers (F-0080 sign-off review queue, F-0093
  investigation workspace, future deviation producers) will add their own
  step ids when they come online; this task just makes the field available.
- **Step-level permissions.** The run page's existing object-level check
  already gates everything below it.
- **Observer view step granularity.** Observers see role-level progress
  only; the fragment is honored where step rows actually render. The
  observer view stays silent — no banner, no toast, no fallback UI.
- **`FieldModeRoleWizard.svelte`.** The field-mode wizard has its own
  `currentStepIdx` and is structurally similar to `RoleWizard`, but it is
  out of scope for this task. Field-mode deep linking is a follow-up; we
  document the gap rather than half-implementing it.
- **Backfill.** The default `'{}'` covers existing rows. No data migration
  required.
- **API schema surfacing.** `NotificationResponse` (Pydantic) intentionally
  does not include `payload`; the field is internal-only and consumed by
  the resolver, not by the frontend. The frontend reads the resolved URL
  (with fragment already appended) via `resolve_notification_urls`.

## Acceptance criteria

- Alembic migration applied; `alembic heads` returns a single head.
- `Notification.payload` is `JSONB NOT NULL DEFAULT '{}'` with a CHECK
  constraint `octet_length(payload::text) <= 512`.
- `send_notification(..., payload={"step_id": ...})` persists the payload
  on each created `Notification`; omitting `payload` keeps the default.
- `resolve_notification_urls` appends `#step-<step_id>` when
  `entity_type == "run"` and `payload.step_id` is a string matching
  `^[A-Za-z0-9_-]{1,64}$`; no anchor otherwise.
- Run page in PLANNED state: a deep link to a present step scrolls the
  EBR row into view and applies the highlight; an unknown step id no-ops.
- Run page in COMPLETED/EDITED state: same behavior on the
  `RunResultsSummary` rows.
- Run page in ACTIVE state for the role assignee: the `RoleWizard`
  seeds `currentStepIdx` to the matching step's page index **only when
  the wizard is on step 0 and `executionData` has no unsaved edits**;
  otherwise the wizard is left alone (silent no-op). The targeted step
  receives the highlight when the wizard does land on it.
- ACTIVE observer view ignores the fragment entirely (silent no-op).
- Hash changes after mount (e.g. clicking a second notification while
  the run page is already open) are handled — the page reacts to a
  changed `$page.url.hash` and re-focuses.
- `prefers-reduced-motion: reduce` users get an instant scroll (`behavior:
  'auto'`) and no highlight animation.
- Unit tests in `backend/tests/unit/test_notification_links.py` cover
  payload-present, payload-absent, and validation-rejection paths.
- Frontend test covers mount-with-fragment scroll + highlight for the
  EBR table (PLANNED state) **and** a second hash change after mount.
- `.claude/rules/backend-services.md` documents the `payload.step_id`
  contract and the `^[A-Za-z0-9_-]{1,64}$` shape for future producers.

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
| `step_id` | string | Stable id of a step within `entity_type == "run"`'s graph snapshot. Must match `^[A-Za-z0-9_-]{1,64}$`. |

Future keys land here as siblings (signoff_id, attachment_id, comment_id)
without further migrations.

**Migration.** Alembic autogenerate, then review. Add column **and**
CHECK constraint:

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
op.create_check_constraint(
    "ck_notifications_payload_size",
    "notifications",
    "octet_length(payload::text) <= 512",
)
```

512 bytes is generous for the documented keys (a UUID step_id is ~36
bytes; even five sibling keys fit) and cheap insurance against a
producer accidentally stuffing the whole event payload in here.

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
    notif_payload = payload if payload is not None else {}
    for user_id in recipients:
        notif = Notification(
            user_id=user_id,
            event_type=event_type,
            entity_type=entity_type,
            entity_id=entity_id,
            title=title_personal,
            message=body_personal,
            payload=notif_payload,      # NEW
        )
        db.add(notif)
```

`payload if payload is not None else {}` (not `payload or {}`) so a
caller explicitly passing `{}` is preserved verbatim and a falsy-but-
present dict can't be coerced away by a future change.

The wrapper docstring will document the `payload.step_id` contract for
step-scoped events on a run, and the `^[A-Za-z0-9_-]{1,64}$` shape.

**Resolver.** In `links.py::resolve_notification_urls`, after the
existing `result[n.id] = f"/{org_slug}{path}"` line, append a fragment
for run notifications carrying a *validated* `step_id`:

```python
import re

_STEP_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")

url = f"/{org_slug}{path}"
if (
    (n.entity_type or "").lower() == "run"
    and isinstance(n.payload, dict)
):
    step_id = n.payload.get("step_id")
    if isinstance(step_id, str) and _STEP_ID_RE.match(step_id):
        url = f"{url}#step-{step_id}"
result[n.id] = url
```

The regex is the contract: producers send ids matching it, the resolver
refuses to emit anchors for anything else, and the frontend uses the
same regex to validate what it reads back from the hash. This closes
off XSS via crafted fragments and keeps the contract enforceable in
one place.

Fragment over query string: not sent to the server, survives reloads,
and we already serve a SPA.

### Frontend

The run page has three rendering branches keyed off `run.status`:

| Status        | Component(s)                              | Step rows in DOM? |
|---------------|-------------------------------------------|-------------------|
| PLANNED       | EBR `<Table.Root>` in `+page.svelte`      | Yes — all steps   |
| ACTIVE        | `RoleWizard.svelte` (assignee)            | One step at a time |
| ACTIVE        | `RunObserverView.svelte` (non-assignee)   | None              |
| COMPLETED / EDITED | `RunResultsSummary.svelte`           | Yes — all steps   |

**Shared helper.** New module `frontend/src/lib/utils/stepDeepLink.ts`
exports a single function:

```typescript
/**
 * Scroll the element with data-step-id={stepId} into view and apply a
 * 1.5s highlight. No-op if the element isn't in the DOM. Idempotent —
 * cancels any prior highlight on the same element. Honors
 * `prefers-reduced-motion: reduce` (instant scroll, no animation).
 */
export async function focusStep(stepId: string): Promise<void> { ... }
```

That's the only export. Fragment parsing is intentionally **inlined at
the call site** with `/^#step-([A-Za-z0-9_-]{1,64})$/` — three lines,
shared regex with the backend, no reason to wrap it in a helper.

`focusStep`:
- Finds the element via `document.querySelector(\`[data-step-id="${CSS.escape(stepId)}"]\`)`.
  `CSS.escape` is belt-and-suspenders given the regex already restricts
  input, but cheap and correct.
- Reads `window.matchMedia('(prefers-reduced-motion: reduce)').matches`.
  If true: `scrollIntoView({behavior: 'auto', block: 'center'})` and
  return without toggling the highlight class.
- Otherwise: `scrollIntoView({behavior: 'smooth', block: 'center'})`,
  toggles `.step-deeplink-target` on the element for 1.5 seconds, then
  removes it.

**Style injection.** `stepDeepLink.ts` injects its CSS rule
(`.step-deeplink-target { ... }`) into `document.head` once, on first
import, guarded by a module-level boolean. This keeps the visual
contract co-located with the JS that toggles the class — consumers
don't have to remember to ship the rule, and three call sites can't
drift apart.

**Three integration points** (one per state with rows):

1. **EBR table** (`+page.svelte`, PLANNED state). Each `<Table.Row>`
   gets `data-step-id={step.id}`. An `$effect` subscribed to
   `$page.url.hash` parses the fragment with the inline regex and
   calls `focusStep` whenever the hash changes (covers both mount and
   subsequent navigation to a second notification while the page is
   already open).

2. **`RunResultsSummary.svelte`** (COMPLETED/EDITED). Same
   `data-step-id` attribute on each step card. Same `$effect`-on-hash
   pattern.

3. **`RoleWizard.svelte`** (ACTIVE, assignee). Wizard already tracks a
   `currentStepIdx` rune (`let currentStepIdx = $state(0)` at
   `RoleWizard.svelte:72`). New `initialStepId?: string` prop. An
   `$effect` keyed on `[steps, initialStepId]` (not `onMount`) seeds
   the wizard:

   ```typescript
   $effect(() => {
     if (!initialStepId) return;
     const idx = steps.findIndex(s => s.id === initialStepId);
     if (idx < 0) return;                          // not in this role's pages
     if (currentStepIdx !== 0) return;             // user already navigated; don't yank
     if (hasUnsavedExecutionData()) return;        // protect in-flight edits
     currentStepIdx = idx;
     // focusStep runs after the wizard re-renders the new page; see below
   });
   ```

   The effect is keyed on `steps` (not bare mount) so an unknown id
   doesn't strand the user if `steps` arrive later. The wizard step
   container gets `data-step-id={currentStep.id}` so the highlight
   finds it. `focusStep(initialStepId)` is called from a second
   `$effect` that fires after `currentStepIdx` changes — this is how
   we avoid the old "wait a microtask" wording; we let Svelte's
   reactivity drive ordering.

   **Silent no-op rules** (per user decision, no banner):
   - If `initialStepId` is unknown to this role: silent no-op.
   - If the user has already advanced past step 0: silent no-op.
   - If `executionData` has unsaved edits on the current step: silent
     no-op. (We don't want the wizard to jump the user away from an
     in-progress entry.)
   - Observer view does not receive `initialStepId` at all.

The mount-time read of `window.location.hash` is replaced by a
`$page`-store subscription in `+page.svelte`; each state branch
derives `stepIdFromHash` from `$page.url.hash` and passes it down as
needed (PLANNED/COMPLETED use it directly; ACTIVE assignee passes it
into `RoleWizard` as `initialStepId`; observer ignores it).

**Pre-existing input id collisions.** `RoleWizard.svelte` currently
uses `id="step-value"` (line 665) and `id="step-notes"` (line 692).
Those collide with the `#step-<id>` fragment shape if a producer ever
ships `step_id="value"` or `step_id="notes"`. Rename them to
`step-value-input` and `step-notes-input` in this task (and update
their `<label for=...>` siblings).

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
- Run + `payload={"step_id": "valid_id-1"}` → anchor appended.
- Run + `payload={}` → URL is the bare run path (no anchor).
- Run + `payload={"step_id": ""}` → no anchor (empty rejected by regex).
- Run + `payload={"step_id": 42}` → no anchor (non-string ignored).
- Run + `payload={"step_id": "x" * 65}` → no anchor (length cap).
- Run + `payload={"step_id": "bad id with spaces"}` → no anchor.
- Run + `payload={"step_id": "<script>"}` → no anchor (charset rejects).
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
- `send_notification(...)` without `payload` defaults to `{}`.
- `send_notification(..., payload={})` persists `{}` verbatim (not
  coerced to `None` or replaced).

### Frontend

`frontend/src/lib/utils/stepDeepLink.test.ts`:

- `focusStep("abc")` calls `scrollIntoView` on the matching element
  and toggles the `.step-deeplink-target` class.
- `focusStep("missing")` is a silent no-op.
- With `prefers-reduced-motion: reduce` mocked to `true`,
  `focusStep("abc")` uses `behavior: 'auto'` and does *not* toggle
  the highlight class.
- Style rule is injected exactly once even across multiple imports.

`frontend/src/routes/[org]/projects/[projectSlug]/runs/[slug]/+page.svelte`:
extend an existing test (or add `+page.test.ts`) to:

1. Mount in PLANNED state with `window.location.hash = "#step-<id>"`
   and assert the matching row gets the highlight class.
2. Then mutate `$page.url.hash` to `#step-<other-id>` and assert the
   second row gets the highlight (proves the effect handles re-firing,
   not just mount).

`RoleWizard` test:
- Mount with `initialStepId` for a step in the assignee's page list and
  assert `currentStepIdx` lands on the right page.
- Mount with an unknown id and assert it stays at `0`.
- Mount with `currentStepIdx = 2` already (simulate prior navigation)
  and assert `initialStepId` does *not* override it.
- Mount with `hasUnsavedExecutionData() === true` and assert
  `initialStepId` does *not* override the current page.

### Browser verification (qa-verify)

Add an explicit check that **`NotificationBell.svelte`'s
`goto(href)`** preserves the `#step-<id>` fragment when the user
clicks an inbox row. SvelteKit's `goto` historically strips fragments
in some versions; we want to confirm the live behavior, not assume.
Verify by clicking a seeded notification with a known step id and
watching the URL bar settle on `…#step-<id>`.

---

## Risks & mitigations

- **Race between hash change and step rendering.** Driven by
  `$effect`s keyed on the relevant reactive inputs (`$page.url.hash`
  for the simple cases; `[steps, initialStepId, currentStepIdx]` for
  the wizard), so Svelte's scheduler handles ordering rather than us
  guessing at microtask boundaries.
- **Unknown step id in the URL.** Silent no-op. Producers should be
  trusted to send valid ids; an arbitrary user pasting `#step-foo`
  loads the page as if the fragment were absent. No error toast.
- **XSS via crafted fragment.** Closed off by the
  `^[A-Za-z0-9_-]{1,64}$` regex at both producer (resolver-side
  validation) and consumer (frontend parse). `CSS.escape` is the
  final belt-and-suspenders against any injection into the
  attribute-selector path.
- **Wizard yanking the user away from in-flight work.** The seeding
  effect refuses to move `currentStepIdx` when the user has already
  navigated past step 0 or has unsaved `executionData`. Silent, per
  the chosen UX direction.
- **Future payload schema drift.** The column is schemaless on purpose
  — siblings (signoff_id, attachment_id) can land without migrations.
  Validation happens at the producer (and at the resolver, which only
  honors known keys).
- **Payload bloat.** The 512-byte CHECK constraint stops a producer
  from accidentally stuffing the full event into `payload`. If a
  legitimate use case ever needs more, raise the cap deliberately.
- **`NotificationResponse` doesn't expose `payload`.** Intentional;
  the resolved URL (with fragment) is the only thing the frontend
  needs. If a future feature needs structured payload on the client,
  add it to the schema then.
- **`NotificationBell.svelte` `goto(href)` may strip fragments.**
  Mitigated by the qa-verify browser check above; if it does strip,
  fall back to `window.location.href = href` for hash-bearing URLs.
- **Forward-compat with secondary entity routing.** If a future
  notification points to an experiment+run pair (rare today), it can
  store `payload.run_id` and the experiment resolver can opt in
  similarly. The contract is: each entity type's resolver decides
  which payload keys it honors.

---

## Files touched

Backend:
- `backend/app/models/notifications.py` (+1 column)
- `backend/alembic/versions/<new>_add_notification_payload.py` (new —
  column + CHECK constraint)
- `backend/app/services/core/notifications/__init__.py` (signature + persist)
- `backend/app/services/core/notifications/links.py` (resolver append +
  shared `_STEP_ID_RE` regex)
- `backend/tests/unit/test_notification_links.py` (extend)
- `backend/tests/unit/test_notification_service.py` (extend or create)

Frontend:
- `frontend/src/lib/utils/stepDeepLink.ts` (new — exports only
  `focusStep`; injects its own `<style>` once)
- `frontend/src/lib/utils/stepDeepLink.test.ts` (new)
- `frontend/src/routes/[org]/projects/[projectSlug]/runs/[slug]/+page.svelte`
  (EBR rows get `data-step-id`; `$effect` on `$page.url.hash`; pass
  `initialStepId` to `RoleWizard`)
- `frontend/src/lib/components/run/RunResultsSummary.svelte`
  (step cards get `data-step-id`; `$effect` on `$page.url.hash`)
- `frontend/src/lib/components/run/RoleWizard.svelte` (`initialStepId`
  prop; seeding `$effect` with safety guards; rename `id="step-value"`
  → `step-value-input` and `id="step-notes"` → `step-notes-input` plus
  their `<label for=...>` siblings)
- Frontend test for run page PLANNED-state scroll + second hash change
- Frontend test for `RoleWizard` `initialStepId` page-index seed +
  no-op guards

Docs:
- `.claude/rules/backend-services.md` (notification payload contract,
  `payload.step_id` shape `^[A-Za-z0-9_-]{1,64}$`)
- `CLAUDE.md` (mention `payload` column if it warrants a one-liner;
  skip if it doesn't)

Out of scope (documented gap):
- `frontend/src/lib/components/field-mode/FieldModeRoleWizard.svelte`
  — field-mode deep linking is a follow-up task.
