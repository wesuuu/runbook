# GLP / GMP Data-Model Audit (May 2026)

**Ticket**: F-0087 — GLP/GMP Protocol Data Model Audit + Sign-Off, SOP & Batch Record Refinements
**Author**: Wesley Uykimpang (with Claude)
**Date**: 2026-05-18
**Status**: Phase 1 deliverable

---

## Purpose

Compare what Batchrite captures today against GLP, GMP-adjacent, and Part 11 batch-record requirements. Surface every gap so Phase 2 of F-0087 has a concrete implementation list, and flag template fields that do not belong on a GLP-compliant SOP or Batch Record.

This audit assumes the work shipped under QA-0008 (Production-grade SOP + Batch Record templates) is in place — see `docs/superpowers/specs/2026-05-14-qa-0008-production-templates-design.md`. Where QA-0008 already closed a gap, this audit marks it ✅ and moves on. Where it deferred a gap (e.g. reviewer signing endpoints, equipment serial numbers), this audit picks it up.

## Standards consulted

| Code | Title | Notes |
|---|---|---|
| 21 CFR Part 58 | Good Laboratory Practice for Nonclinical Laboratory Studies | The "GLP" anchor — toxicology, safety, environmental studies |
| 21 CFR Part 211 | Current Good Manufacturing Practice for Finished Pharmaceuticals | The "GMP" anchor for drug-product batch records |
| 21 CFR Part 11 | Electronic Records; Electronic Signatures | Applies to any GxP electronic record/signature |
| ICH Q7 | GMP Guide for Active Pharmaceutical Ingredients | API-batch-record analog of Part 211 |

Where multiple codes apply, the strictest is cited.

## Severity rubric

| Severity | Definition | Phase 2 disposition |
|---|---|---|
| **must-have** | Required for Batchrite to make a credible claim of GLP-readiness. Auditor would file this as a 483 observation. | Implement under F-0087 |
| **should-have** | Customer-facing GLP/GMP shops will ask for this within the first year. Not blocking for initial GxP rollout but is for formal CSV-validated deployment. | Implement under F-0087 *if* the work fits within the ticket envelope; otherwise spawn a sibling F-task |
| **nice-to-have** | Refinement / quality-of-life. Auditor would not flag absence; we'd add it for competitive parity with mature ELN/LES products. | Spawn a follow-up ticket; document and defer |
| **extraneous** | Currently rendered but not GLP/GMP-required. Remove from default templates. | Strip under F-0087 |

## Methodology

I read the data model (`backend/app/models/science.py`, `iam.py`, `execution.py`), template engine (`backend/app/services/protocols/template_engine.py`, the existing `sop_default.docx` + `batch_record_default.docx`), run lifecycle endpoint (`backend/app/api/endpoints/runs.py`), frontend protocol/run components, and the QA-0008 catalog. I mapped each regulatory requirement to the current data surface, classified the gap (or extraneous-field flag), assigned severity, and drafted a concrete recommendation.

Each finding has an ID of the form `<CategoryLetter><n>`. IDs are stable; refer to them in commit messages and follow-up tickets so the audit trail through Phase 2 is traceable.

---

## A. Operator identity, qualification & training

GLP §58.29 and §58.31 require that personnel performing each study activity be qualified by education, training, or experience, with records on file. GMP §211.25 mirrors this for manufacturing. Today Batchrite captures *who* performed a step but not *whether they were qualified to perform it*.

| ID | Requirement | Std ref | Current state | Gap | Severity | Recommendation |
|---|---|---|---|---|---|---|
| A1 | Operator identity per step | §58.130(e), §211.188(b) | `execution_data[step_id].completed_by_user_id` | none | ✅ | — |
| A2 | Operator identity per run (overall) | §58.185(a)(4) | `Run.started_by_id` (run starter); no `completed_by_id` at run level | Operator who ultimately closes the run is not captured at the Run row; only the step-level completer. Reports cannot answer "who ran this batch?" without scanning steps. | should-have | Promote to `RunSignoff` row (role=OPERATOR) — covered by the F-0087 known-fix sign-off block. No separate column needed. |
| A3 | Operator training / qualification record | §58.29(b), §211.25(b) | none | No `TrainingRecord` model. System cannot prove the operator was trained on the protocol or instrument being used. | should-have | Add `TrainingRecord(user_id, topic, completed_at, expires_at, signed_off_by_id, document_ref)` + optional per-protocol required-training list. Defer enforcement (warn-not-block) until a customer asks for hard gating. |
| A4 | Per-step start-time attribution | §58.130(e) "promptly, dated, signed" | `execution_data[step_id].started_at` exists (QA-0008 B9) but no `started_by_user_id` per step | Step start is timestamped but anonymous. GLP requires attribution of the entry itself, not just the completion. | must-have | Add `execution_data[step_id].started_by_user_id` in the same write that sets `started_at`. No migration. |

