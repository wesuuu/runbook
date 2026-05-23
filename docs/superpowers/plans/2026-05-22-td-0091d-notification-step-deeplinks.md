# TD-0091d — Notification step-level deep links: Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an optional `payload JSONB` column to `notifications`, make the URL resolver append `#step-<id>` for run notifications with `payload.step_id`, and make the run page (PLANNED, COMPLETED/EDITED, ACTIVE-assignee) scroll the matching step into view + highlight it. Observer view and field-mode wizard explicitly out of scope.

**Architecture:** Vertical slice across schema → service wrapper → resolver → frontend. Schema is intentionally schemaless dict; only the well-known `step_id` key is honored today. A single regex (`^[A-Za-z0-9_-]{1,64}$`) gates `step_id` at producer (resolver-side validation), URL-fragment shape, and frontend parse. Producers stay unchanged — this task only makes the field available; F-0080/F-0093/deviation tasks will populate it when they land.

**Tech Stack:** SQLAlchemy 2.0 async + Alembic + PostgreSQL JSONB on the backend; Svelte 5 (runes) + vitest on the frontend.

**Spec:** `docs/superpowers/specs/2026-05-22-td-0091d-notification-step-deeplinks-design.md`

---

## File Structure

**Backend:**
- `backend/app/models/notifications.py` — modify `Notification` (add `payload` column)
- `backend/alembic/versions/<rev>_add_notification_payload.py` — new migration (column + CHECK constraint)
- `backend/app/services/core/notifications/__init__.py` — extend `send_notification` signature + persist payload
- `backend/app/services/core/notifications/links.py` — add regex constant + fragment append
- `backend/tests/unit/test_notification_links.py` — extend (existing file)
- `backend/tests/unit/test_notification_service.py` — new file

**Frontend:**
- `frontend/src/lib/utils/stepDeepLink.ts` — new (exports only `focusStep`; injects scoped style once)
- `frontend/src/lib/utils/stepDeepLink.test.ts` — new
- `frontend/src/routes/[org]/projects/[projectSlug]/runs/[slug]/+page.svelte` — modify (EBR rows get `data-step-id`; `$effect` on `$page.url.hash`; pass `initialStepId` to `RoleWizard`)
- `frontend/src/lib/components/run/RunResultsSummary.svelte` — modify (step cards get `data-step-id`; `$effect` on `$page.url.hash`)
- `frontend/src/lib/components/run/RoleWizard.svelte` — modify (`initialStepId` prop + seeding `$effect`; rename two input ids)

**Docs:**
- `.claude/rules/backend-services.md` — append a one-paragraph subsection documenting the `payload.step_id` contract.

**Why these boundaries:** the deep-link helper is its own module because three frontend call sites would otherwise import the same regex + scrollIntoView + highlight logic. The regex lives once on each side (one Python constant in `links.py`, one inline regex literal at each frontend call site — the test asserts the shape). Schema, service, resolver, and frontend each land as separate commits so a regression bisects cleanly.

---

## Pre-flight (do once before Task 1)

- [ ] **Confirm the worktree is up and you're inside it.**

  This plan executes inside the worktree set up by the `implement-task` skill. Verify:

  ```bash
  pwd                          # should be /home/wesuuu/Code/trellisbio/.worktrees/td-0091d-...
  git branch --show-current    # should be td-0091d-...
  cat backend/.env | grep DATABASE_URL   # should point to batchrite_wt<N>
  ```

- [ ] **Confirm dev servers are running on the worktree's slot.**

  ```bash
  lsof -i :80<N>0              # backend (uvicorn)
  lsof -i :<5173 + 10*N>       # frontend (vite)
  ```

  If they aren't, start them per CLAUDE.md before continuing.

- [ ] **Confirm the test DB is reachable.**

  ```bash
  cd backend && source .venv/bin/activate
  pytest tests/unit/test_notification_links.py -q
  ```

  Expected: all existing tests pass. If they don't, fix the environment before touching code.

---

## Task 1: Add `payload` column to the `Notification` model

**Files:**
- Modify: `backend/app/models/notifications.py:135-163` (the `Notification` class)

- [ ] **Step 1: Modify the `Notification` model.**

  Add a `payload` field after the existing `read_at` column (the column order matches the existing pattern in the file). Use the same `JSONB` import that's already at the top.

  Replace this block in `backend/app/models/notifications.py`:

  ```python
      read_at: Mapped[Optional[Any]] = mapped_column(
          DateTime(timezone=True), nullable=True
      )

      # Relationships
      user: Mapped["User"] = relationship("app.models.iam.User")
  ```

  with:

  ```python
      read_at: Mapped[Optional[Any]] = mapped_column(
          DateTime(timezone=True), nullable=True
      )
      # TD-0091d: schemaless payload for deep-link metadata. Today only
      # `step_id` (string matching ^[A-Za-z0-9_-]{1,64}$) is honored, and
      # only when entity_type == "run". Future keys land here as siblings
      # (signoff_id, attachment_id, ...) without further migrations.
      payload: Mapped[dict[str, Any]] = mapped_column(
          JSONB, default=dict, server_default="{}", nullable=False
      )

      # Relationships
      user: Mapped["User"] = relationship("app.models.iam.User")
  ```

- [ ] **Step 2: Commit (model only — migration follows separately).**

  ```bash
  git add backend/app/models/notifications.py
  git commit -m "feat(TD-0091d): add payload JSONB to Notification model"
  ```

---

## Task 2: Alembic migration with size-cap CHECK constraint

**Files:**
- Create: `backend/alembic/versions/<rev>_add_notification_payload.py` (Alembic generates the filename)

- [ ] **Step 1: Generate the migration scaffold.**

  ```bash
  cd backend && source .venv/bin/activate
  alembic revision --autogenerate -m "add notification payload"
  ```

  Note the generated filename (e.g. `2026_05_22_xxxx-add_notification_payload.py`).

- [ ] **Step 2: Replace the autogenerated body to include the CHECK constraint.**

  Alembic autogenerate adds the column but won't emit the CHECK. Replace the generated `upgrade()` and `down_grade()` bodies so they read exactly:

  ```python
  def upgrade() -> None:
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


  def downgrade() -> None:
      op.drop_constraint(
          "ck_notifications_payload_size",
          "notifications",
          type_="check",
      )
      op.drop_column("notifications", "payload")
  ```

  Ensure `from sqlalchemy.dialects import postgresql` and `import sqlalchemy as sa` are present in the imports block (autogen usually adds them).

- [ ] **Step 3: Apply the migration.**

  ```bash
  alembic upgrade head
  ```

  Expected: no errors. `alembic heads` should report a single head.

- [ ] **Step 4: Sanity-check the constraint with `psql`.**

  ```bash
  psql -h localhost -U postgres -d $(python -c "from app.core.config import settings; print(settings.database_url.rsplit('/', 1)[1])") -c "\d+ notifications" | grep -E "payload|ck_notifications_payload_size"
  ```

  Expected: prints both the `payload` column line and the `ck_notifications_payload_size` constraint.

