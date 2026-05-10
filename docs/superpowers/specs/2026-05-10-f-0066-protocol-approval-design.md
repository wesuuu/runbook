# F-0066 — Protocol Approval & Digital Signatures (Design Spec)

**Status:** Draft for approval
**Date:** 2026-05-10
**ClickUp:** https://app.clickup.com/t/86e0qj1uj
**Prereq:** TD-0084 — shipped (`OrgRole.PROTOCOL_APPROVER`, `OrganizationMember.roles: list[str]`)

---

## 1. Goal

Close the gap between the half-built approval surface and a complete, auditable approval & signature flow, and surface that history inside generated SOP/batch-record documents.

---

## 2. State machine

```
            designate=true (creator/admin, status=DRAFT)
DRAFT ─────────────────────────────────────────────────▶ DRAFT (requires_approval=true)
                                                                   │
                                                          submit-for-approval
                                                          (creator/editor; pick approvers)
                                                                   │
                                                                   ▼
                                                           PENDING_APPROVAL
                                                            │           │
                                                       approve     reject (comment)
                                                            │           │
                                                            ▼           ▼
                                                        APPROVED      DRAFT
                                                            │
                                          edit graph/name/description
                                          (creator + project ADMIN +
                                           project APPROVER + org PROTOCOL_APPROVER)
                                                            │
                                                            ▼
                                              DRAFT (REVERTED event), requires_approval=true
```

`requires_approval` can be flipped back to `false` only by the creator or a project admin **and only when status = DRAFT**. PENDING_APPROVAL must be withdrawn (rejected by self or an approver) before un-designation.

---

## 3. Data model

### 3.1 Schema additions

**`Protocol`** (modify):
- `requires_approval: bool` — default `False`. NOT NULL. New protocols start `False`.
- `created_by_id: UUID | None` — FK `users.id`, nullable, ON DELETE SET NULL. Backfill from the v1 `ProtocolVersion.created_by_id` of each protocol; rows with no v1 creator stay NULL.
- `approved_by_id: UUID | None` — FK `users.id`, nullable, ON DELETE SET NULL. Set on approve, cleared on revert.
- `approved_at: datetime | None` — timestamptz, nullable. Set on approve, cleared on revert.

**`Run`** (modify):
- `is_strict: bool` — default `False`. NOT NULL. Snapshot at run creation from `protocol.requires_approval`.

**`protocol_approval_events`** (new):

| col | type | notes |
| --- | --- | --- |
| `id` | UUID PK | |
| `protocol_id` | UUID FK protocols.id | indexed |
| `protocol_version_id` | UUID FK protocol_versions.id, NULL | snapshotted version at event time |
| `actor_id` | UUID FK users.id, NULL ON DELETE SET NULL | |
| `action` | varchar(20) | CHECK in `('SUBMITTED','APPROVED','REJECTED','REVERTED')` |
| `comment` | text NULL | required for REJECTED |
| `signature_statement` | text NULL | for APPROVED |
| `created_at` | timestamptz NOT NULL | server default `now()` |

Index on `(protocol_id, created_at DESC)`.

**`protocol_approval_requests`** (new):

| col | type | notes |
| --- | --- | --- |
| `id` | UUID PK | |
| `protocol_id` | UUID FK protocols.id | indexed |
| `requested_user_id` | UUID FK users.id, NULL ON DELETE SET NULL | |
| `requested_by_id` | UUID FK users.id, NULL ON DELETE SET NULL | |
| `status` | varchar(20) | CHECK in `('OPEN','APPROVED','REJECTED','WITHDRAWN')`; default `'OPEN'` |
| `fulfilled_at` | timestamptz NULL | |
| `fulfilled_by_id` | UUID FK users.id, NULL | actor that closed it |
| `created_at` | timestamptz NOT NULL | |

Unique partial index on `(protocol_id, requested_user_id) WHERE status = 'OPEN'` so a user can't have two open requests for the same protocol.

### 3.2 Migration

