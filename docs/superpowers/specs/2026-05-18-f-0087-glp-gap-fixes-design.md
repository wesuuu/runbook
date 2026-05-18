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
- **Sign-off model**: `RunSignoff` child table, not JSONB on `Run`. Auditor-preference reasons documented in audit Q-section.
- **Signature image binding**: copy `User.signature_full_path` to a record-scoped path **at sign time** (satisfies §11.70). Storing only `signer_id` would allow retroactive re-binding if the user re-uploads a signature.
- **`glpSettings` location**: top-level key in `Protocol.graph` JSONB, mirrored into `ProtocolVersion.graph` snapshots automatically. Zero migration; no first-class column.
- **Reopen UX**: single-button reopen-with-reason. After QAU sign-off, `COMPLETED → EDITED` is blocked unless `POST /runs/{id}/reopen {reason}` is called, which invalidates **all active sign-offs** on the run (sets `invalidated_at`) and writes an `AuditLog` entry. Every role that signed must re-sign after edits land.
- **Outcome ↔ QAU coupling**: separate fields, co-located in UI. Operator sets `Run.outcome` at completion; QAU sign-off attests to outcome but doesn't set it.
- **GLP-conformant role names** on the two new enums in this design (existing product roles like `OrgRole`, `TeamRole`, `ProtocolRole` are unchanged).

## Scope (10 buckets)

| # | Bucket | Audit IDs |
|---|---|---|
| 1 | RunSignoff table + endpoints + UI | H2, H3, H4, K4, K5 |
| 2 | Per-step reviewer endpoint + UI | H1 |
| 3 | GLP Settings panel on Protocol Editor | drives H3/H4/D1/K3/C3/E* opt-ins |
| 4 | Reason-for-change on EDITED transitions | I4 |
| 5 | Run timestamps (Run.started_at, completed_at, per-step started_by_user_id) | A4, G4, G5 |
| 6 | Equipment refinement (serial, calibration fields) | B1, B2 |
| 7 | Run outcome block (Run.outcome, outcome_notes) | L5 |
| 8 | Immutability gate (block edits after QAU sign-off; reopen-with-reason) | J1 |
| 9 | Protocol approval multi-stage (stage enum + signature_statement validator) | H5, K2 |
| 10 | Template default cleanup | N1–N5 |

## Out of scope (explicit deferrals to sibling F-tickets)

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

#### New table — `RunSignoff`

```python
class RunSignoffRole(str, Enum):
    OPERATOR = "OPERATOR"          # §58.29 study personnel
    STUDY_DIRECTOR = "STUDY_DIRECTOR"  # §58.33 overall conduct
    QAU = "QAU"                    # §58.35 quality assurance unit

class RunSignoff(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "run_signoffs"

    run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("runs.id", ondelete="CASCADE"), nullable=False
    )
    role: Mapped[str] = mapped_column(String, nullable=False)
    signer_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    attestation: Mapped[str] = mapped_column(Text, nullable=False)
    signed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    signature_image_path: Mapped[str] = mapped_column(String, nullable=False)

    # Reopen-and-resign audit trail
    invalidated_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    invalidated_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    invalidated_by_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("users.id"), nullable=True
    )

    __table_args__ = (
        Index(
            "ux_run_signoff_active",
            "run_id", "role",
            unique=True,
            postgresql_where="invalidated_at IS NULL",
        ),
        CheckConstraint(
            "role IN ('OPERATOR', 'STUDY_DIRECTOR', 'QAU')",
            name="ck_run_signoff_role",
        ),
    )
```

**Rationale:**
- Partial unique index preserves the audit-trail row when a sign-off is invalidated; only one active sign-off per `(run, role)` is enforced.
- `signature_image_path` stores a record-scoped copy made at sign time (`uploads/{org_id}/signoffs/{signoff_id}.png`). User re-uploading their signature later does not retroactively change past records (§11.70).
- `signer_id` uses `ON DELETE RESTRICT`: a user with sign-offs cannot be hard-deleted; org admins can deactivate but not erase. Required for §11.70 link permanence.

#### Run additions

| Column | Type | Set when |
|---|---|---|
| `started_at` | `DateTime(timezone=True)` nullable | PLANNED → ACTIVE transition |
| `completed_at` | `DateTime(timezone=True)` nullable | ACTIVE → COMPLETED transition |
| `outcome` | `String` nullable (enum: `COMPLETED_NORMAL` / `COMPLETED_WITH_DEVIATIONS` / `ABORTED`) | Operator selects at completion |
| `outcome_notes` | `Text` nullable | Operator may include free-text |

`completed_by_id` is **not** added as a column — it rolls into `RunSignoff(role=OPERATOR)`.