## B. Equipment identity, calibration & instrument readings

GLP §58.61–§58.63 and GMP §211.68 require equipment to be uniquely identified, inspected, cleaned, maintained, and calibrated, with records. QA-0008 surfaced `equipment_summary` and per-step equipment lists in the template but flagged serial numbers + calibration as TBD.

| ID | Requirement | Std ref | Current state | Gap | Severity | Recommendation |
|---|---|---|---|---|---|---|
| B1 | Equipment uniquely identified (serial / asset ID) | §211.105, §58.63 | `Equipment` has `name`, `description`, `equipment_type`, `location` — no `serial_number` | Cannot distinguish two units of the same instrument type. Audit fails on basic identification. | must-have | Add `Equipment.serial_number: str?` (nullable to migrate existing rows; UI prompts on first edit). |
| B2 | Calibration status visible at point of use | §211.68(b) | none | No `calibration_due_at`, no "calibrated within tolerance" gate. Operator cannot tell at run time if instrument is overdue. | must-have | Add `Equipment.last_calibrated_at`, `calibration_due_at`, `calibration_certificate_path`. Render calibration status next to each piece of equipment on the Batch Record. Warn (not block) on overdue at run time. |
| B3 | Calibration history (records, not just current) | §58.63(c) | none | No `CalibrationRecord` table. History stays in lab paper, not the LES. | should-have | Add `CalibrationRecord(equipment_id, performed_at, performed_by_id, certificate_path, due_at, notes)`. Cascade from Equipment. |
| B4 | Per-step equipment readings (recorded value, not just identity) | §211.188(b)(11) | Step `param_schema` supports arbitrary recorded values; equipment-derived readings live there if the protocol author defines them | Not modeled distinctly; readings indistinguishable from manual entry. Loses provenance. | should-have | Phase 2: convention only — encourage authors to tag schema fields with `source: "instrument"`. Modeling instrument-direct ingest is out of scope. |
| B5 | Equipment summary on Batch Record | §211.188(b) | `equipment_summary` rendered (QA-0008 B10) | none — but row contents change after B1/B2 | ✅ | Update row shape: `{local_id, name, serial_number, calibration_due_at, status}` once B1/B2 ship. |
| B6 | Equipment qualification (IQ/OQ/PQ) records | §211.63, §211.68 | none | Out of scope for an LES; lives in CMMS / validation packages. | nice-to-have | Document the boundary in CSV docs. Cross-reference to external system. |

## C. Material identity, lots, expiration & COAs

GMP §211.184 and §211.122 require receipt, lot identity, COA, and use of components to be recorded. GLP §58.105 mirrors for test/control article characterization. Today `Run.lot_number` is the **output** lot; we do not model **input** materials.

| ID | Requirement | Std ref | Current state | Gap | Severity | Recommendation |
|---|---|---|---|---|---|---|
| C1 | Per-step material consumption (which lot of what reagent) | §211.188(b)(3) | Template has `materials` loop populated only when test fixtures pass it (not from real DB); no `MaterialLot` model | Cannot link consumed reagent lot to step. Defeats traceability. | must-have | Add `MaterialLot(organization_id, material_name, lot_number, vendor, expiration_date, coa_path, received_at, qualification_status)`. Per-step `materials_used: [{lot_id, qty, unit}]` on `execution_data`. |
| C2 | Material lot identifier (vendor lot + internal lot) | §211.184(b) | none | No place to record. | must-have | `MaterialLot.lot_number` (internal) + `vendor_lot_number` (external). |
| C3 | Material expiration check at use | §211.137 | none | No way for system to prevent use of expired material. | should-have | Warn at run time when `MaterialLot.expiration_date < today`. Block only when `glpSettings.block_expired_materials = true`. |
| C4 | COA on file / referenceable | §211.84(d) | none | No attachment. | must-have | `MaterialLot.coa_path` (FileStorage). Render COA reference in BR materials section. |
| C5 | Run output lot (product lot) | §211.188(b)(2) | `Run.lot_number` + `Run.batch_number` (QA-0008 B15) | none | ✅ | — |