One Alembic revision: `f0039_protocol_approval`. Down-revision is the current head (will be resolved at implementation time). Includes:
- Add columns to `protocols` and `runs`.
- Backfill `protocols.created_by_id` from v1 `protocol_versions.created_by_id`.
- Create the two new tables.

`requires_approval` and `is_strict` are **not** backfilled — explicitly out of scope per task.

---

## 4. IAM

Edit `backend/app/services/core/permissions.py` `check_permission`:

After the existing `OrgRole.ADMIN` bypass (around line 122), add: if `obj.object_type == ObjectType.PROTOCOL` AND the membership has `OrgRole.PROTOCOL_APPROVER`, grant **VIEW**, **EDIT**, **APPROVE** for any protocol in the same organization. ADMIN-level on protocols is **not** granted.

This deliberately gives no project-level access (they cannot list runs, see project members, etc.). They reach individual protocols via the "awaiting my approval" endpoint or a direct URL.

---

## 5. Endpoints

All paths prefixed with `/api/v1`.

### 5.1 Modify

**`POST /science/protocols/{protocol_id}/submit-for-approval`** (`protocol_versions.py:217–269`)

Body:
```json
{ "requested_user_ids": ["uuid", "uuid", ...] }
```
- 400 if `protocol.requires_approval = false`.
- 400 if status not DRAFT.
- 400 if `requested_user_ids` is empty OR contains a user that has neither project APPROVE nor org PROTOCOL_APPROVER.
- Sets status PENDING_APPROVAL, writes `SUBMITTED` event (no signature), inserts one `protocol_approval_requests` row per requested user (status OPEN), and creates a notification per requested user via the existing notification service (new type: `PROTOCOL_APPROVAL_REQUESTED`).

**`POST /science/protocols/{protocol_id}/approve`**

Body:
```json
{ "comment": "optional", "signature_statement": "optional" }
```
- Caller must have project APPROVE on parent project OR org PROTOCOL_APPROVER (covered by `check_permission`).
- Sets status APPROVED, sets `protocol.approved_by_id` (new field on Protocol — see below) & `approved_at`.
- Writes `APPROVED` event with the signature_statement.
- Marks **all** open `protocol_approval_requests` for this protocol as `APPROVED` (single approver suffices — out of scope: N-of-M).
- Audit log entry.

**`POST /science/protocols/{protocol_id}/reject`**

Body:
```json
{ "comment": "required", "signature_statement": "optional" }
```
- 422 if comment missing/empty.
- Sets status DRAFT.
- Writes `REJECTED` event.
- Marks all open `protocol_approval_requests` `REJECTED`.

**`PATCH/PUT /science/protocols/{protocol_id}`** (graph/name/description) — `protocols.py:533–574`
- Edit lock now applies to `name`, `description`, **and** `graph` (today only `graph`).
- While `status = APPROVED`, allowed editors: creator, project ADMIN, project APPROVER, org PROTOCOL_APPROVER. Anyone else → 403.
- On a successful edit while `status = APPROVED`: status → DRAFT, write `REVERTED` event, clear `approved_by_id`/`approved_at`, leave `requires_approval` as-is. Audit log.

**`POST /science/runs`** — `runs.py:75–93`
- New gate: when `project.settings.require_protocol_approval` AND `protocol.requires_approval` AND `protocol.status != 'APPROVED'` → 400 with code `PROTOCOL_NOT_APPROVED`.
- Snapshot `run.is_strict = protocol.requires_approval` (independent of project setting — once a protocol opts in to approval, its runs are always strict).

**Override endpoints** (`runs.py:162` `OVERRIDE_SET`, `runs.py:543` `OVERRIDE_EDIT`)
- Reject 403 with code `RUN_IS_STRICT` when `run.is_strict`.

**Protocol designation endpoint** (new, simplest place is `protocols.py`):
**`POST /science/protocols/{protocol_id}/designate-approval`**