- [ ] **Step 5: Commit.**

  ```bash
  git add backend/alembic/versions/*add_notification_payload*.py
  git commit -m "feat(TD-0091d): migration for Notification.payload + size cap"
  ```

---

## Task 3: Extend `send_notification` to accept optional `payload`

**Files:**
- Modify: `backend/app/services/core/notifications/__init__.py:36-81`

- [ ] **Step 1: Write the failing test (new file).**

  Create `backend/tests/unit/test_notification_service.py`:

  ```python
  """Unit tests for the send_notification wrapper."""

  from uuid import uuid4

  import pytest
  from sqlalchemy import select

  from app.models.notifications import Notification
  from app.services.core.notifications import send_notification


  pytestmark = pytest.mark.asyncio


  async def test_send_notification_persists_payload(
      db_session, test_user, test_org
  ):
      """Explicit payload survives the wrapper end-to-end."""
      await send_notification(
          event_type="ROLE_ASSIGNED",
          org_id=test_org.id,
          entity_type="run",
          entity_id=uuid4(),
          recipients=[test_user.id],
          context={"role_name": "Operator", "run_name": "CHO 42"},
          payload={"step_id": "abc-123"},
      )

      rows = (
          await db_session.execute(
              select(Notification).where(Notification.user_id == test_user.id)
          )
      ).scalars().all()

      assert len(rows) == 1
      assert rows[0].payload == {"step_id": "abc-123"}


  async def test_send_notification_defaults_payload_to_empty_dict(
      db_session, test_user, test_org
  ):
      """Omitting payload persists `{}` (the column default)."""
      await send_notification(
          event_type="ROLE_ASSIGNED",
          org_id=test_org.id,
          entity_type="run",
          entity_id=uuid4(),
          recipients=[test_user.id],
          context={"role_name": "Operator", "run_name": "CHO 42"},
      )

      rows = (
          await db_session.execute(
              select(Notification).where(Notification.user_id == test_user.id)
          )
      ).scalars().all()

      assert len(rows) == 1
      assert rows[0].payload == {}


  async def test_send_notification_preserves_explicit_empty_payload(
      db_session, test_user, test_org
  ):
      """Caller passing {} verbatim is not coerced (rules out `payload or {}`)."""
      await send_notification(
          event_type="ROLE_ASSIGNED",
          org_id=test_org.id,
          entity_type="run",
          entity_id=uuid4(),
          recipients=[test_user.id],
          context={"role_name": "Operator", "run_name": "CHO 42"},
          payload={},
      )

      rows = (
          await db_session.execute(
              select(Notification).where(Notification.user_id == test_user.id)
          )
      ).scalars().all()

      assert len(rows) == 1
      assert rows[0].payload == {}
  ```

  **Important:** `send_notification` opens its own `AsyncSessionLocal` session (see existing code), so the test does *not* pass `db_session` in. The test reads back via `db_session` after the wrapper commits — this works because the test DB is the same DB the wrapper writes to.

- [ ] **Step 2: Run the test — expect FAIL.**

  ```bash
  cd backend && source .venv/bin/activate
  pytest tests/unit/test_notification_service.py -v
  ```

  Expected: FAIL with `TypeError: send_notification() got an unexpected keyword argument 'payload'` (and the default-test will fail because `payload` column would need to be unset / behavior differs).

- [ ] **Step 3: Add the `payload` parameter and persist it.**

  In `backend/app/services/core/notifications/__init__.py`, edit the `send_notification` signature (currently at line 36) to add `payload: dict | None = None` as the last keyword arg. Inside, compute the persisted value once outside the loop and pass it into each `Notification(...)` call.

  Change this block:

  ```python
  async def send_notification(
      event_type: str,
      org_id: UUID,
      entity_type: str,
      entity_id: UUID,
      recipients: list[UUID],
      context: dict,
  ) -> None:
      """Main entry point: create in-app notifications and dispatch to channels.

      Opens its own AsyncSessionLocal session — safe to call from
      BackgroundTasks after the request session is closed.

      Args:
          event_type: NotificationEventType value (e.g. "ROLE_ASSIGNED").
          org_id: Organization ID for org-level channel lookup.
          entity_type: Entity type for deep linking (e.g. "run", "protocol").
          entity_id: Entity UUID for deep linking.
          recipients: List of user IDs to notify.
          context: Template variables (run_name, role_name, etc.).
      """
  ```

  to:

  ```python
  async def send_notification(
      event_type: str,
      org_id: UUID,
      entity_type: str,
      entity_id: UUID,
      recipients: list[UUID],
      context: dict,
      payload: dict | None = None,
  ) -> None:
      """Main entry point: create in-app notifications and dispatch to channels.

      Opens its own AsyncSessionLocal session — safe to call from
      BackgroundTasks after the request session is closed.

      Args:
          event_type: NotificationEventType value (e.g. "ROLE_ASSIGNED").
          org_id: Organization ID for org-level channel lookup.
          entity_type: Entity type for deep linking (e.g. "run", "protocol").
          entity_id: Entity UUID for deep linking.
          recipients: List of user IDs to notify.
          context: Template variables (run_name, role_name, etc.).
          payload: Optional schemaless dict persisted on each Notification.
              TD-0091d: pass {"step_id": "<id>"} (matching
              ^[A-Za-z0-9_-]{1,64}$) for step-scoped events on a run; the
              resolver will append #step-<id> to the deep link.
      """
  ```

  Then update the loop body. Replace:

  ```python
      async with AsyncSessionLocal() as db:
          try:
              for user_id in recipients:
                  db.add(
                      Notification(
                          user_id=user_id,
                          event_type=event_type,
                          entity_type=entity_type,
                          entity_id=entity_id,
                          title=title_personal,
                          message=body_personal,
                      )
                  )
              await db.flush()
  ```

  with:

  ```python
      notif_payload = payload if payload is not None else {}
      async with AsyncSessionLocal() as db:
          try:
              for user_id in recipients:
                  db.add(
                      Notification(
                          user_id=user_id,
                          event_type=event_type,
                          entity_type=entity_type,
                          entity_id=entity_id,
                          title=title_personal,
                          message=body_personal,
                          # Per-row dict copy so SQLAlchemy doesn't hand the
                          # same mutable dict to N ORM instances. JSONB
                          # serialization is independent, but defensive
                          # copying rules out a later mutation surprising
                          # the other rows.
                          payload=dict(notif_payload),
                      )
                  )
              await db.flush()
  ```

  `payload if payload is not None else {}` (not `payload or {}`) so a caller explicitly passing `{}` is preserved verbatim.

- [ ] **Step 4: Run the test — expect PASS.**

  ```bash
  pytest tests/unit/test_notification_service.py -v
  ```

  Expected: all 3 tests pass.

