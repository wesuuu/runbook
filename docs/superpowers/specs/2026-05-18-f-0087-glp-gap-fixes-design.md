# F-0087 Phase 2 — GLP Gap Fixes (Design)

**Ticket**: F-0087 — GLP Protocol Data Model Audit + Sign-Off, SOP & Batch Record Refinements
**Audit input**: `docs/glp_audit_2026.md` (Section P scope)
**Author**: Wesley Uykimpang (with Claude)
**Date**: 2026-05-18
**Status**: Design — pending user review before writing-plans

---

## Purpose

Implement the GLP gap fixes from audit Section P that land under F-0087. Scope is bounded by Section P; sibling tickets (training, materials, deviations, environmental, samples, calibration history, audit-log sweep) are out of scope and not addressed here.

## Locked decisions (from prior brainstorming)

- **GLP only.** No GMP / Part 211 / ICH Q7 framing.
- **Sign-off model**: unified `GlpSignoff` child table that **replaces both** `ProtocolApprovalEvent` (F-0066) and the originally-proposed standalone `RunSignoff`. Partition by FK: `protocol_id IS NOT NULL XOR run_id IS NOT NULL`. One enum, one service, one validator suite across both contexts. (Auditor-preference reasons in audit Q-section.)
- **Signature image binding**: copy `User.signature_full_path` to a record-scoped path **at sign time** (satisfies §11.70). Storing only `signer_id` would allow retroactive re-binding if the user re-uploads a signature.
- **`glpSettings` location**: top-level key in `Protocol.graph` JSONB, mirrored into `ProtocolVersion.graph` snapshots automatically. Zero migration; no first-class column.
- **Reopen UX**: single-button reopen-with-reason. After QAU sign-off, `COMPLETED → EDITED` is blocked unless `POST /runs/{id}/reopen {reason}` is called, which invalidates **all active sign-offs** on the run (sets `invalidated_at`) and writes an `AuditLog` entry. Every role that signed must re-sign after edits land.
- **Outcome ↔ QAU coupling**: separate fields, co-located in UI. Operator sets `Run.outcome` at completion; QAU sign-off attests to outcome but doesn't set it.
- **GLP-conformant role names.** Single `GlpRole` enum used across protocol approval and run sign-off: `SPONSOR`, `STUDY_DIRECTOR`, `QAU`, `OPERATOR`. Existing product roles (`OrgRole`, `TeamRole`, `ProtocolRole`) are unchanged.
- **Request workflow.** F-0066's `ProtocolApprovalRequest` is renamed to `GlpSignoffRequest` (cosmetic rename, no functional change) in F-0087 scope. Run-signoff request *generation* (auto-create review tasks for SD/QAU when a run completes, with assignment + notifications + dashboard) is deferred to sibling ticket `86e1ef2tv` — "Run sign-off review queue."

## Scope (11 buckets)

| # | Bucket | Audit IDs |
|---|---|---|
| 1 | Unified `GlpSignoff` table replacing `ProtocolApprovalEvent` + new run signoffs; endpoints + UI | H2, H3, H4, K4, K5 |
| 2 | F-0066 refactor — protocol approval reads/writes via `GlpSignoff`; cosmetic rename `ProtocolApprovalRequest` → `GlpSignoffRequest` | H5, K2 |
| 3 | Per-step reviewer endpoint + UI | H1 |
| 4 | GLP Settings panel on Protocol Editor | drives H3/H4/D1/K3/C3/E* opt-ins |
| 5 | Reason-for-change on EDITED transitions | I4 |
| 6 | Run timestamps (Run.started_at, completed_at, per-step started_by_user_id) | A4, G4, G5 |
| 7 | Equipment refinement (serial, calibration fields) | B1, B2 |
| 8 | Run outcome block (Run.outcome, outcome_notes) | L5 |
| 9 | Immutability gate (block edits after QAU sign-off; reopen-with-reason) | J1 |
| 10 | Deprecation shim — old `POST /protocols/{id}/approval-events` route delegates to new unified endpoint for one release | H5, K2 |
| 11 | Template default cleanup | N1–N5 |

Bucket 2 (F-0066 refactor) is the highest-regression-risk piece because F-0066 just shipped. Requires thorough integration-test coverage; planned for first or second slot in implementation order so it surfaces issues early.