Body:
```json
{ "requires_approval": true }
```
- Caller must be the protocol creator (`protocol.created_by_id`) OR project ADMIN.
- Setting to `true`: requires project setting `require_protocol_approval = true`; status must be DRAFT.
- Setting to `false`: status must be DRAFT.
- Idempotent (no-op if already in target state).

### 5.2 New

**`GET /science/protocols/{protocol_id}/approval-history`**
- Caller needs VIEW on the protocol (existing perm pattern).
- Returns events ordered `created_at DESC`, eager-loading actor: `[ { id, action, comment, signature_statement, actor: { id, name, email }, protocol_version: { id, version_number } | null, created_at }, ... ]`.

**`GET /science/protocols/awaiting-my-approval`**
- For the current user, returns protocols where:
  - There is an OPEN `protocol_approval_requests` row for me, OR
  - I have org PROTOCOL_APPROVER and the protocol is PENDING_APPROVAL in my org (deduped).
- Lightweight projection: `[ { protocol_id, name, project_id, project_name, organization_id, submitted_at, submitted_by: { id, name } } ]`.

### 5.3 Schema/response changes

**`ProtocolResponse`** gains: `requires_approval`, `created_by_id`, `approved_by_id`, `approved_at`, `latest_signature_statement`, `latest_approval_comment`. Last two are derived from the most recent APPROVED event (None if never approved).

**`RunResponse`** gains: `is_strict`.

**New schemas:**
- `SubmitForApprovalRequest { requested_user_ids: list[UUID] }`
- `ApproveProtocolRequest { comment: Optional[str], signature_statement: Optional[str] }`
- `RejectProtocolRequest { comment: str, signature_statement: Optional[str] }`
- `DesignateApprovalRequest { requires_approval: bool }`
- `ProtocolApprovalEventResponse { id, action, comment, signature_statement, actor, protocol_version, created_at }`
- `AwaitingMyApprovalItem { protocol_id, name, project_id, project_name, organization_id, submitted_at, submitted_by }`

---

## 6. SOP / Batch-record templates

### 6.1 Template engine

`backend/app/services/protocols/template_engine.py` — extend `KNOWN_VARIABLES`:
- `approval` (dict or None)
- `approval_history` (list)
- `unapproved_warning` (bool)

`approval` shape when present:
```
{
  "approver_name": str,
  "approver_email": str,
  "approved_at": datetime,
  "signature_statement": Optional[str],
  "signature_image_path": Optional[str],   # absolute path to PNG; renderer embeds
  "protocol_version": int,
}
```

`approval_history` shape (most recent first):
```
[
  {"action": "APPROVED", "actor_name": str, "comment": Optional[str],
   "signature_statement": Optional[str], "created_at": datetime},
  ...
]
```

`unapproved_warning` is `True` when `project.settings.require_protocol_approval AND protocol.requires_approval AND protocol.status != 'APPROVED'`.

### 6.2 Default DOCX templates

Edit `sop_default.docx` and `batch_record_default.docx`. Append a new section "Approval & Signatures":

- If `unapproved_warning`: a single boxed line in red — "Unapproved — Draft Only". Skip the rest.
- If `approval` present:
  - Approver name, date (formatted `YYYY-MM-DD HH:MM`), protocol version.
  - Embedded full signature image (`signature_image_path`) sized ~150x60 px. Falls back to a cursive-font rendering of approver name when no path.
  - Signature statement quote (italic) when present.
- "Approval History" subsection: bulleted list iterating `approval_history`.

### 6.3 Signature helper

`backend/app/api/endpoints/protocol_pdfs.py:35–60` `_build_user_signatures` — extend the dict it returns to include `signature_full_path` (absolute path) alongside the existing initials. The SOP/batch context builders use the helper and feed it into `approval.signature_image_path`.

The cursive fallback for "no saved signature" is rendered by python-docx as text with a script font (e.g., "Brush Script MT" / fallback to italic) — **no image generation**.

---

## 7. Frontend

### 7.1 New components