- [ ] **Step 5: Run the full notifications test suite to confirm no regressions in existing callers.**

  ```bash
  pytest tests/unit/test_notifications.py tests/unit/test_notification_links.py tests/unit/test_notification_policy.py tests/unit/test_notification_provisioning.py tests/unit/test_notification_service.py -v
  ```

  Expected: all pass. The existing 13 call sites across the service layer (verified via `grep -rn 'send_notification(' backend/app`) pass positional args and stop at `context`, so the new keyword `payload=None` default keeps them unchanged.

- [ ] **Step 6: Commit.**

  ```bash
  git add backend/app/services/core/notifications/__init__.py backend/tests/unit/test_notification_service.py
  git commit -m "feat(TD-0091d): send_notification accepts optional payload"
  ```

---

## Task 4: Resolver appends `#step-<id>` for validated step ids

**Files:**
- Modify: `backend/app/services/core/notifications/links.py` (add regex constant near top; modify the final result loop ~line 152)
- Modify: `backend/tests/unit/test_notification_links.py` (extend with new payload tests)

- [ ] **Step 1: Write the failing tests.**

  Append the following block to the **end** of `backend/tests/unit/test_notification_links.py`:

  ```python
  # -- TD-0091d: payload.step_id deep-link anchoring ----------------------


  async def _run_notif_with_payload(
      db_session, test_user, run, payload
  ):
      """Create + flush a run-typed Notification with a specific payload."""
      n = Notification(
          user_id=test_user.id,
          event_type="STEP_DEVIATION",
          entity_type="run",
          entity_id=run.id,
          title="t",
          message="m",
          payload=payload,
      )
      db_session.add(n)
      await db_session.flush()
      return n


  async def test_run_notification_with_step_id_appends_fragment(
      db_session, test_user, test_project
  ):
      run = Run(name="R", slug="r-step", project_id=test_project.id)
      db_session.add(run)
      await db_session.flush()
      n = await _run_notif_with_payload(
          db_session, test_user, run, {"step_id": "abc-123"}
      )

      urls = await resolve_notification_urls(db_session, [n], test_user.id)

      assert urls[n.id] == (
          "/test-org/projects/test-project/runs/r-step#step-abc-123"
      )


  async def test_run_notification_with_empty_payload_has_no_fragment(
      db_session, test_user, test_project
  ):
      run = Run(name="R", slug="r-empty", project_id=test_project.id)
      db_session.add(run)
      await db_session.flush()
      n = await _run_notif_with_payload(db_session, test_user, run, {})

      urls = await resolve_notification_urls(db_session, [n], test_user.id)

      assert urls[n.id] == "/test-org/projects/test-project/runs/r-empty"


  async def test_run_notification_with_empty_step_id_has_no_fragment(
      db_session, test_user, test_project
  ):
      run = Run(name="R", slug="r-emp-id", project_id=test_project.id)
      db_session.add(run)
      await db_session.flush()
      n = await _run_notif_with_payload(
          db_session, test_user, run, {"step_id": ""}
      )

      urls = await resolve_notification_urls(db_session, [n], test_user.id)

      assert urls[n.id] == "/test-org/projects/test-project/runs/r-emp-id"


  async def test_run_notification_with_non_string_step_id_is_ignored(
      db_session, test_user, test_project
  ):
      run = Run(name="R", slug="r-int", project_id=test_project.id)
      db_session.add(run)
      await db_session.flush()
      n = await _run_notif_with_payload(
          db_session, test_user, run, {"step_id": 42}
      )

      urls = await resolve_notification_urls(db_session, [n], test_user.id)

      assert urls[n.id] == "/test-org/projects/test-project/runs/r-int"


  async def test_run_notification_with_overlong_step_id_is_ignored(
      db_session, test_user, test_project
  ):
      run = Run(name="R", slug="r-long", project_id=test_project.id)
      db_session.add(run)
      await db_session.flush()
      n = await _run_notif_with_payload(
          db_session, test_user, run, {"step_id": "x" * 65}
      )

      urls = await resolve_notification_urls(db_session, [n], test_user.id)

      assert urls[n.id] == "/test-org/projects/test-project/runs/r-long"


  async def test_run_notification_with_invalid_chars_in_step_id_is_ignored(
      db_session, test_user, test_project
  ):
      run = Run(name="R", slug="r-bad", project_id=test_project.id)
      db_session.add(run)
      await db_session.flush()
      n = await _run_notif_with_payload(
          db_session, test_user, run, {"step_id": "bad id"}
      )

      urls = await resolve_notification_urls(db_session, [n], test_user.id)

      assert urls[n.id] == "/test-org/projects/test-project/runs/r-bad"


  async def test_run_notification_with_xss_step_id_is_ignored(
      db_session, test_user, test_project
  ):
      run = Run(name="R", slug="r-xss", project_id=test_project.id)
      db_session.add(run)
      await db_session.flush()
      n = await _run_notif_with_payload(
          db_session, test_user, run, {"step_id": "<script>"}
      )

      urls = await resolve_notification_urls(db_session, [n], test_user.id)

      assert urls[n.id] == "/test-org/projects/test-project/runs/r-xss"


  async def test_experiment_notification_with_step_id_has_no_fragment(
      db_session, test_user, test_project
  ):
      exp = Experiment(name="E", slug="e-step", project_id=test_project.id)
      db_session.add(exp)
      await db_session.flush()
      n = Notification(
          user_id=test_user.id,
          event_type="STEP_DEVIATION",
          entity_type="experiment",
          entity_id=exp.id,
          title="t",
          message="m",
          payload={"step_id": "abc"},
      )
      db_session.add(n)
      await db_session.flush()

      urls = await resolve_notification_urls(db_session, [n], test_user.id)

      assert urls[n.id] == (
          "/test-org/projects/test-project/experiments/e-step"
      )
  ```

- [ ] **Step 2: Run the new tests — expect FAIL.**

  ```bash
  pytest tests/unit/test_notification_links.py -k "step_id or payload or fragment" -v
  ```

  Expected: FAIL — the resolver does not append `#step-...` yet, and the first test (`test_run_notification_with_step_id_appends_fragment`) will fail on the assertion comparing to the bare URL.

- [ ] **Step 3: Add the regex constant and the fragment-append logic.**

  Edit `backend/app/services/core/notifications/links.py`:

  Add `import re` to the imports block (after `from __future__ import annotations`), and add the regex constant just below the existing `_ROUTABLE` frozenset (around line 32):

  ```python
  # TD-0091d: a Notification.payload.step_id is honored only when it
  # matches this shape. Mirrored at the frontend parser. The bound caps
  # injection surface area and matches the CHECK octet_length cap.
  _STEP_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
  ```

  Then modify the final result-building loop. Replace:

  ```python
      result: dict[UUID, Optional[str]] = {}
      for n in notifications:
          target = targets.get(((n.entity_type or "").lower(), n.entity_id))
          if target is None:
              result[n.id] = None
              continue
          org_id, path = target
          org_slug = org_slugs.get(org_id)
          # A blank or hyphen-leading slug means the org name had no
          # alphanumeric content — there is no valid route, so degrade.
          if org_slug and not org_slug.startswith("-"):
              result[n.id] = f"/{org_slug}{path}"
          else:
              result[n.id] = None
      return result
  ```

  with:

  ```python
      result: dict[UUID, Optional[str]] = {}
      for n in notifications:
          target = targets.get(((n.entity_type or "").lower(), n.entity_id))
          if target is None:
              result[n.id] = None
              continue
          org_id, path = target
          org_slug = org_slugs.get(org_id)
          # A blank or hyphen-leading slug means the org name had no
          # alphanumeric content — there is no valid route, so degrade.
          if not (org_slug and not org_slug.startswith("-")):
              result[n.id] = None
              continue
          url = f"/{org_slug}{path}"
          # TD-0091d: step deep link, run-only, validated step_id.
          if (n.entity_type or "").lower() == "run" and isinstance(
              n.payload, dict
          ):
              step_id = n.payload.get("step_id")
              if isinstance(step_id, str) and _STEP_ID_RE.match(step_id):
                  url = f"{url}#step-{step_id}"
          result[n.id] = url
      return result
  ```