## D. Environmental conditions

GMP §211.46 + §211.42(c) require room/area/temperature/humidity to be recorded where they materially affect the process (e.g., aseptic operations, cold-chain). GLP §58.41 + §58.43 mirror it. Many protocols don't require it; some do.

| ID | Requirement | Std ref | Current state | Gap | Severity | Recommendation |
|---|---|---|---|---|---|---|
| D1 | Per-step environmental capture (T, RH, room) | §211.46, §58.41 | none | Not modeled. Not surfaced in template. | should-have | Add `execution_data[step_id].environmental: {temperature_c?, humidity_pct?, room?, captured_at}` JSONB. Per-protocol opt-in via `glpSettings.require_environmental_steps: [step_id]`. Render in BR when present. |
| D2 | Continuous environmental monitoring integration | §211.46 | none | External system territory. | nice-to-have | Document boundary; cross-ref to BMS / monitoring system if customer has one. |

## E. Deviations, root cause & corrective action

GMP §211.192 requires that all deviations be investigated, with conclusions in the batch record. GLP §58.130(e) demands explanation for unexpected results. Today deviations are captured as `Run.notes[i].flags` containing `"anomaly"`, rendered into a `deviations` list by `build_context`. This is a single text blob — no root cause, no corrective action, no closeout, no severity, no link to the step.

| ID | Requirement | Std ref | Current state | Gap | Severity | Recommendation |
|---|---|---|---|---|---|---|
| E1 | Deviation captured with timestamp + author | §211.192 | `Run.notes[i]` (timestamped, authored) flagged `anomaly` | minimum-viable for capture | ⚠️ should-have | Promote to dedicated `RunDeviation` model (see E2/E3/E4 below). The Note-with-flag shape is fine for "minor observation" but auditor will reject it as the *only* deviation record. |
| E2 | Root cause documented | §211.192 | none | No `root_cause` field; lives only in note free-text if author thinks to write it. | must-have | `RunDeviation.root_cause: text?` (optional at capture, required at closeout). |
| E3 | Corrective action documented | §211.192 | none | No `corrective_action` field. | must-have | `RunDeviation.corrective_action: text?` (required at closeout). |
| E4 | Closeout signoff (deviation reviewed + closed) | §211.192 | none | Deviations stay open forever (or get edited inline; lossy). | must-have | `RunDeviation.closed_by_id`, `closed_at`, `closure_signature_path?`. Render in BR. |
| E5 | Severity / classification | §211.192 (implicit) | none | No way to triage minor vs major. | should-have | `RunDeviation.severity: enum(MINOR, MAJOR, CRITICAL)`. |
| E6 | Link deviation to specific step | §211.188 | `Run.notes[i].step_id` exists | retained in promoted model | ✅ → reuse | `RunDeviation.step_node_id: str?` (nullable; not every deviation is step-scoped). |

## F. Sample identity & chain of custody

GLP §58.90 + §58.105 + §58.190 require samples (test/control article aliquots, in-process samples, retains) to be uniquely identified with chain of custody. Heavy in tox studies; lighter in many GMP processes. Currently unmodeled.

| ID | Requirement | Std ref | Current state | Gap | Severity | Recommendation |
|---|---|---|---|---|---|---|
| F1 | Sample ID at collection | §58.90(c), §211.110(c) | none — only via free-form schema field | Not enforced; not searchable across runs. | should-have | Add `Sample(run_id, step_node_id, sample_id_external, collected_at, collected_by_id, container_type, storage_location, parent_sample_id?, status)`. `parent_sample_id` enables chain. Defer "transfer custody" workflow (G&S) — out of scope. |
| F2 | Chain of custody transfers | §58.90(c) | none | Cannot track who handled a sample after collection. | nice-to-have | Add `SampleCustodyEvent(sample_id, transferred_from_id, transferred_to_id, transferred_at, reason)` if/when a customer requires it. Defer. |
| F3 | Retention sample tracking | §211.170 | none | No retention container, no retain-until date. | nice-to-have | Defer; add `Sample.retain_until_date` when needed. |

## G. Time stamps: scheduled, actual, attributed

GLP §58.130(e) — entries made "directly, promptly, dated". QA-0008 added scheduled-vs-actual rendering. We're mostly OK; attribution of step start is the residual gap (already cited as A4).