| File | Purpose |
| --- | --- |
| `lib/components/protocol/ApprovalDesignator.svelte` | Toggle + helper text in ProtocolSidebar to flip `requires_approval`. Visible only to creator/project admin. Disabled (with reason tooltip) when state machine forbids the change. |
| `lib/components/protocol/ApprovalHistory.svelte` | Vertical timeline of events. Renders inside ProtocolSidebar as a collapsible section (NOT a separate Inspector tab — see Section 9 note). Lazy-fetches `/approval-history` on first expand. |
| `lib/components/protocol/ApprovalSignatureDialog.svelte` | Modal opened by Approve/Reject. Approve mode: optional `signature_statement` textarea + preview of saved signature image (or cursive-name fallback). Reject mode: required `comment` textarea, signature optional. Confirm posts the appropriate endpoint. |
| `lib/components/protocol/SubmitForApprovalDialog.svelte` | Modal opened by "Submit for Approval". Multi-select of eligible approvers (project APPROVE users + org PROTOCOL_APPROVER members), grouped headers. Confirm posts `/submit-for-approval`. |
| `lib/components/protocol/RevertOnEditConfirmDialog.svelte` | Reusable confirm modal: "Editing will revert this protocol from APPROVED to DRAFT and require re-approval. Continue?" Triggered the first time the user makes a graph/name/description edit on an APPROVED protocol in a session. |
| `lib/components/settings/ProtocolApproversCard.svelte` | Lives on the org settings page. Lists members with `roles` containing PROTOCOL_APPROVER, lets ADMINs add/remove. Wraps existing org-member endpoints from TD-0084. |
| `lib/components/shared/PendingApprovalsCard.svelte` | Dashboard card listing protocols awaiting the current user's approval. Pulls `/awaiting-my-approval`. Empty state hidden (don't render the card). |

### 7.2 Modifications

| File | Change |
| --- | --- |
| `lib/components/protocol/ProtocolSidebar.svelte` | Mount `<ApprovalDesignator>` (in the existing approval-required area), `<ApprovalHistory>` (new collapsible section beneath status), and Submit/Approve/Reject buttons that open the new dialogs. Buttons gated by status + permission. |
| `lib/components/run/RunOverridesEditor.svelte` | New prop `isStrict: boolean`. When true, render a banner "Overrides disabled — protocol is approved & strict" instead of the editor. |
| `lib/components/run/RunCreatorUnitOpCard.svelte` | New prop `isStrict: boolean`. Hide override controls when true. |
| `lib/components/project/ProtocolsTab.svelte` | New columns/badges: "Requires approval" pill; for APPROVED rows show approver name + date in a tooltip on the status badge. |
| `lib/components/project/SettingsTab.svelte` | Add helper text under the existing `require_protocol_approval` toggle: "When enabled, protocols can be marked as requires-approval and runs are blocked until approved. Approvers are managed per project below, and globally in Org Settings." |
| `routes/+page.svelte` (dashboard) | Mount `<PendingApprovalsCard>` near the top of the home page when the response is non-empty. |
| `routes/protocols/[id]/+page.svelte` | Hook in `<RevertOnEditConfirmDialog>` — wrap the first onChange while status=APPROVED with the confirmation. State flag `revertConfirmedThisSession`. |
| `routes/runs/[id]/+page.svelte` and the run-creator route | Pass `isStrict` (from `run.is_strict`) into RunOverridesEditor / RunCreatorUnitOpCard. |

### 7.3 API client

Add to `lib/api.ts`:
```ts
designateProtocolApproval(id, requires_approval)
submitProtocolForApproval(id, requested_user_ids)
approveProtocol(id, { comment, signature_statement })
rejectProtocol(id, { comment, signature_statement })
getProtocolApprovalHistory(id)
getAwaitingMyApproval()
```

Zod schemas in `lib/schemas/` for the new request/response shapes.

---

## 8. Tests