#### Equipment additions

| Column | Type |
|---|---|
| `serial_number` | `String` nullable |
| `last_calibrated_at` | `DateTime(timezone=True)` nullable |
| `calibration_due_at` | `DateTime(timezone=True)` nullable |
| `calibration_certificate_path` | `String` nullable |

#### ProtocolApprovalEvent additions

| Column | Type | Notes |
|---|---|---|
| `stage` | `String` (enum: `STUDY_DIRECTOR` / `SPONSOR` / `QAU`) | Default `QAU` for backward compat |

Data migration backfills existing rows with `stage = 'QAU'`. New approvals must specify a stage.

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
| `assert_qau_independent(run, signer_id)` | `services/runs/validation.py` | Raises 400 if a QAU signer is also the OPERATOR or STUDY_DIRECTOR on the same run (§58.35 independence) |
| `validate_signoff_role_assignable(run, user, role)` | `services/runs/validation.py` | Verifies user has permission to sign in this role (combination of project permissions and `RunRoleAssignment`) |
| `assert_signature_statement_present(approval_event)` | `services/protocols/validation.py` | Raises 400 if `action=APPROVED` and `signature_statement IS NULL` (K2) |
| `assert_can_edit_completed_run(run)` | `services/runs/validation.py` | Raises 400 if active QAU sign-off exists; client must call `POST /reopen` first (J1) |

Frontend mirrors land in `frontend/src/lib/runValidation.ts` and `protocolValidation.ts` (existing files) so the UX can pre-flight before the round trip.

### Endpoints (backend/app/api/endpoints/runs.py, equipment.py)

| Verb + path | Body | Action |
|---|---|---|
| `POST /runs/{id}/signoffs` | `{role, attestation_override?}` | Calls `validate_signoff_role_assignable`, `assert_qau_independent`. Copies `User.signature_full_path` to record-scoped path. Inserts `RunSignoff` row. Writes `AuditLog`. |
| `POST /runs/{id}/steps/{step_id}/review` | `{}` | Sets `execution_data[step_id].reviewed_by_user_id` + `reviewed_at`. Writes `AuditLog`. |
| `POST /runs/{id}/reopen` | `{reason}` | Calls `assert_can_edit_completed_run` (inverse — must currently be blocked). Invalidates **all active sign-offs** on the run (sets `invalidated_at`, `invalidated_reason`, `invalidated_by_id`). Writes `AuditLog`. |
| `PATCH /runs/{id}/state` (existing, extended) | `{state: "EDITED", edit_reasons: {step_id: reason}}` | Calls `assert_no_unjustified_edit_errors`. |
| `POST /runs/{id}/complete` (new wrapper) | `{outcome, outcome_notes?}` | Sets `Run.outcome`, transitions ACTIVE → COMPLETED, sets `completed_at`. Calls `assert_run_can_close`. |
| `PATCH /equipment/{id}` (existing, extended) | `{serial_number?, last_calibrated_at?, calibration_due_at?, calibration_certificate_path?}` | Equipment field updates. |
| `PUT /protocols/{id}` (existing, extended) | `{graph: {..., glpSettings: {...}}}` | No new endpoint; `glpSettings` is just another key in the graph payload. |

### Template engine (backend/app/services/protocols/template_engine.py)

New variables added to `KNOWN_VARIABLES`:

| Variable | Source | Notes |
|---|---|---|
| `signoffs.operator`, `signoffs.study_director`, `signoffs.qau` | Latest active `RunSignoff` per role | Each is `{name, signature_image, attestation, signed_at, initials}`. Signature swap pulls from `RunSignoff.signature_image_path` (already record-scoped), not from `User.*`. |
| `equipment[i].serial_number`, `.calibration_due_at`, `.calibration_status` | `Equipment` columns | `calibration_status` derived: "OK" / "OVERDUE" / "UNKNOWN" |
| `run.outcome`, `run.outcome_notes` | `Run` columns | Conditional rendering |
| `run.started_at`, `run.completed_at` | `Run` columns | Replace UI-inferred values |
| `step.edit_reason` | `execution_data[step_id].edit_reason` | Appended to the strikethrough RichText annotation (`"42 → 50 (corrected unit conversion, WU 2026-05-18)"`) |
| `step.actual_value_block` | Composed | Stacked-RichText: target / unit / recorded / Δ-flag / initials / timestamp (replaces N3 raw `actual_value`) |
| `protocol_approvals[i].stage` | `ProtocolApprovalEvent.stage` | Multi-stage approval rendering |

### Frontend (frontend/src/lib/components/)

Per the bucket placement rule in `conventions.md`:

| Component | Path | Purpose |
|---|---|---|
| `GlpSettingsPanel.svelte` | `protocol/` | Inspector-replacing view when no node selected; toggles + attestation textareas |
| `RunSignoffBlock.svelte` | `run/` | Rendered in `RunEditMode.svelte`; lists required sign-offs per `glpSettings`; each row has a "Sign as <role>" button |
| `RunSignoffModal.svelte` | `run/` | Attestation preview + signature confirmation modal |
| `RunReopenModal.svelte` | `run/` | Required `reason` field; warns sign-off invalidation; triggered from completed-run view |
| `RunEditReasonPrompt.svelte` | `run/` | Modal inserted into existing step-edit save flow; collects `edit_reason` per modified step |
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
Operator finishes last step in RunEditMode
  → frontend validateCanCloseRun() passes
  → POST /runs/{id}/complete {outcome, outcome_notes}
  → backend assert_run_can_close()
    → if OPERATOR signoff missing: 400 SIGNOFF_REQUIRED (OPERATOR)
  → 200; transitions ACTIVE → COMPLETED; sets Run.completed_at
  → UI surfaces RunSignoffBlock with required roles per glpSettings

Operator clicks "Sign as Operator"
  → RunSignoffModal renders with operator_attestation_text
  → POST /runs/{id}/signoffs {role: OPERATOR}
  → backend validate_signoff_role_assignable() passes
  → copy User.signature_full_path → uploads/{org}/signoffs/{signoff_id}.png
  → INSERT RunSignoff(role=OPERATOR, ...)
  → AuditLog
  → 201

QAU user signs
  → POST /runs/{id}/signoffs {role: QAU}
  → assert_qau_independent() — signer_id must not match OPERATOR signer
  → same flow as above
  → record now satisfies require_qau

Operator later opens completed run, sees results need correction
  → clicks "Reopen for correction"
  → RunReopenModal collects reason
  → POST /runs/{id}/reopen {reason}
  → backend marks ALL active signoffs invalidated_at=now()
  → state allows EDITED transition again
  → on save: PATCH /runs/{id}/state {state: "EDITED", edit_reasons: {...}}
  → backend assert_no_unjustified_edit_errors() validates
  → re-sign cycle required to re-close
```

## Error handling

- 400 `{error: "EDIT_REASON_REQUIRED", issues: [{step_id, ...}]}` — missing edit_reason on EDITED transition
- 400 `{error: "SIGNOFF_REQUIRED", role: "QAU"}` — close attempted without required signature
- 400 `{error: "QAU_NOT_INDEPENDENT"}` — QAU signer matches operator or study director
- 400 `{error: "RUN_IMMUTABLE_REOPEN_REQUIRED"}` — edit attempted on QAU-signed run
- 400 `{error: "SIGNATURE_STATEMENT_REQUIRED"}` — protocol approval action=APPROVED without signature_statement
- 403 — user lacks signoff role permission (existing `require_permission` pattern)

## Testing strategy

| Layer | Tool | Coverage |
|---|---|---|
| Unit (backend) | pytest | Each validator function (6 functions); enum/constraint enforcement; signature-image copy path generation |
| Integration (backend) | pytest | Full sign-off lifecycle including reopen; immutability gate; equipment calibration warn-not-block; multi-stage approval; PROTOCOL → PROTOCOLVERSION snapshot preserves glpSettings; template render with new context variables |
| Unit (frontend) | Vitest | `validateCanCloseRun` mirror agrees with backend on all 4xx cases |
| E2E | Playwright | (1) complete run → operator+QAU sign-off → BR render snapshot; (2) reopen-with-reason → re-edit → re-sign → re-close; (3) protocol editor → GLP Settings toggle → run honors requirement; (4) equipment with overdue calibration shows warning |

Target ≥80% coverage on new modules per `CLAUDE.md`.

## Migration

One Alembic revision:
- Create `run_signoffs` table + partial unique index
- Add columns to `runs`, `equipment`, `protocol_approval_events`
- Backfill `protocol_approval_events.stage = 'QAU'`

JSONB additions (`execution_data[*].started_by_user_id`, `edit_reason`, `Protocol.graph.glpSettings`) require no DDL; defaults apply on first write.

## Open items for plan-writing (not design decisions)

- Order of bucket implementation (proposed: data model → validators → endpoints → template engine → frontend GLP Settings → frontend sign-off → frontend reason-for-change → equipment UI → template defaults → reviewer endpoint → immutability gate → multi-stage approval)
- Whether to split into multiple PRs or land as one — defer to writing-plans
- Default attestation text content — placeholder strings in this design; final wording is a separate review per audit Q5

## Sign-off

This design is locked once reviewed. Changes after writing-plans starts require updating both this doc and the plan.