| ID | Requirement | Std ref | Current state | Gap | Severity | Recommendation |
|---|---|---|---|---|---|---|
| G1 | Scheduled time per step | §58.130(d), §211.188 | `step.scheduled_at` (computed in `build_context`) | none | ✅ | — |
| G2 | Actual start time per step | §58.130(e) | `execution_data[step_id].started_at` (QA-0008 B9) | none | ✅ | — |
| G3 | Actual completion time per step | §58.130(e) | `execution_data[step_id].completed_at` | none | ✅ | — |
| G4 | Start-time attribution (who started) | §58.130(e) | none | Cross-ref A4 — same gap | must-have | Same fix as A4. |
| G5 | Run start & completion timestamps + attribution | §211.188(b)(8) | Run has `created_at` (creation), no `started_at` / `completed_at` column. UI infers from execution_data. | The Run row itself has no `started_at` / `completed_at` / `completed_by_id`. Attribution lives one indirection away (in step JSONB or in audit log). | should-have | Add `Run.started_at`, `Run.completed_at` columns set on status transitions in `runs.py:425`+. `completed_by_id` rolls into RunSignoff (operator role). |
| G6 | Time-zone explicit on all stored timestamps | Part 11 §11.10(e) | All `DateTime(timezone=True)`; rendering uses `replace("Z", "+00:00")` | OK but verify all *new* timestamp fields (training, calibration, samples, deviations) also use tz-aware columns. | must-have policy | Document in `backend-models.md` rules: every new datetime column carries `DateTime(timezone=True)`. |

## H. Reviewer & QA sign-off separate from operator

GMP §211.188(b)(11) + §211.192 require that batch records be reviewed and approved by QA before release. Two-signature workflow at minimum. QA-0008 surfaced a per-step reviewer signature (B7) and added `execution_data.reviewed_by_user_id`. At **run level**, we have no operator/witness/QA sign-off block. This is the central F-0087 known-fix.

| ID | Requirement | Std ref | Current state | Gap | Severity | Recommendation |
|---|---|---|---|---|---|---|
| H1 | Per-step reviewer signature | §211.188(b)(11) | `execution_data[step_id].reviewed_by_user_id` + `reviewed_at` (QA-0008 B7); template renders `step.reviewer_initials` via signature swap | data is there; **no UI endpoint sets it yet** | must-have | Phase 2: add `POST /runs/{id}/steps/{step_id}/review` endpoint + button in `RunEditMode.svelte` for users with reviewer role on the run. Wire signature swap (already in `render_to_docx`). |
| H2 | Run-level operator sign-off (batch record attestation) | §211.188(b)(11), §11.50 | none | The F-0087 known-fix. | must-have | New `RunSignoff` model (decided in brainstorming): `run_id`, `role: enum(OPERATOR\|WITNESS\|REVIEWER)`, `signer_id: fk users.id ON DELETE RESTRICT`, `attestation: text`, `signed_at: tz-aware`, `UNIQUE(run_id, role)`. Signature image resolved from `User.signature_full_path` at render. UI surfaced in run-completion flow. |
| H3 | Witness sign-off (optional per protocol) | §211.188 implicit "double-check" | none | The F-0087 known-fix. | must-have (conditional) | Same `RunSignoff` table, `role=WITNESS`. Enabled per protocol via `glpSettings.require_witness`. |
| H4 | QA reviewer sign-off | §211.192 | none | The F-0087 known-fix. | must-have (conditional) | Same `RunSignoff` table, `role=REVIEWER`. Enabled per protocol via `glpSettings.require_qa_reviewer`. |
| H5 | Protocol approval (operator preparation) | §211.100 | `ProtocolApprovalEvent` (F-0066) — single-stage | F-0066 is single-stage. Multi-stage (operator → reviewer → QA) was deferred from QA-0008 as Migration C. | should-have | Phase 2: add `ProtocolApprovalEvent.stage: enum(operator\|reviewer\|qa)` with default `qa` for backward compat. Migration with backfill. |

## I. Reason-for-change capture (Part 11 §11.10(e))

Part 11 §11.10(e) requires "secure, computer-generated, time-stamped audit trails ... [that] independently record ... operator entries and actions that create, modify, or delete electronic records. **Record changes shall not obscure previously recorded information.**" In practice: when an operator edits a recorded result, the record must capture **what changed, when, who, and why**. We have what / when / who. We do not have **why**.