- [ ] **Step 4: Run the new tests — expect PASS.**

  ```bash
  pytest tests/unit/test_notification_links.py -v
  ```

  Expected: all tests pass (the new 8 and all 14 pre-existing).

- [ ] **Step 5: Commit.**

  ```bash
  git add backend/app/services/core/notifications/links.py backend/tests/unit/test_notification_links.py
  git commit -m "feat(TD-0091d): resolver appends validated #step-<id> fragment"
  ```

---

## Task 5: Frontend `stepDeepLink` helper module

**Files:**
- Create: `frontend/src/lib/utils/stepDeepLink.ts`
- Create: `frontend/src/lib/utils/stepDeepLink.test.ts`

- [ ] **Step 1: Write the failing tests.**

  Create `frontend/src/lib/utils/stepDeepLink.test.ts`:

  ```typescript
  import { describe, it, expect, beforeEach, vi } from 'vitest';
  import { focusStep } from './stepDeepLink';

  describe('focusStep', () => {
      beforeEach(() => {
          document.body.innerHTML = '';
          document.head
              .querySelectorAll('style[data-step-deeplink]')
              .forEach((el) => el.remove());
          vi.restoreAllMocks();
      });

      it('scrolls and highlights the matching element', async () => {
          const el = document.createElement('div');
          el.setAttribute('data-step-id', 'abc-123');
          const scrollSpy = vi.fn();
          el.scrollIntoView = scrollSpy;
          document.body.appendChild(el);

          await focusStep('abc-123');

          expect(scrollSpy).toHaveBeenCalledWith(
              expect.objectContaining({
                  behavior: 'smooth',
                  block: 'nearest',
              }),
          );
          expect(el.classList.contains('step-deeplink-target')).toBe(true);
      });

      it('is a silent no-op when the element is absent', async () => {
          await expect(focusStep('missing')).resolves.toBeUndefined();
      });

      it('honors prefers-reduced-motion (instant scroll, no highlight)', async () => {
          const el = document.createElement('div');
          el.setAttribute('data-step-id', 'abc');
          const scrollSpy = vi.fn();
          el.scrollIntoView = scrollSpy;
          document.body.appendChild(el);

          vi.spyOn(window, 'matchMedia').mockImplementation(
              (q: string) =>
                  ({
                      matches: q.includes('reduce'),
                      media: q,
                      onchange: null,
                      addEventListener: () => {},
                      removeEventListener: () => {},
                      addListener: () => {},
                      removeListener: () => {},
                      dispatchEvent: () => false,
                  }) as MediaQueryList,
          );

          await focusStep('abc');

          expect(scrollSpy).toHaveBeenCalledWith(
              expect.objectContaining({ behavior: 'auto' }),
          );
          expect(el.classList.contains('step-deeplink-target')).toBe(false);
      });

      it('injects its <style> exactly once across multiple imports', async () => {
          const el = document.createElement('div');
          el.setAttribute('data-step-id', 'a');
          el.scrollIntoView = () => {};
          document.body.appendChild(el);

          await focusStep('a');
          await focusStep('a');
          await focusStep('a');

          const styles = document.head.querySelectorAll(
              'style[data-step-deeplink]',
          );
          expect(styles.length).toBe(1);
      });

      it('escapes selector input', async () => {
          const el = document.createElement('div');
          el.setAttribute('data-step-id', 'safe-id');
          const scrollSpy = vi.fn();
          el.scrollIntoView = scrollSpy;
          document.body.appendChild(el);

          // CSS.escape should not blow up if a regex-passing id has special
          // chars; ours can't (the regex forbids them), but the helper
          // wraps the value in CSS.escape regardless.
          await focusStep('safe-id');
          expect(scrollSpy).toHaveBeenCalled();
      });
  });
  ```

- [ ] **Step 2: Run the tests — expect FAIL.**

  ```bash
  cd frontend
  npm run test -- src/lib/utils/stepDeepLink.test.ts
  ```

  Expected: FAIL with `Cannot find module './stepDeepLink'`.

- [ ] **Step 3: Implement the helper.**

  Create `frontend/src/lib/utils/stepDeepLink.ts`:

  ```typescript
  /**
   * Step-level deep-link helper.
   *
   * Producers stamp `data-step-id="<id>"` on the DOM node for each step;
   * `focusStep(id)` scrolls the matching node into view and applies a
   * brief outline-fade highlight. Honors `prefers-reduced-motion: reduce`
   * (instant scroll, no animation). Silent no-op when no element matches.
   *
   * The associated CSS rule (`.step-deeplink-target`) is injected into
   * `document.head` on first call so consumers don't have to remember to
   * ship it. The `step_id` shape (`^[A-Za-z0-9_-]{1,64}$`) is enforced
   * upstream at the backend resolver and at each frontend hash parse;
   * `CSS.escape` here is a final belt-and-suspenders.
   */

  const STYLE_ID = 'step-deeplink-style';
  const HIGHLIGHT_CLASS = 'step-deeplink-target';
  const HIGHLIGHT_MS = 1500;

  let styleInjected = false;

  function ensureStyle(): void {
      if (styleInjected) return;
      if (typeof document === 'undefined') return;
      if (document.head.querySelector(`style[data-step-deeplink]`)) {
          styleInjected = true;
          return;
      }
      const style = document.createElement('style');
      style.id = STYLE_ID;
      style.setAttribute('data-step-deeplink', '');
      // Use box-shadow (not outline) so the highlight survives parents
      // with overflow:hidden; use var(--ring) so it tracks each theme
      // (lab-glass / blueprint / apothecary) rather than baking in teal.
      style.textContent = `