## Out of scope (explicit deferrals to sibling F-tickets)

- **Run sign-off review queue** — `86e1ef2tv` (auto-generated request rows, assignee picker, "awaiting your review" dashboard, notifications for runs needing SD/QAU sign-off). F-0087 lets SD/QAU sign by navigating to a completed run; the queue/notification workflow lands separately.
- Training records (A3)
- MaterialLot / characterization / COA (C1–C4)
- Deviation system (E1–E5)
- Environmental capture (D1)
- Sample identity (F1)
- Calibration history table (B3) — only the snapshot fields `last_calibrated_at` / `calibration_due_at` land in F-0087
- Audit-log coverage sweep (I5)
- Documentation-only boundary items (B6, D2, F2, F3, I6, J3, M5, M6)

---

## Architecture

### Data model (backend/app/models/science.py)

#### New table — `GlpSignoff` (unifies protocol approval + run sign-off)

```python
class GlpRole(str, Enum):
    SPONSOR = "SPONSOR"                # §58.10, §58.120(a) — approves protocol
    STUDY_DIRECTOR = "STUDY_DIRECTOR"   # §58.33 overall conduct
    QAU = "QAU"                         # §58.35 quality assurance unit
    OPERATOR = "OPERATOR"               # §58.29 study personnel

class GlpSignoffAction(str, Enum):
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    REQUESTED_CHANGES = "REQUESTED_CHANGES"

class GlpSignoff(Base, UUIDMixin, TimestampMixin):
    """Unified GLP signature event. Replaces ProtocolApprovalEvent
    (F-0066) and supersedes the originally-proposed RunSignoff. Used for
    both protocol approvals (pre-execution) and run sign-offs (during /
    post-execution). Partition by FK: exactly one of protocol_id / run_id
    is set."""

    __tablename__ = "glp_signoffs"

    # Polymorphic parent
    protocol_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("protocols.id", ondelete="CASCADE"), nullable=True
    )
    run_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("runs.id", ondelete="CASCADE"), nullable=True
    )

    role: Mapped[str] = mapped_column(String, nullable=False)
    action: Mapped[str] = mapped_column(String, nullable=False)

    signer_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    attestation: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    signed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    signature_image_path: Mapped[Optional[str]] = mapped_column(String, nullable=True)

    # Optional link to a pending request (F-0066 / sibling 86e1ef2tv)
    signoff_request_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("glp_signoff_requests.id"), nullable=True
    )

    # Reopen-and-resign audit trail
    invalidated_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    invalidated_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    invalidated_by_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("users.id"), nullable=True
    )

    __table_args__ = (
        # Exactly one parent set
        CheckConstraint(
            "(protocol_id IS NOT NULL AND run_id IS NULL) OR "
            "(protocol_id IS NULL AND run_id IS NOT NULL)",
            name="ck_glp_signoff_scope",
        ),
        # Role / action enum enforcement
        CheckConstraint(
            "role IN ('SPONSOR','STUDY_DIRECTOR','QAU','OPERATOR')",
            name="ck_glp_signoff_role",
        ),
        CheckConstraint(
            "action IN ('APPROVED','REJECTED','REQUESTED_CHANGES')",
            name="ck_glp_signoff_action",
        ),
        # Role-context fit
        CheckConstraint(
            "(protocol_id IS NULL) OR (role IN ('SPONSOR','STUDY_DIRECTOR','QAU'))",
            name="ck_protocol_signoff_roles",
        ),
        CheckConstraint(
            "(run_id IS NULL) OR (role IN ('OPERATOR','STUDY_DIRECTOR','QAU'))",
            name="ck_run_signoff_roles",
        ),
        # APPROVED requires attestation + image (§11.50, §11.70)
        CheckConstraint(
            "(action != 'APPROVED') OR "
            "(attestation IS NOT NULL AND signature_image_path IS NOT NULL)",
            name="ck_approved_requires_attestation",
        ),
        # Only one active APPROVED sign-off per (entity, role)
        Index(
            "ux_glp_signoff_active_protocol",
            "protocol_id", "role",
            unique=True,
            postgresql_where=(
                "protocol_id IS NOT NULL AND action='APPROVED' "
                "AND invalidated_at IS NULL"
            ),
        ),
        Index(
            "ux_glp_signoff_active_run",
            "run_id", "role",
            unique=True,
            postgresql_where=(
                "run_id IS NOT NULL AND action='APPROVED' "
                "AND invalidated_at IS NULL"
            ),
        ),
    )
```