| ID | Requirement | Std ref | Current state | Gap | Severity | Recommendation |
|---|---|---|---|---|---|---|
| I1 | "What" changed | §11.10(e) | `execution_data[step_id].original_results` + `results` | ✅ | ✅ | — |
| I2 | "When" changed | §11.10(e) | `execution_data[step_id].edited_at` | ✅ | ✅ | — |
| I3 | "Who" changed it | §11.10(e) | `execution_data[step_id].edited_by_user_id` | ✅ | ✅ | — |
| I4 | "Why" changed (reason for change) | §11.10(e) | none | **No reason captured.** UI does not prompt for reason; backend does not store. Part 11 cornerstone gap. | must-have | Add `execution_data[step_id].edit_reason: str` (required when EDITED transition is requested, enforced server-side with `assert_no_unjustified_edit_errors`). UI prompt at edit time. Render in BR strikethrough annotation: `"42 → 50 (corrected unit conversion, WU 2026-05-18)"`. |
| I5 | Audit trail covers non-result edits too (signatures, attachments, deviations) | §11.10(e) | `AuditLog` model exists; 69 call sites across endpoints | Coverage is broad but uneven — need a sweep to confirm every Run/Protocol/Signoff state change writes an `AuditLog` row. | should-have | Sweep + add missing call sites. Spawn a sibling F-task (`F-XXXX: Audit log coverage sweep for GxP entities`) — not gated by F-0087. |
| I6 | Audit trail itself immutable | §11.10(c), §11.10(e) | `AuditLog` rows are mutable at DB level; no DB trigger to forbid UPDATE/DELETE | App code doesn't update/delete, but auditor will ask about DB-level controls. | should-have | Document control in CSV package (read-only DB role for production). DB triggers are nice-to-have. |

## J. Versioning & immutability of completed batch records

§11.70 requires signatures linked to records "such that the signatures cannot be excised, copied, or otherwise transferred." §211.180 + §58.195 require retention of records. Today Run has a `COMPLETED → EDITED` transition that allows post-completion modification with audit trail preserved via `original_results`. That's not the same as "immutable record".

| ID | Requirement | Std ref | Current state | Gap | Severity | Recommendation |
|---|---|---|---|---|---|---|
| J1 | Completed batch record is immutable | §11.70, §211.188 | `COMPLETED → EDITED` allowed; preserves `original_results` per field but allows further mutation | The audit trail is preserved, but the record itself is not locked. After QA sign-off, edits should be impossible without re-opening the record under a new revision. | must-have | After `RunSignoff` row exists for `role=REVIEWER` (QA sign-off), block `COMPLETED → EDITED` transition unless an explicit `reopen` action is taken (creates an audit-logged reopen event that nullifies the QA sign-off and requires re-review). |
| J2 | Run has versioned snapshot for re-review | §211.180 | `Run.graph` is the snapshot; no `RunVersion` history table | Currently the snapshot is mutable through EDITED. After J1 lands, the immutability gate is sufficient. | should-have | If customers ask for "Run revision N" history, add `RunVersion` mirroring `ProtocolVersion`. Defer. |
| J3 | Record retention policy | §211.180 (1 year past expiry), §58.195 (study + 2y) | No data-retention controls at all | Out of scope for a data-model audit; lives in customer storage policy. | nice-to-have | Document boundary in CSV docs. |

## K. Signature semantics & drawn-signature reuse

§11.50 requires every electronic signature to carry (1) signer's printed name, (2) date and time, (3) **meaning of signature**. F-0080 gave us drawn signatures stored on the User. Today: protocol approvals carry `signature_statement` (meaning); step initials and signature images render but **no meaning is captured per step**.

| ID | Requirement | Std ref | Current state | Gap | Severity | Recommendation |
|---|---|---|---|---|---|---|
| K1 | Drawn signature image stored on user | F-0080 | `User.signature_initials_path`, `User.signature_full_path` (PNG paths) | ✅ | ✅ | — |
| K2 | Protocol approval signature meaning | §11.50(a)(3) | `ProtocolApprovalEvent.signature_statement: text?` | nullable; should be required when `action=APPROVED` | should-have | Server-side enforce `signature_statement IS NOT NULL` when action is APPROVED. Migration not needed; constraint at validator. |
| K3 | Step-completion signature meaning | §11.50(a)(3) | Step initials render as image; no `meaning` text stored | Operator completes step → image renders → but record does not say *"I attest the recorded values are accurate"*. Auditor will ask. | should-have | Define a canonical attestation per protocol (default: "I performed this step according to the approved protocol and certify the recorded values."), render once per step block. Configurable in `glpSettings.step_attestation_text`. |
| K4 | Sign-off signature meaning (operator / witness / QA) | §11.50(a)(3) | none | The F-0087 known-fix already includes `attestation` text per signoff. | must-have | `RunSignoff.attestation: text NOT NULL`. Each role has a default attestation text configurable per protocol in `glpSettings`. |
| K5 | Signature cannot be re-bound to a different record | §11.70 | Signatures resolved at render time from `User.signature_*_path`; not embedded per-record | The user's signature image is shared across all their records (it's their canonical signature). The *linkage* is enforced by `signer_id` on the signoff row + FK. A future user might re-upload their signature, which would re-render past records with the new image. | should-have | At sign time, **copy** the signature image to a record-scoped path (`uploads/{org_id}/signoffs/{signoff_id}.png`) and store that path on the RunSignoff row, not just `signer_id`. This satisfies §11.70 ("linked such that ... cannot be transferred to falsify another"). Same fix should apply to ProtocolApprovalEvent on a follow-up sweep. |