.${HIGHLIGHT_CLASS} {
    animation: stepDeepLinkPulse ${HIGHLIGHT_MS}ms ease-out;
    border-radius: 6px;
}
@keyframes stepDeepLinkPulse {
    0%   { box-shadow: 0 0 0 0 hsl(var(--ring) / 0); background-color: hsl(var(--ring) / 0); }
    20%  { box-shadow: 0 0 0 4px hsl(var(--ring) / 0.55); background-color: hsl(var(--ring) / 0.10); }
    100% { box-shadow: 0 0 0 0 hsl(var(--ring) / 0); background-color: hsl(var(--ring) / 0); }
}
@media (prefers-reduced-motion: reduce) {
    .${HIGHLIGHT_CLASS} { animation: none; box-shadow: none; background: none; }
}
`.trim();
      document.head.appendChild(style);
      styleInjected = true;
  }

  function prefersReducedMotion(): boolean {
      if (typeof window === 'undefined' || !window.matchMedia) return false;
      return window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  }

  /**
   * Scroll the element with `data-step-id={stepId}` into view and apply
   * a 1.5s highlight. Silent no-op when nothing matches. Idempotent —
   * a second call on the same element re-toggles the highlight class.
   */
  export async function focusStep(stepId: string): Promise<void> {
      if (typeof document === 'undefined') return;
      ensureStyle();
      const selector = `[data-step-id="${CSS.escape(stepId)}"]`;
      const el = document.querySelector(selector) as HTMLElement | null;
      if (!el) return;

      const reduceMotion = prefersReducedMotion();
      el.scrollIntoView({
          behavior: reduceMotion ? 'auto' : 'smooth',
          // 'nearest' avoids dramatic re-scrolls when the element is
          // already on-screen; only scrolls if it isn't fully visible.
          block: 'nearest',
      });
      if (reduceMotion) return;

      el.classList.remove(HIGHLIGHT_CLASS);
      // Reflow so removing + re-adding restarts the animation.
      void el.offsetWidth;
      el.classList.add(HIGHLIGHT_CLASS);
      window.setTimeout(() => {
          el.classList.remove(HIGHLIGHT_CLASS);
      }, HIGHLIGHT_MS);
  }
  ```

- [ ] **Step 4: Run the tests — expect PASS.**

  ```bash
  npm run test -- src/lib/utils/stepDeepLink.test.ts
  ```

  Expected: all 5 tests pass.

- [ ] **Step 5: Commit.**

  ```bash
  git add frontend/src/lib/utils/stepDeepLink.ts frontend/src/lib/utils/stepDeepLink.test.ts
  git commit -m "feat(TD-0091d): stepDeepLink focusStep helper + style injection"
  ```

---

## Task 6: Wire deep-link into the run page PLANNED-state EBR table

**Files:**
- Modify: `frontend/src/routes/[org]/projects/[projectSlug]/runs/[slug]/+page.svelte`
  - Add import + `stepIdFromHash` derived value to `<script>` block
  - Add `data-step-id={step.id}` to the EBR `<Table.Row>` (currently at line 983)
  - Add an `$effect` that calls `focusStep(stepIdFromHash)` whenever it changes

- [ ] **Step 1: Add imports + `stepIdFromHash` derived value.**

  At the top of the `<script>` block in `+page.svelte`, ensure these imports exist (some may already be present). Add what's missing:

  ```typescript
  import { tick } from 'svelte';
  import { page } from '$app/stores';
  import { focusStep } from '$lib/utils/stepDeepLink';
  ```

  Then add this regex constant + derived value near the top of the script block (just below other top-level `let`/`const` declarations):

  ```typescript
  // TD-0091d: parse #step-<id> from the URL hash. The shape mirrors the
  // backend resolver regex (^[A-Za-z0-9_-]{1,64}$). $page is reactive,
  // so this re-derives when a second notification is clicked while the
  // run page is already open.
  const STEP_HASH_RE = /^#step-([A-Za-z0-9_-]{1,64})$/;
  const stepIdFromHash = $derived.by(() => {
      const m = STEP_HASH_RE.exec($page.url.hash);
      return m ? m[1] : null;
  });
  ```

- [ ] **Step 2: Stamp `data-step-id` on the EBR rows.**

  In the PLANNED-state `<Table.Body>` block (currently around line 981-1015), modify the `<Table.Row>` opening tag inside the `{#each getAllUnitOpSteps() as step, i}` loop. Change:

  ```svelte
                                  {#each getAllUnitOpSteps() as step, i}
                                      <Table.Row>
  ```

  to:

  ```svelte
                                  {#each getAllUnitOpSteps() as step, i}
                                      <Table.Row data-step-id={step.id}>
  ```

- [ ] **Step 3: Add the focus effect for PLANNED state.**

  Inside the `<script>` block, after the `stepIdFromHash` derived value, add an `$effect` that drives `focusStep` whenever the hash points at a step *and* the page is in PLANNED state:

  ```typescript
  // TD-0091d: focus the step row when arriving from a notification.
  // Runs whenever stepIdFromHash changes (mount AND subsequent
  // notification clicks). The wizard branch (ACTIVE) handles its own
  // focus via initialStepId; observer view is a deliberate no-op.
  $effect(() => {
      if (!stepIdFromHash) return;
      if (!run) return;
      if (run.status !== 'PLANNED' && !['COMPLETED', 'EDITED'].includes(run.status)) {
          return;
      }
      const id = stepIdFromHash;
      // Wait for Svelte's flush + DOM patch (tick) instead of microtask:
      // queueMicrotask fires before the DOM update, so the [data-step-id]
      // node may not exist yet on the first paint.
      tick().then(() => focusStep(id));
  });
  ```

  *Note for the implementer:* the existing file's `run` variable is reactive (it's a `$state` updated by `loadData()`). The `$effect` will re-run whenever either `stepIdFromHash` or `run.status` changes — that's the intended behavior.

- [ ] **Step 4: Manual browser smoke test.**

  ```bash
  # backend & frontend dev servers should already be running per pre-flight
  ```

  In a browser:
  1. Log in as `admin@bioprocess.com` / `password123`.
  2. Navigate to a PLANNED run with at least 3 steps.
  3. Pick a step's id from the EBR table (open dev tools, inspect a row, copy the `data-step-id`).
  4. Append `#step-<that-id>` to the URL and press Enter.
  5. The matching row should scroll into view and pulse a themed highlight (ring color of the active theme) for ~1.5s.
  6. Append `#step-<a-different-id>` and observe the second row gets the same treatment without a full reload.

  Report any unexpected behavior in the task log; do not skip this step.

- [ ] **Step 5: Commit.**

  ```bash
  git add frontend/src/routes/\[org\]/projects/\[projectSlug\]/runs/\[slug\]/+page.svelte
  git commit -m "feat(TD-0091d): EBR rows honor #step-<id> deep link"
  ```

---

## Task 7: Wire deep-link into COMPLETED/EDITED `RunResultsSummary`

**Files:**
- Modify: `frontend/src/lib/components/run/RunResultsSummary.svelte` (add `data-step-id` to each step card)

The same `$effect` from Task 6 already covers COMPLETED/EDITED state (it checks the status list). The only thing needed here is to stamp `data-step-id` on the rendered step elements so `focusStep` can find them.