**Rationale:**
- Single table reflects GLP's view that the same people in the same roles sign at multiple study phases — only the *moment* differs.
- Partial unique indexes scope uniqueness per entity (protocol vs run) so we don't accidentally cross-block. Both filter on `action='APPROVED'` so a REJECTED row doesn't block a later APPROVED row at the same (entity, role).
- `signature_image_path` stores a record-scoped copy made at sign time (`uploads/{org_id}/signoffs/{signoff_id}.png`). User re-uploading their signature later does not retroactively change past records (§11.70).
- `signer_id` uses `ON DELETE RESTRICT`: a user with sign-offs cannot be hard-deleted; org admins can deactivate but not erase. Required for §11.70 link permanence.
- `signoff_request_id` is nullable: protocol approvals reference a `GlpSignoffRequest` (F-0066 flow preserved); run sign-offs leave it NULL in F-0087 and start populating once sibling `86e1ef2tv` ships request generation for runs.

#### Migration of existing F-0066 data

1. Create `glp_signoffs` table with the schema above.
2. Copy every row from `protocol_approval_events` into `glp_signoffs` mapping:
   - `protocol_id` → `protocol_id`
   - `approval_request_id` → `signoff_request_id`
   - `signer_user_id` → `signer_id`
   - `action` → `action` (already matches enum values)
   - `signature_statement` → `attestation`
   - `signed_at` → `signed_at`
   - `role` defaults to `QAU` for all existing rows (no stage field today; QAU is the safe semantic default since F-0066 is single-stage QA-style review)
   - `signature_image_path` = NULL (existing F-0066 rows did not snapshot the image; the CHECK constraint `ck_approved_requires_attestation` is added as `NOT VALID` initially and validated only against new rows — see migration script note below)
3. Rename `protocol_approval_requests` → `glp_signoff_requests` (cosmetic; columns unchanged).
4. Drop `protocol_approval_events` after F-0087 has shipped and a release window has passed.

**CHECK-constraint note:** `ck_approved_requires_attestation` is created with `NOT VALID` so legacy rows missing `signature_image_path` don't block migration. New rows must satisfy it. A follow-up backfill (out of F-0087 scope) can copy historical signatures into the record-scoped paths and then `VALIDATE CONSTRAINT`.

#### Run additions

| Column | Type | Set when |
|---|---|---|
| `started_at` | `DateTime(timezone=True)` nullable | PLANNED → ACTIVE transition |
| `completed_at` | `DateTime(timezone=True)` nullable | ACTIVE → COMPLETED transition |
| `outcome` | `String` nullable (enum: `COMPLETED_NORMAL` / `COMPLETED_WITH_DEVIATIONS` / `ABORTED`) | Operator selects at completion |
| `outcome_notes` | `Text` nullable | Operator may include free-text |

`completed_by_id` is **not** added as a column — it rolls into `GlpSignoff(run_id=X, role=OPERATOR)`.

#### Equipment additions

| Column | Type |
|---|---|
| `serial_number` | `String` nullable |
| `last_calibrated_at` | `DateTime(timezone=True)` nullable |
| `calibration_due_at` | `DateTime(timezone=True)` nullable |
| `calibration_certificate_path` | `String` nullable |

#### Protocol approval (formerly ProtocolApprovalEvent)

No longer a separate table — protocol approvals are `GlpSignoff` rows with `protocol_id` set and `role IN ('SPONSOR','STUDY_DIRECTOR','QAU')`. The historical `stage` enum proposed in earlier brainstorming is replaced by the unified `role` column on `GlpSignoff`.

`GlpSignoffRequest` (renamed from `ProtocolApprovalRequest`) is unchanged functionally and continues to drive the protocol-approval workflow. Run-side request generation is deferred to sibling `86e1ef2tv`.

#### JSONB additions (no migration; documented in `.claude/rules/backend-models.md`)