## L. Document metadata, control & revision history

GLP §58.81 + GMP §211.100 + §211.180 require master copies, document control IDs, effective/supersedes dates, change history. Most of this landed in QA-0008.

| ID | Requirement | Std ref | Current state | Gap | Severity | Recommendation |
|---|---|---|---|---|---|---|
| L1 | Document number / control ID | §211.100 | `Protocol.doc_number` (QA-0008 B1) | none | ✅ | — |
| L2 | Effective / supersedes date | §211.100 | `Protocol.effective_date`, `supersedes_date` (QA-0008 B2) | none | ✅ | — |
| L3 | Revision history surfaced on SOP | §211.180(c) | `revision_history` from `ProtocolVersion` (QA-0008 B3) | none | ✅ | — |
| L4 | Purpose / scope / responsibilities / references / definitions | §211.100, §58.81 | Fields on `Protocol`; rendered (QA-0008 B4, B5) | none | ✅ | — |
| L5 | Final disposition / release statement on Batch Record | §211.188(b)(13) | none (QA-0008 B16 deferred) | No "Released for use" or "Rejected" decision block on the BR. | should-have | Add `Run.disposition: enum(RELEASED, REJECTED, ON_HOLD)?` + `disposition_at` + `disposition_by_id`. Render conditional block in BR. Tie to QA sign-off (set together). |

## M. Part 11 system controls (data-model adjacent)

Part 11 has system-level controls beyond data fields. Mostly satisfied by Batchrite's auth + permission stack; auditing for completeness here.

| ID | Requirement | Std ref | Current state | Gap | Severity | Recommendation |
|---|---|---|---|---|---|---|
| M1 | Limit access to authorized individuals | §11.10(d) | Auth + RBAC; per-project + per-org permissions | ✅ | ✅ | — |
| M2 | Authority checks (only authorized people sign / approve / release) | §11.10(g) | `require_permission` dependencies; F-0066 approver role | ✅ | ✅ | Verify `RunSignoff` endpoints gate by role membership when added. |
| M3 | Unique IDs (no shared accounts) | §11.300 | User table; email-unique | ✅ at the schema level; policy-level depends on customer | ✅ | Document in CSV. |
| M4 | Password complexity & periodic change | §11.300(b) | Customer-configurable via SSO upstream (F-0052 in progress) | ✅ (delegated) | ✅ | — |
| M5 | Loss management of devices | §11.300(c) | Session expiry + revocation; offline-mode device-level auth (F-0037 deferred) | ⚠️ — offline-mode device auth still on the shelf | should-have | Out of scope for F-0087 — already tracked under F-0037. Note in CSV. |
| M6 | System validation evidence | §11.10(a) | Pytest + Playwright coverage; no formal IQ/OQ/PQ package | ⚠️ | should-have (org-level) | Out of scope for F-0087. Customer-facing CSV package is a separate deliverable. |

---

## N. Extraneous fields to strip from default templates

F-0087 calls out specific render fixes. This section names every field that does not belong on a GLP-compliant SOP or Batch Record and should be removed from the default `sop_default.docx` / `batch_record_default.docx`. The variable can remain in `KNOWN_VARIABLES` for custom-template authors who want it.