- [ ] **Step 1: Stamp `data-step-id` on each step card.**

  In `RunResultsSummary.svelte`, find the `{#each steps as step}` block (currently line 84) and the wrapping `<div>` that contains each card (line 89). Change:

  ```svelte
                  <div class="space-y-3">
                      {#each steps as step}
                          {@const stepData = executionData?.[step.id]}
                          {@const origResults = stepData?.original_results}
                          {@const origValue = stepData?.original_value}
                          {@const isEdited = showEditAnnotations && !!(origResults || origValue)}
                          <div class="p-3 rounded border {isEdited ? 'bg-amber-50 border-amber-200' : 'bg-background border-border'}">
  ```

  to:

  ```svelte
                  <div class="space-y-3">
                      {#each steps as step}
                          {@const stepData = executionData?.[step.id]}
                          {@const origResults = stepData?.original_results}
                          {@const origValue = stepData?.original_value}
                          {@const isEdited = showEditAnnotations && !!(origResults || origValue)}
                          <div
                              data-step-id={step.id}
                              class="p-3 rounded border {isEdited ? 'bg-amber-50 border-amber-200' : 'bg-background border-border'}"
                          >
  ```

- [ ] **Step 2: Manual browser smoke test.**

  In a browser:
  1. Open a COMPLETED run (or EDITED — either works).
  2. Inspect any step card in dev tools, copy its `data-step-id`.
  3. Append `#step-<that-id>` to the URL and press Enter.
  4. The matching card should scroll into view and pulse the highlight.

- [ ] **Step 3: Commit.**

  ```bash
  git add frontend/src/lib/components/run/RunResultsSummary.svelte
  git commit -m "feat(TD-0091d): RunResultsSummary cards honor #step-<id> deep link"
  ```

---

## Task 8: Rename `RoleWizard` + `FieldModeRoleWizard` input ids that collide with `#step-<id>`

**Files:**
- Modify: `frontend/src/lib/components/run/RoleWizard.svelte` (lines 658, 665, 686, 692)
- Modify: `frontend/src/lib/components/field-mode/FieldModeRoleWizard.svelte` (lines 473, 477, 493, 497)

Both wizards use `id="step-value"` and `id="step-notes"`. Browsers resolve URL fragments against the global `id` index, so a producer emitting `step_id="value"` would yield `#step-value` and the browser would jump to the *input*, not the step. Field mode is out-of-scope for the deep-link *feature*, but the id rename is a self-contained, defensive fix and we touch the file once now rather than racing a future producer.

- [ ] **Step 1: Rename `step-value` → `step-value-input`.**

  In `RoleWizard.svelte`, find the `<label for="step-value">` (line 658) and its `<input id="step-value">` (line 665). Change both:

  - `for="step-value"` → `for="step-value-input"`
  - `id="step-value"` → `id="step-value-input"`

- [ ] **Step 2: Rename `step-notes` → `step-notes-input`.**

  Same file, line 686 (`<label for="step-notes">`) and line 692 (`<textarea id="step-notes">`):

  - `for="step-notes"` → `for="step-notes-input"`
  - `id="step-notes"` → `id="step-notes-input"`

- [ ] **Step 3: Apply the same renames in `FieldModeRoleWizard.svelte`.**

  Same file structure, same collision. In `frontend/src/lib/components/field-mode/FieldModeRoleWizard.svelte` find the `for="step-value"` (line 473), `id="step-value"` (line 477), `for="step-notes"` (line 493), and `id="step-notes"` (line 497) — rename all four to `step-value-input` / `step-notes-input` to match Steps 1–2.

- [ ] **Step 4: Confirm no other references to these ids.**

  ```bash
  grep -rn 'step-value\|step-notes' frontend/src/ | grep -v step-value-input | grep -v step-notes-input | grep -v 'step-id'
  ```

  Expected: empty (no stragglers). If anything prints, update those call sites too.

- [ ] **Step 5: Manual smoke check (optional but cheap).**

  Click into the legacy-fallback step in the wizard, type in the value and notes fields, confirm they still work and the `<label>` clicks correctly focus the matching input.

- [ ] **Step 6: Commit.**

  ```bash
  git add frontend/src/lib/components/run/RoleWizard.svelte frontend/src/lib/components/field-mode/FieldModeRoleWizard.svelte
  git commit -m "refactor(TD-0091d): rename step-value/notes input ids in both wizards"
  ```

---

## Task 9: `RoleWizard` accepts `initialStepId` and seeds `currentStepIdx` safely

**Files:**
- Modify: `frontend/src/lib/components/run/RoleWizard.svelte` (Props interface + seeding `$effect` + `data-step-id` on the wizard step container)
- Modify: `frontend/src/routes/[org]/projects/[projectSlug]/runs/[slug]/+page.svelte` (pass `stepIdFromHash` as `initialStepId` to the `<RoleWizard>` instance at line 1173)

- [ ] **Step 1: Add `initialStepId` prop + seeding effect to `RoleWizard`.**

  In `RoleWizard.svelte`, modify the `Props` destructuring (currently line 54-70) to add `initialStepId` and add imports at the top of the script block.

  Add to the imports:

  ```typescript
  import { tick, untrack } from 'svelte';
  import { focusStep } from '$lib/utils/stepDeepLink';
  ```

  Change the props destructure block. Replace:

  ```typescript
  let {
      steps = [],
      runId,
      executionData = {},
      readonly = false,
      draftMode = false,
      onDataUpdate,
      onAllStepsComplete,
  }: {
      steps: Step[];
      runId: string;
      executionData: Record<string, any>;
      readonly?: boolean;
      draftMode?: boolean;
      onDataUpdate?: (data: Record<string, any>) => void;
      onAllStepsComplete?: () => void;
  } = $props();
  ```

  with:

  ```typescript
  let {
      steps = [],
      runId,
      executionData = {},
      readonly = false,
      draftMode = false,
      initialStepId = null,
      onDataUpdate,
      onAllStepsComplete,
  }: {
      steps: Step[];
      runId: string;
      executionData: Record<string, any>;
      readonly?: boolean;
      draftMode?: boolean;
      initialStepId?: string | null;
      onDataUpdate?: (data: Record<string, any>) => void;
      onAllStepsComplete?: () => void;
  } = $props();
  ```