- `execution_data[step_id].started_by_user_id` — set when `started_at` is written
- `execution_data[step_id].edit_reason` — required when EDITED transition modifies the step
- `Protocol.graph.glpSettings` — top-level key:
  ```json
  {
    "glpSettings": {
      "require_study_director": false,
      "require_qau": true,
      "operator_attestation_text": "I performed this run according to the approved protocol and certify the recorded values are accurate.",
      "study_director_attestation_text": "I confirm this run was conducted according to the approved protocol.",
      "qau_attestation_text": "I have inspected this run record and confirm it complies with the approved protocol and applicable SOPs.",
      "step_attestation_text": "I performed this step according to the approved protocol and certify the recorded values."
    }
  }
  ```

Attestation text strings are defaults the protocol author can edit per protocol.

### Validators (services/runs/, services/protocols/)

Following the `validate_X` + `assert_no_X_errors` pattern from `.claude/rules/backend-services.md`:

| Function | Module | Behavior |
|---|---|---|
| `assert_no_unjustified_edit_errors(execution_data_delta)` | `services/runs/validation.py` | Raises 400 with `{"error": "EDIT_REASON_REQUIRED", "issues": [...]}` if any modified step lacks `edit_reason` |
| `assert_run_can_close(run, glp_settings)` | `services/runs/validation.py` | Raises 400 if required sign-offs (per `glpSettings.require_*`) are missing for COMPLETED |
| `assert_qau_independent(entity_id, entity_type, signer_id)` | `services/signoffs/validation.py` | Raises 400 if a QAU signer is also the OPERATOR (run) or STUDY_DIRECTOR (run or protocol) on the same entity (§58.35 independence). Works for both protocols and runs. |
| `validate_signoff_role_assignable(entity, user, role)` | `services/signoffs/validation.py` | Verifies user has permission to sign in this role. Run context combines project permissions and `RunRoleAssignment`; protocol context uses project permissions only. |
| `assert_attestation_and_image_present(signoff)` | `services/signoffs/validation.py` | Raises 400 if `action=APPROVED` and `attestation IS NULL` or `signature_image_path IS NULL` (K2, K4). Replaces the old protocol-only `assert_signature_statement_present`. |
| `assert_can_edit_completed_run(run)` | `services/runs/validation.py` | Raises 400 if active QAU sign-off exists; client must call `POST /reopen` first (J1) |

A new `services/signoffs/` module hosts the cross-context validators. The `services/runs/` and `services/protocols/` modules import from it. Frontend mirrors land in `frontend/src/lib/runValidation.ts` and `protocolValidation.ts` (existing files) plus a new `signoffValidation.ts` for the shared rules.

### Endpoints (backend/app/api/endpoints/)

URLs stay split per entity for clarity and for permission gating; both call into the same `services/signoffs/` service.

| Verb + path | Body | Action |
|---|---|---|
| `POST /runs/{id}/signoffs` | `{role, action, attestation_override?, signoff_request_id?}` | Run sign-off. Calls shared `validate_signoff_role_assignable`, `assert_qau_independent`, `assert_attestation_and_image_present`. Copies `User.signature_full_path` to record-scoped path on APPROVED. Inserts `GlpSignoff` row with `run_id` set. Writes `AuditLog`. |
| `POST /protocols/{id}/signoffs` | `{role, action, attestation_override?, signoff_request_id?}` | Protocol approval. Same service, same validators. Replaces F-0066's `POST /protocols/{id}/approval-events`. Old route preserved as a deprecation shim that delegates to the new one for one release. |
| `POST /runs/{id}/steps/{step_id}/review` | `{}` | Per-step reviewer (H1). Sets `execution_data[step_id].reviewed_by_user_id` + `reviewed_at`. Writes `AuditLog`. Not a `GlpSignoff` row — step-level review stays in JSONB for granularity. |
| `POST /runs/{id}/reopen` | `{reason}` | Calls `assert_can_edit_completed_run` (inverse — must currently be blocked). Invalidates **all active sign-offs** on the run. Writes `AuditLog`. |
| `PATCH /runs/{id}/state` (existing, extended) | `{state: "EDITED", edit_reasons: {step_id: reason}}` | Calls `assert_no_unjustified_edit_errors`. |
| `POST /runs/{id}/complete` (new wrapper) | `{outcome, outcome_notes?}` | Sets `Run.outcome`, transitions ACTIVE → COMPLETED, sets `completed_at`. Calls `assert_run_can_close`. |
| `PATCH /equipment/{id}` (existing, extended) | `{serial_number?, last_calibrated_at?, calibration_due_at?, calibration_certificate_path?}` | Equipment field updates. |
| `PUT /protocols/{id}` (existing, extended) | `{graph: {..., glpSettings: {...}}}` | No new endpoint; `glpSettings` is just another key in the graph payload. |