| ID | Field | On template | Reason to remove | Action |
|---|---|---|---|---|
| N1 | `target_yield` in **Batch Record header table** | yes (per F-0087 description) | Header is for identification (lot, batch, run, protocol). Yield target belongs in the materials/yield body section, not the header — auditors expect yield in context with materials and process. | Remove cell from header; keep in BR body if it appears there, or drop entirely if unused. |
| N2 | Run-specific data on **SOP** | check each: `lot_number`, `batch_number`, `run_name`, `run_status`, `started_at`, `completed_at`, `started_by`, `execution_data` references | SOPs are pre-execution templates. Batch-specific values do not belong on the SOP, they belong on the Batch Record. Auditor will flag co-mingling. | Audit current `sop_default.docx`. Remove any reference to Run-level fields. Keep Protocol-level fields only (name, doc_number, effective_date, version, purpose, scope, references, definitions, revision_history, responsibilities, equipment_summary, procedure body, approval block). |
| N3 | `actual_value` column rendering | yes (per F-0087: must improve) | Currently renders the recorded value alone. GLP/GMP need: target value, units, recorded value, deviation indicator, operator initials, timestamp — in one cell or one row. | Refactor cell into a sub-table or stacked-RichText:<br>• Target: `{{ step.target }}` `{{ step.unit }}`<br>• Recorded: `{{ step.value }}` `{{ step.unit }}` `[Δ if out of tolerance]`<br>• `{{ step.initials }}` `{{ step.completed_at }}`<br>Use existing `step.value_display` RichText as the foundation and extend. |
| N4 | Any cell that pulls `pixelsPerHour` or `layout` direction | unknown — verify | These are editor-only state, not record fields (QA-0008 row #9, #11). | Strip if present in either default. |
| N5 | Per-step `figure_refs` rendered as raw `Run.attachments[i].id` | unknown — verify | Figure cross-references should render as "Figure N" — not raw IDs. QA-0008 implies this is already correct via `figure_map`; verify no leakage in defaults. | Verify in Phase 2 with rendered artifacts. |

---

## O. Summary of severities

| Severity | Count | IDs |
|---|---|---|
| **must-have** | 14 | A4, B1, B2, C1, C2, C4, E2, E3, E4, G4, G6 (policy), H1, H2, H3, H4, I4, J1, K4 |
| **should-have** | 16 | A2, A3, B3, B4, C3, D1, E1, E5, F1, G5, H5, I5, I6, J2, K2, K3, K5, L5, M5, M6 |
| **nice-to-have** | 6 | B6, D2, F2, F3, J3 |
| **extraneous (remove)** | 5 | N1, N2, N3, N4, N5 |

(Counts approximate; some IDs span categories.)

## P. Phase 2 scope recommendation

Per F-0087's intake: every **must-have** and **should-have** is in scope; gaps that imply >1 day of work or a discrete subsystem get spawned as sibling F-tickets.

### Land under F-0087

| Bucket | Findings | Notes |
|---|---|---|
| **Sign-off block (core known-fix)** | H2, H3, H4, K4, K5 | New `RunSignoff` table + UI + render. Pulls in K5 (signature image copy at sign time) as the only honest way to satisfy §11.70. |
| **Per-step reviewer endpoint + UI** | H1 | QA-0008 left the data shape; we land the endpoint + button. |
| **GLP Settings panel on protocol editor** | new — drives H3, H4, D1, K3, C3, E* opt-ins | `protocol.graph.glpSettings: {require_witness, require_qa_reviewer, require_environmental_steps: [step_id], block_expired_materials, step_attestation_text, witness_attestation_text, qa_attestation_text}`. Inspector-level new view when no node is selected. |
| **Reason-for-change** | I4 | New required field on EDITED transition; validator + UI prompt; render in BR. |
| **Run timestamps** | A4, G4, G5 | Add `Run.started_at`, `Run.completed_at`; add `execution_data[step_id].started_by_user_id`. |
| **Equipment refinement** | B1, B2 | Add `serial_number`, `last_calibrated_at`, `calibration_due_at`, `calibration_certificate_path` to Equipment. Warn (not block) on overdue. |
| **Disposition block on Batch Record** | L5 | Add `Run.disposition`, `disposition_at`, `disposition_by_id`. Tied to QA sign-off. |
| **Immutability gate** | J1 | Block `COMPLETED → EDITED` when QA sign-off exists; require explicit reopen. |
| **Protocol approval multi-stage** | H5, K2 | QA-0008's Migration C: add `ProtocolApprovalEvent.stage` enum; enforce `signature_statement NOT NULL` when APPROVED. |
| **Template cleanup** | N1, N2, N3, N4, N5 | The render-fix half of the F-0087 known-fix list. |

### Spawn sibling F-tickets (too large for F-0087)

| Sibling | Findings | Reason |
|---|---|---|
| **F-XXXX: Training & qualification records** | A3 | New domain (TrainingRecord model, expiry tracking, enforcement policy). Not blocking, not trivial. |
| **F-XXXX: Material lots & COAs** | C1, C2, C3, C4 | New domain (MaterialLot model, per-step `materials_used`, expiration warnings, COA storage). Big enough to warrant its own scope. |
| **F-XXXX: Deviation system (CAPA-lite)** | E1, E2, E3, E4, E5 | Promotes anomaly-flag-notes to dedicated RunDeviation model with closeout workflow. Discrete subsystem with its own UI surface. |
| **F-XXXX: Environmental capture per step** | D1 | Smaller, but enough surface (UI + JSONB + template render + opt-in setting) to bundle separately. |
| **F-XXXX: Sample identity (Phase 1)** | F1 | New domain (Sample model). Defer custody and retention until needed. |
| **F-XXXX: Calibration records** | B3 | Sibling of B1/B2 but historical-records story (CalibrationRecord child table); land after Equipment serial number lands. |
| **F-XXXX: Audit log coverage sweep** | I5 | Codebase sweep across all endpoints; not gated by F-0087. |

### Document-only (no code under F-0087)

- B6 (IQ/OQ/PQ records) — boundary documentation in CSV package.
- D2 (continuous environmental monitoring) — boundary documentation.
- F2, F3 (chain of custody, retention) — boundary documentation.
- I6 (audit-log DB-level immutability) — CSV documentation.
- J3 (record retention) — CSV documentation.
- M5, M6 (device loss, system validation) — handled by F-0037 (offline) + customer CSV package.

---

## Q. Open questions deferred to Phase 2 design

These are the questions Phase 2 brainstorming will resolve. They are *not* gaps; they are design decisions.

1. **Where does `glpSettings` live?** Top-level key in `Protocol.graph` JSONB (zero-migration) vs first-class column on `Protocol`. Recommendation: graph JSONB, mirrored to `ProtocolVersion.graph` like other graph state. Decide in Phase 2.
2. **Signature image copy semantics (K5).** When does the copy happen — on `POST /signoffs` or lazily at first render? Recommendation: on sign (matches §11.70 "linked at signing time").
3. **Reopen UX (J1).** Single-button "reopen for correction" with a required reason, or an explicit "void this batch record" + start new? Recommendation: reopen-with-reason; the audit trail records the reopen event and nullifies the QA sign-off. Decide in Phase 2 brainstorming.
4. **Disposition + QA sign-off coupling (L5 ↔ H4).** Is QA sign-off the trigger for disposition, or are they separate? Recommendation: separate but co-located in UI ("approve & release" or "approve & reject"). Decide in Phase 2.
5. **Default attestation text per role (K4).** What does "I attest…" actually say by default? Industry-standard wording is needed. Recommendation: copy verbiage from a few public BR templates (Cytiva, AbbVie samples); have a CSV/QA reviewer (or counsel) review the defaults before customer-facing. Phase 2 lands the field; the *content* is a separate review.

---

## R. Verification of audit completeness

I checked the following surfaces, in order:

- `backend/app/models/science.py` — all model definitions (Protocol, Run, ProtocolVersion, Equipment, ProtocolApprovalEvent, ProtocolApprovalRequest, RunRoleAssignment).
- `backend/app/models/iam.py` — User signature fields.
- `backend/app/models/execution.py` — AuditLog.
- `backend/app/api/endpoints/runs.py` — run lifecycle transitions (PLANNED → ACTIVE → COMPLETED → EDITED).
- `backend/app/services/protocols/template_engine.py` — KNOWN_VARIABLES, `build_context`, `render_to_docx`, signature swap, `value_display` RichText.
- `backend/app/services/documents/templates/` — confirmed `sop_default.docx` + `batch_record_default.docx` exist (binary; structural review deferred to Phase 2 visual pass).
- `frontend/src/lib/components/protocol/` — inspector is node-centric; no protocol-level settings panel.
- `frontend/src/lib/components/run/` — no run-completion sign-off surface today.
- `docs/superpowers/specs/2026-05-14-qa-0008-production-templates-design.md` — full QA-0008 catalog; this audit builds on it without duplicating gaps already closed there.

Surfaces not exhaustively inspected (low expected gap density):
- Chat-agent tool surfaces (not GxP-record-bearing).
- Background jobs (operationally GxP-adjacent but not on the record path).

If Phase 2 implementation uncovers a record-bearing surface I missed, it gets logged here as an addendum.