### Backend (pytest)
- `tests/integration/test_protocol_approval_designate.py` — designation perms, state-machine rules.
- `tests/integration/test_protocol_approval_submit.py` — submit gates, request rows created, eligibility check.
- `tests/integration/test_protocol_approval_approve_reject.py` — events written, requests fulfilled, project-vs-org approver, signature_statement persisted, comment-required-on-reject.
- `tests/integration/test_protocol_approval_history.py` — ordering, eager load, permission gating.
- `tests/integration/test_protocol_approval_awaiting_me.py` — both code paths (open request + org role), dedupe.
- `tests/integration/test_protocol_edit_lock.py` — lock applies to name/description/graph; auto-revert on edit by authorized actor while APPROVED; REVERTED event written.
- `tests/integration/test_run_approval_gate.py` — block when ungated, snapshot is_strict, override-block 403s.
- `tests/integration/test_protocol_pdf_approval_section.py` — context builder yields the right `approval` / `approval_history` / `unapproved_warning`; with and without saved signature.
- `tests/unit/test_permissions_protocol_approver.py` — org PROTOCOL_APPROVER passes VIEW/EDIT/APPROVE on protocol, fails on project/run/document.

Coverage target ≥80% on every touched file.

### Frontend (vitest)
- `ApprovalDesignator.test.ts` — disabled states reflect status + perms.
- `ApprovalHistory.test.ts` — empty state, fetch on expand, ordering.
- `SubmitForApprovalDialog.test.ts` — disable submit when no approvers chosen, eligible list grouping.
- `ApprovalSignatureDialog.test.ts` — reject requires comment; approve doesn't.
- `RevertOnEditConfirmDialog.test.ts` — fires on first edit only when status=APPROVED.
- `RunOverridesEditor.test.ts` — extend existing tests; assert banner replaces editor when `isStrict=true`.
- `PendingApprovalsCard.test.ts` — hides when empty, renders rows when populated.

### Browser (qa-verify agent)
End-to-end golden path: designate → submit → approve → run-create succeeds → override blocked → edit graph → confirm dialog → revert. PDF download includes the approval section.

---

## 9. Notes / refinements from brainstorming

- **Approval History placement:** the brainstorming question framed Inspector vs panel vs modal, and Inspector won. After looking at the actual components: Inspector is strictly node-focused (selected node's params), and ProtocolSidebar already owns protocol-level metadata (name, status, requires_approval, version, save buttons). Putting an `<ApprovalHistory>` collapsible section inside **ProtocolSidebar** is the cleanest fit. If the user prefers a true Inspector tab, we can swap by lifting the component into a `<Tabs>` wrapper there instead — call out before implementing.
- **Designation flow:** two-step (designate → submit) chosen.
- **Edit revert UX:** confirmation dialog before the first edit in a session.
- **Un-designate:** allowed by creator/admin while status=DRAFT only.
- **No PKI** — typed statement + drawn signature image (F-0080) only.

---

## 10. File touch list

**Backend (modify):** `models/science.py`, `services/core/permissions.py`, `api/endpoints/protocol_versions.py`, `api/endpoints/protocols.py`, `api/endpoints/runs.py`, `api/endpoints/protocol_pdfs.py`, `services/protocols/template_engine.py`, `schemas/science.py`, `services/documents/templates/sop_default.docx`, `services/documents/templates/batch_record_default.docx`.

**Backend (new):** `alembic/versions/f0039_protocol_approval.py`, `services/approvals/__init__.py` + `events.py` (helper that writes events + audit log to keep endpoint code thin), `services/approvals/awaiting.py` (helper for the awaiting-me query), `tests/integration/test_protocol_approval_*` and `tests/unit/test_permissions_protocol_approver.py`.

**Frontend (new):** components per Section 7.1.

**Frontend (modify):** files per Section 7.2.

---

## 11. Out of scope

PKI / cert signatures. N-of-M / sequential approvals. Run-step e-sig. Removing org approvers with active pending requests (will fail with 409 for now — handle in a follow-up). Backfilling `requires_approval` for existing protocols.