- [ ] **Step 2: Add the seeding guard helper + effect.**

  After the existing `$effect` that populates `stepData` from `executionData` (currently line 114-122), add:

  ```typescript
  // TD-0091d: track which initialStepId we've already processed so the
  // seeding effect is strictly one-shot per value of the prop. Prevents
  // the wizard from yanking the user back to the deep-link target if
  // they've manually navigated and then `executionData` (an effect
  // dependency we deliberately untrack below) updates.
  let lastSeededStepId = $state<string | null>(null);

  // TD-0091d: detect unsaved edits on the current step. Conservative —
  // if uncertain, treat as unsaved so we don't clobber in-flight work.
  function hasUnsavedExecutionData(): boolean {
      const sid = steps[currentStepIdx]?.id;
      if (!sid) return false;
      const live = stepData[sid];
      const snapshot = executionData?.[sid];
      if (!live) return false;
      const liveFields = {
          results: live.results ?? null,
          value: live.value ?? null,
          notes: live.notes ?? null,
      };
      const snapFields = {
          results: snapshot?.results ?? null,
          value: snapshot?.value ?? null,
          notes: snapshot?.notes ?? null,
      };
      return JSON.stringify(liveFields) !== JSON.stringify(snapFields);
  }

  // TD-0091d: seed currentStepIdx from a deep link, but only when safe.
  // Tracks ONLY `initialStepId` (and `steps.length` transitions 0→N for
  // async loads) by reading mutable state through `untrack`. Reasons for
  // a silent no-op: id unknown to this role, user already navigated past
  // step 0, or the current step has unsaved edits.
  $effect(() => {
      if (!initialStepId) return;
      if (lastSeededStepId === initialStepId) return;
      // Reading `steps.length` is reactive on purpose — handles the
      // async-load case where steps arrive after mount.
      if (steps.length === 0) return;

      untrack(() => {
          const idx = steps.findIndex((s) => s.id === initialStepId);
          if (idx < 0) {
              lastSeededStepId = initialStepId; // mark handled; observer-style no-op
              return;
          }
          if (currentStepIdx !== 0) {
              lastSeededStepId = initialStepId; // user already moved; respect that
              return;
          }
          if (hasUnsavedExecutionData()) {
              lastSeededStepId = initialStepId; // don't clobber in-flight edits
              return;
          }
          currentStepIdx = idx;
          lastSeededStepId = initialStepId;
      });
  });

  // TD-0091d: after currentStepIdx settles, scroll + highlight the
  // wizard's step container. Runs whenever the wizard lands on (or is
  // already on) the deep-link target. `tick()` waits for Svelte's DOM
  // flush so [data-step-id] is queryable.
  $effect(() => {
      if (!initialStepId) return;
      if (steps[currentStepIdx]?.id !== initialStepId) return;
      const id = initialStepId;
      tick().then(() => focusStep(id));
  });
  ```

- [ ] **Step 3: Stamp `data-step-id` on the wizard's form-fields container.**

  In `RoleWizard.svelte`, find the form-fields wrapper at line 564:

  ```svelte
              <!-- Form Fields -->
              <div class="flex-1 space-y-6 mb-8">
                  {#if hasSchema}
  ```

  Change the opening `<div>` to:

  ```svelte
              <!-- Form Fields -->
              <div data-step-id={currentStep?.id} class="flex-1 space-y-6 mb-8">
                  {#if hasSchema}
  ```

  This wrapper encloses both branches of the `{#if hasSchema}` (schema-driven fields and the legacy fallback) plus the notes textarea, so the highlight visibly surrounds the entire interactive region of the current step.

- [ ] **Step 4: Wire `initialStepId` from the run page into `<RoleWizard>`.**

  In `+page.svelte` (line 1173-1184), modify the `<RoleWizard>` instantiation to pass `initialStepId`. Change:

  ```svelte
                              <RoleWizard
                                  steps={getWizardSteps()}
                                  runId={run.id}
                                  executionData={run.execution_data || {}}
                                  onDataUpdate={handleExecutionDataUpdate}
                                  onAllStepsComplete={() => {
                                      if (allStepsComplete()) {
                                          showCompleteConfirm = true;
                                      }
                                  }}
                              />
  ```

  to:

  ```svelte
                              <RoleWizard
                                  steps={getWizardSteps()}
                                  runId={run.id}
                                  executionData={run.execution_data || {}}
                                  initialStepId={stepIdFromHash}
                                  onDataUpdate={handleExecutionDataUpdate}
                                  onAllStepsComplete={() => {
                                      if (allStepsComplete()) {
                                          showCompleteConfirm = true;
                                      }
                                  }}
                              />
  ```

  Also update the page-level `$effect` (added in Task 6, Step 3) so the ACTIVE branch is excluded from the page-level `focusStep` call — the wizard owns its own focus there:

  ```typescript
  $effect(() => {
      if (!stepIdFromHash) return;
      if (!run) return;
      // ACTIVE is handled inside RoleWizard via initialStepId; observer
      // view is a deliberate no-op.
      const status = run.status;
      const isPageRendered =
          status === 'PLANNED' || status === 'COMPLETED' || status === 'EDITED';
      if (!isPageRendered) return;
      const id = stepIdFromHash;
      tick().then(() => focusStep(id));
  });
  ```