### Template engine (backend/app/services/protocols/template_engine.py)

New variables added to `KNOWN_VARIABLES`:

| Variable | Source | Notes |
|---|---|---|
| `signoffs.operator`, `signoffs.study_director`, `signoffs.qau` | Latest active `GlpSignoff` per role with `run_id=this run` and `action=APPROVED` | Each is `{name, signature_image, attestation, signed_at, initials}`. Signature swap pulls from `GlpSignoff.signature_image_path` (already record-scoped), not from `User.*`. |
| `protocol_approvals.sponsor`, `protocol_approvals.study_director`, `protocol_approvals.qau` | Latest active `GlpSignoff` per role with `protocol_id=this protocol` and `action=APPROVED` | Same shape as run sign-offs. Replaces the old per-event list rendering from F-0066. |
| `equipment[i].serial_number`, `.calibration_due_at`, `.calibration_status` | `Equipment` columns | `calibration_status` derived: "OK" / "OVERDUE" / "UNKNOWN" |
| `run.outcome`, `run.outcome_notes` | `Run` columns | Conditional rendering |
| `run.started_at`, `run.completed_at` | `Run` columns | Replace UI-inferred values |
| `step.edit_reason` | `execution_data[step_id].edit_reason` | Appended to the strikethrough RichText annotation (`"42 → 50 (corrected unit conversion, WU 2026-05-18)"`) |
| `step.actual_value_block` | Composed | Stacked-RichText: target / unit / recorded / Δ-flag / initials / timestamp (replaces N3 raw `actual_value`) |

### Frontend (frontend/src/lib/components/)

Per the bucket placement rule in `conventions.md`:

| Component | Path | Purpose |
|---|---|---|
| `GlpSettingsPanel.svelte` | `protocol/` | Inspector-replacing view when no node selected; toggles + attestation textareas |
| `SignoffBlock.svelte` | `shared/` | Reused by both run-completion and protocol-approval surfaces. Lists required sign-offs per role; each row has a "Sign as <role>" button. Props: `entityType`, `entityId`, `requiredRoles`, `attestationDefaults`. |
| `SignoffModal.svelte` | `shared/` | Attestation preview + signature confirmation modal. Shared between protocols and runs. |
| `RunReopenModal.svelte` | `run/` | Required `reason` field; warns sign-off invalidation; triggered from completed-run view |
| `RunEditReasonPrompt.svelte` | `run/` | Modal inserted into existing step-edit save flow; collects `edit_reason` per modified step |
| Protocol approval page update | `protocol/` | Existing approval surface migrated to consume `SignoffBlock`; removes F-0066's bespoke approval-event UI |
| Equipment fields | extend existing equipment edit surface | Add serial_number + calibration inputs |

Frontend validation utilities:
- `frontend/src/lib/runValidation.ts` — `validateCanCloseRun(run, glpSettings)` mirror of backend `assert_run_can_close`; disables close button pre-flight

### Template default cleanup (backend/app/services/documents/templates/)

| ID | File | Action |
|---|---|---|
| N1 | `batch_record_default.docx` | Strip `target_yield` cell from header table |
| N2 | `sop_default.docx` | Remove all run-specific fields (`{{ run.* }}`, `lot_number`, `batch_number`, `started_at`, `completed_at`, `started_by`, `execution_data`); keep protocol-level fields only |
| N3 | `batch_record_default.docx` | Replace `actual_value` cell with `{{r step.actual_value_block }}` |
| N4 | both | Scan unzipped DOCX XML for `pixelsPerHour` / `layout` references; strip if present |
| N5 | both | Verify `figure_refs` resolves through `figure_map`; no raw IDs leak |

DOCX edits land alongside golden-file regression tests (`tests/integration/documents/test_template_rendering.py`).

## Data flow