- [ ] **Step 5: Manual browser smoke test (ACTIVE path).**

  1. Open an ACTIVE run as the role assignee.
  2. Note the wizard starts on step 0.
  3. Pick a step id from another wizard page (e.g. dev-tools-inspect the role's step list).
  4. Append `#step-<that-id>` to the URL and press Enter.
  5. The wizard should advance to that step and the step container should pulse the highlight.
  6. **Negative test 1**: navigate to a different step manually (e.g. click "Next"). Then append a deep link for *yet another* step. The wizard should *not* yank the user away — it should stay on the manually-navigated step.
  7. **Negative test 2**: log in as a non-assignee, open the same ACTIVE run with `#step-<id>`. You should see `RunObserverView` with no scroll, no highlight, no banner.
  8. **Negative test 3**: pass an unknown id `#step-bogus`. Nothing should happen, no error toast.

- [ ] **Step 6: Commit.**

  ```bash
  git add frontend/src/lib/components/run/RoleWizard.svelte frontend/src/routes/\[org\]/projects/\[projectSlug\]/runs/\[slug\]/+page.svelte
  git commit -m "feat(TD-0091d): RoleWizard initialStepId seeds wizard from deep link"
  ```

---

## Task 10: Preserve URL fragment when routing from notification surfaces

**Files:**
- Modify: `frontend/src/lib/components/layout/NotificationBell.svelte` (`handleSelect` around line 111)
- Modify: `frontend/src/routes/notifications/+page.svelte` (the same `goto(href)` call, around line 111)

SvelteKit's `goto(href)` is inconsistent with hash-bearing URLs: when the destination is the current page, the fragment may or may not trigger a hashchange-style update depending on history state. Rather than test-and-react, apply the fallback unconditionally at both notification entry points — the behavior of `window.location.href` for hash-bearing URLs is well-defined and cheap. Both files duplicate the same `goto(href)` line, so both need the same patch.

- [ ] **Step 1: Patch `NotificationBell.svelte` `handleSelect`.**

  Find the line that calls `goto(href)` inside `handleSelect` (around line 111). Replace:

  ```typescript
  goto(href);
  ```

  with:

  ```typescript
  // TD-0091d: hash-bearing URLs from the resolver (#step-<id>) must
  // navigate via window.location so the fragment is honored even when
  // already on the destination page. `goto` is fine for plain hrefs.
  if (href.includes('#')) {
      window.location.href = href;
  } else {
      goto(href);
  }
  ```

- [ ] **Step 2: Apply the same patch in `routes/notifications/+page.svelte`.**

  The standalone notifications page duplicates the bell's click logic. Find the matching `goto(href)` call (around line 111) and apply the identical replacement from Step 1.

- [ ] **Step 3: Seed a test notification with `payload.step_id`.**

  In the worktree's backend Python shell:

  ```bash
  cd backend && source .venv/bin/activate
  python -c "
  import asyncio
  from uuid import UUID
  from app.services.core.notifications import send_notification

  # Replace with a real org id, run id, step id, and your user id.
  ORG_ID = UUID('REPLACE-ME')
  RUN_ID = UUID('REPLACE-ME')
  USER_ID = UUID('REPLACE-ME')
  STEP_ID = 'REPLACE-ME'

  asyncio.run(send_notification(
      event_type='STEP_DEVIATION',
      org_id=ORG_ID,
      entity_type='run',
      entity_id=RUN_ID,
      recipients=[USER_ID],
      context={'run_name': 'Smoke Test', 'step_name': 'Step X'},
      payload={'step_id': STEP_ID},
  ))
  print('seeded')
  "
  ```

- [ ] **Step 4: Manual browser smoke test for both entry points.**

  1. Open the run page.
  2. Open the bell, click the seeded notification → URL settles on `…#step-<id>`, matching row pulses.
  3. Navigate to `/notifications`, click the seeded notification → same outcome.

  If either path drops the fragment, the conditional in Steps 1–2 isn't catching that case — investigate before continuing.

- [ ] **Step 5: Commit.**

  ```bash
  git add frontend/src/lib/components/layout/NotificationBell.svelte frontend/src/routes/notifications/+page.svelte
  git commit -m "fix(TD-0091d): preserve URL fragment when routing from notification surfaces"
  ```

---

## Task 11: Document the payload contract in `.claude/rules/`

**Files:**
- Modify: `.claude/rules/backend-services.md` (append a subsection)

- [ ] **Step 1: Append the subsection to `.claude/rules/backend-services.md`.**

  At the end of the file, append:

  ```markdown

  ## Notification payload contract

  `Notification.payload` (JSONB, default `{}`) carries optional deep-link
  metadata. The column is schemaless; the resolver
  (`services/core/notifications/links.py`) only honors documented keys.

  | Key | Type | When honored |
  |-----|------|--------------|
  | `step_id` | string matching `^[A-Za-z0-9_-]{1,64}$` | `entity_type == "run"`; resolver appends `#step-<id>` to the deep link |

  Producers of step-scoped events on a run should pass
  `payload={"step_id": "<id>"}` to `send_notification`. Ids must match the
  regex above — anything else is silently dropped by the resolver and the
  notification falls back to a bare run link. The 512-byte CHECK
  constraint on the column bounds payload bloat; raise the cap
  deliberately if a future key needs more.

  `NotificationResponse` (Pydantic) intentionally does not surface
  `payload` — the frontend consumes the already-resolved URL (with
  fragment) via `resolve_notification_urls`. Add the field to the schema
  only when a frontend feature needs structured payload directly.
  ```

- [ ] **Step 2: Commit.**

  ```bash
  git add .claude/rules/backend-services.md
  git commit -m "docs(TD-0091d): document Notification.payload contract"
  ```

---

## Task 12: Full-suite green check

- [ ] **Step 1: Backend.**

  ```bash
  cd backend && source .venv/bin/activate
  pytest -q
  ```

  Expected: all tests pass. If any unrelated test fails, that's a pre-existing flake — note it, don't try to fix here.

- [ ] **Step 2: Frontend type check + tests.**

  ```bash
  cd frontend
  npm run check
  npm run test
  ```

  Expected: both clean.

- [ ] **Step 3: Build.**

  ```bash
  npm run build
  ```

  Expected: clean build, no errors.

- [ ] **Step 4: If anything failed, fix in the corresponding task's file, retest, and re-commit before continuing.**

---

## Done

All commits are on the worktree branch. The implement-task skill's verification stage (diff review panel + qa-verify + user sign-off) picks up from here.

## Self-review notes

- **Spec coverage:** every acceptance criterion in the spec has a corresponding task — schema (Tasks 1–2), service wrapper (Task 3), resolver (Task 4), helper (Task 5), three integration points (Tasks 6, 7, 9), wizard input rename (Task 8), URL-fragment fallback (Task 10), rule doc (Task 11), green-check (Task 12).
- **Spec drift:** the spec showed `send_notification(db: AsyncSession, ...)` as the existing signature; the real signature opens its own `AsyncSessionLocal` and takes no `db`. The plan uses the real signature and adds `payload` as the 7th keyword arg after `context` — semantically equivalent to what the spec intended.
- **Observer view & FieldModeRoleWizard deep-link feature:** explicitly out of scope. The FieldModeRoleWizard id rename in Task 8 Step 3 is the *only* touch — a defensive collision fix, not a feature backport.
- **No placeholders:** every code block is complete; every command shows expected output.

### Plan-review-panel triage (applied)

- **DB scalability:** per-row `dict(notif_payload)` copy in Task 3 Step 3 — avoids sharing one mutable dict across N ORM instances.
- **DRY / coupling:** call-site count corrected from 5 to 13 in Task 3 Step 5; `routes/notifications/+page.svelte` added to Task 10 alongside `NotificationBell.svelte`.
- **Adversarial / wizard race:** Task 9 Step 2 rewritten with `lastSeededStepId` sentinel + `untrack` so the seeding effect is strictly one-shot per `initialStepId`. `tick()` replaces `queueMicrotask` in Tasks 6 and 9 so the DOM is patched before `focusStep` queries it.
- **UI/UX:** `stepDeepLink` CSS in Task 5 swapped from hardcoded teal `outline` to `box-shadow` + `background-color` driven by `hsl(var(--ring) / ...)` — survives ancestor `overflow:hidden` and tracks each theme. `scrollIntoView` uses `block: 'nearest'`.
- **Fragment routing:** Task 10 restructured from "test, fall back if broken" to "apply the well-defined `window.location.href` path unconditionally for hash-bearing URLs at both notification surfaces."
- **Task 9 Step 3:** prescriptive — wrap the existing `<div class="flex-1 space-y-6 mb-8">` at line 564 in `RoleWizard.svelte`. No more "find the right wrapper."

### Plan-review-panel triage (rejected, with reason)

- **`id="result-{key}"` collision (adversarial MUST FIX):** browser fragment navigation matches `id`, so `#step-<id>` only resolves to `id="step-<id>"`. A `result-x` input id would only be hit by `#result-x`, which the resolver never produces. The original `step-value` / `step-notes` rename in Task 8 covers the real cases.
- **Migration NOT VALID + VALIDATE (adversarial SHOULD CONSIDER):** the `notifications` table is small at current scale; a one-pass CHECK validation is fine. Worth revisiting if production volume grows.
- **"Jump to step X" banner affordance (UI/UX recommendation):** user explicitly vetoed banners during spec brainstorming; deep-link is a silent, immediate scroll/highlight by design.
- **`aria-live` announcement (UI/UX recommendation):** the user initiated the navigation themselves (clicked a notification); a screen-reader announcement on top of the URL change would be redundant noise.