```
Run completion + sign-off (run context)
  Operator finishes last step in RunEditMode
    → frontend validateCanCloseRun() passes
    → POST /runs/{id}/complete {outcome, outcome_notes}
    → backend assert_run_can_close()
      → if OPERATOR signoff missing: 400 SIGNOFF_REQUIRED (OPERATOR)
    → 200; transitions ACTIVE → COMPLETED; sets Run.completed_at
    → UI surfaces SignoffBlock (shared) with required roles per glpSettings

  Operator clicks "Sign as Operator"
    → SignoffModal (shared) renders with operator_attestation_text
    → POST /runs/{id}/signoffs {role: OPERATOR}
    → backend validate_signoff_role_assignable() passes
    → assert_attestation_and_image_present() passes
    → copy User.signature_full_path → uploads/{org}/signoffs/{signoff_id}.png
    → INSERT GlpSignoff(run_id=X, role=OPERATOR, action=APPROVED, ...)
    → AuditLog
    → 201

  QAU user signs
    → POST /runs/{id}/signoffs {role: QAU}
    → assert_qau_independent() — signer_id must not match OPERATOR or STUDY_DIRECTOR signer
    → same flow as above; INSERT GlpSignoff(run_id=X, role=QAU, ...)
    → record now satisfies require_qau

  Operator later opens completed run, sees results need correction
    → clicks "Reopen for correction"
    → RunReopenModal collects reason
    → POST /runs/{id}/reopen {reason}
    → backend marks ALL active GlpSignoff rows for this run invalidated_at=now()
    → state allows EDITED transition again
    → on save: PATCH /runs/{id}/state {state: "EDITED", edit_reasons: {...}}
    → backend assert_no_unjustified_edit_errors() validates
    → re-sign cycle required to re-close (operator + any roles required by glpSettings)

Protocol approval (protocol context — F-0066 refactor)
  Author finishes protocol, submits for approval
    → existing GlpSignoffRequest row created (formerly ProtocolApprovalRequest)
    → SD/QAU reviewer navigates to the protocol approval page (existing surface,
      now backed by shared SignoffBlock component)
    → clicks "Sign as Study Director" (or QAU)
    → SignoffModal renders with sd/qau attestation text from protocol.graph.glpSettings
      (or platform defaults)
    → POST /protocols/{id}/signoffs {role: STUDY_DIRECTOR, action: APPROVED,
       signoff_request_id: ...}
    → validate_signoff_role_assignable() — project permission gates SD/QAU roles
    → assert_qau_independent() — when role=QAU, signer must differ from SD signer
    → assert_attestation_and_image_present()
    → copy User.signature_full_path → uploads/{org}/signoffs/{signoff_id}.png
    → INSERT GlpSignoff(protocol_id=X, role=..., action=APPROVED, signoff_request_id=...)
    → AuditLog
    → 201; protocol approval surface re-renders showing the new sign-off
    → when all required roles signed, GlpSignoffRequest closes (existing F-0066 logic
      adapted to read from glp_signoffs instead of protocol_approval_events)
```

## Error handling

All sign-off errors come from the shared `services/signoffs/` validator suite, so the same shape applies to both protocol and run endpoints:

- 400 `{error: "EDIT_REASON_REQUIRED", issues: [{step_id, ...}]}` — missing edit_reason on EDITED transition
- 400 `{error: "SIGNOFF_REQUIRED", role: "QAU"}` — close attempted without required signature (run) or approval workflow can't close (protocol)
- 400 `{error: "QAU_NOT_INDEPENDENT"}` — QAU signer matches operator (run) or study director (run or protocol)
- 400 `{error: "RUN_IMMUTABLE_REOPEN_REQUIRED"}` — edit attempted on a run with any active sign-off; client must call `POST /runs/{id}/reopen` first
- 400 `{error: "ATTESTATION_REQUIRED"}` — sign-off with `action=APPROVED` missing `attestation` or `signature_image_path` (replaces F-0066's `SIGNATURE_STATEMENT_REQUIRED`; old code re-exported as alias for one release)
- 400 `{error: "ROLE_NOT_VALID_FOR_SCOPE"}` — attempting OPERATOR sign-off on a protocol, or SPONSOR sign-off on a run (CHECK constraint catches at DB layer, validator catches earlier)
- 403 — user lacks signoff role permission (existing `require_permission` pattern, applied per-role)

## Testing strategy

| Layer | Tool | Coverage |
|---|---|---|
| Unit (backend) | pytest | Each validator function in `services/signoffs/` and `services/runs/validation.py`; CHECK-constraint enforcement (scope partition, role enum, role-scope fit, APPROVED→attestation+image); partial unique index blocks duplicate active APPROVED per (entity, role); signature-image copy path generation; F-0066 → GlpSignoff data-migration script (rows mapped, role defaults to QAU) |
| Integration (backend) | pytest | Full sign-off lifecycle in both contexts: (a) protocol approval — SD then QAU sign, re-edit blocked, edit triggers new GlpSignoffRequest; (b) run lifecycle — operator+QAU sign, reopen with reason invalidates all active sign-offs, re-sign required to re-close; equipment calibration warn-not-block; PROTOCOL → PROTOCOLVERSION snapshot preserves glpSettings; template render with new `signoffs.*` and `protocol_approvals.*` variables; F-0066 regression suite (all existing protocol-approval tests pass against unified backend); deprecation shim `POST /protocols/{id}/approval-events` still works |
| Unit (frontend) | Vitest | `validateCanCloseRun` mirror agrees with backend on all 4xx cases; shared `SignoffBlock` / `SignoffModal` render correctly for both `entityType="protocol"` and `entityType="run"`; signoffValidation.ts mirror |
| E2E | Playwright | (1) complete run → operator+QAU sign-off → BR render snapshot; (2) reopen-with-reason → re-edit → re-sign → re-close; (3) protocol editor → GLP Settings toggle → run honors requirement; (4) equipment with overdue calibration shows warning; (5) protocol approval flow end-to-end (F-0066 regression) — author submits, SD signs, QAU signs, protocol publishable; (6) QAU on run cannot be the same user as the operator (cross-role independence) |

Target ≥80% coverage on new modules per `CLAUDE.md`.

## Migration

Single Alembic revision, performed in this order:

1. Create `glp_signoffs` table with all CHECK constraints. The `ck_approved_requires_attestation` constraint is added with `NOT VALID` so legacy F-0066 rows missing `signature_image_path` don't block migration.
2. Create the two partial unique indexes (`ux_glp_signoff_active_protocol`, `ux_glp_signoff_active_run`).
3. Rename `protocol_approval_requests` → `glp_signoff_requests` (cosmetic; columns unchanged; FK names updated).
4. Data-migrate `protocol_approval_events` → `glp_signoffs`:
   - `protocol_id`, `signer_user_id → signer_id`, `action`, `signature_statement → attestation`, `signed_at`, `approval_request_id → signoff_request_id`
   - `role` defaulted to `'QAU'` for every existing row (single-stage F-0066 review is QA-style)
   - `signature_image_path` left NULL (record-scoped snapshot not captured pre-F-0087)
   - `run_id` NULL (these are all protocol rows)
5. Add `started_at`, `completed_at`, `outcome`, `outcome_notes` columns to `runs`.
6. Add `serial_number`, `last_calibrated_at`, `calibration_due_at`, `calibration_certificate_path` columns to `equipment`.
7. Leave `protocol_approval_events` in place but unreferenced. A follow-up cleanup migration (out of F-0087 scope) drops the table after one release where the deprecation shim has been live.

JSONB additions (`execution_data[*].started_by_user_id`, `execution_data[*].edit_reason`, `Protocol.graph.glpSettings`) require no DDL; defaults apply on first write.

**Rollback note:** because we leave `protocol_approval_events` in place, rollback is a code revert plus dropping `glp_signoffs` / renaming `glp_signoff_requests` back. No data loss, but any new sign-offs created post-F-0087 would not exist in the old table — operationally this means rollback is safe only within the first release window.

## Open items for plan-writing (not design decisions)

- Order of bucket implementation (proposed: data model → validators → endpoints → template engine → frontend GLP Settings → frontend sign-off → frontend reason-for-change → equipment UI → template defaults → reviewer endpoint → immutability gate → multi-stage approval)
- Whether to split into multiple PRs or land as one — defer to writing-plans
- Default attestation text content — placeholder strings in this design; final wording is a separate review per audit Q5

## Sign-off

This design is locked once reviewed. Changes after writing-plans starts require updating both this doc and the plan.
