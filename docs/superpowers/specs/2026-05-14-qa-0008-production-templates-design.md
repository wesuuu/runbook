# QA-0008 — Production-grade SOP + Batch Record templates

## Problem

Before declaring the protocol + batch record templating system production-ready, we need two production-grade `.docx` templates — one SOP, one Batch Record — that exercise the full set of Jinja2 variables, conditionals, and loops that a protocol can have. The current system defaults render a subset of the protocol model; several model fields and GxP-typical surfaces aren't reachable from a template today.

This task delivers those two templates, closes the backend gaps so every protocol feature has a Jinja surface, and ships them as the system defaults.

## Goals

- Two `.docx` templates that read like real SOP / Batch Record documents and use every relevant Jinja directive.
- A unified catalog of "what a protocol can carry" → "what the template renders it as", with no row left unreachable.
- Backend additions (`build_context`, `KNOWN_VARIABLES`, models, JSONB shapes) so every catalog row can flow to a template.
- A small frontend addition: `lot_number` and `batch_number` inputs on the Run-start dialog. Other UI surfaces (Protocol metadata form, reviewer-signature button) are filed as follow-up F-tickets.
- Verification: pytest fixtures across 6 permutations that prove every conditional fires in both directions.
- Replace the existing system-default SOP and Batch Record templates.

## Non-goals

- No swap of the templating engine. We stay on `docxtpl` + LibreOffice headless. The dual-Jinja-layer wart (regex `{{key}}` pass in `pdf_base.py` co-existing with docxtpl's own Jinja) stays unless an audit gap forces the consolidation.
- No HTML preview pipeline. That's a worthwhile follow-up; out of scope here.
- No deep editor / frontend UX work beyond the `lot_number` / `batch_number` inputs. Other new model fields populate via test fixtures and follow-up tickets.
- No production-quality re-design of how approvals or signatures work; we only surface what the model already supports.
- No Equipment model enrichment (serial numbers etc.). Surface what exists; file a follow-up if missing fields block rendering.

## Decisions locked in brainstorming

| Decision | Choice | Rationale |
| --- | --- | --- |
| Source SOP+BR origin | I author. | Avoids proprietary / copyright concerns; I control complexity. |
| Process domain | Cell culture + harvest. | User selection. Irrelevant to coverage; the templates are the artifact. |
| Gap policy | Fix every gap in this task. | User selection, "no ceiling". |
| Stop condition | Catalog matrix green + user signoff. | Bounded, concrete, matches the user's chosen ceiling. |
| Templates replace existing system defaults | Yes. | "Production grade" implies this. |
| Catalog driver | Data model first, GxP-informed second. | Floor (anything we store, we render); ceiling (GxP layer surfaces additional needs). |
| One BR template vs split | One BR template with sibling `{%tc if%}` directives. | Split criterion (>3 nested) not met; downstream resolver / preview / blank-download / completed-download surface adds disproportionate cost. Re-evaluate at phase-3 author time if it reads terribly. |
| Run type discriminator | None. `lot_number` presence is the signal. | Same Run model for experiments and production; nullable fields gate the BR. |
| Frontend scope | `lot_number` + `batch_number` inputs only. | Other UI is net-new editor surface; file as F-tickets. |
| Endpoint coverage | One end-to-end endpoint test for P1; rest at `build_context` level. | Proves integration path without seeding 6 protocols. |
| Verification strategy | Tests + rendered artifacts only — no DB seed CLI. | The templates are the deliverable; the rest is testing scaffolding. |

## Architecture

Four phases. Each phase produces a discrete commit set (see "Commit shape" below).

```
Phase 1 — Catalog (this doc + gap-log.md)
Phase 2 — Close backend gaps (models, migrations, build_context, KNOWN_VARIABLES, render_to_docx, lot/batch UI)
Phase 3 — Author SOP.docx + BatchRecord.docx; replace system defaults in template_seeder.py
Phase 4 — Verification: 6 permutations as pytest fixtures + rendered artifacts + your signoff
```

The implementation pattern stays consistent with `.claude/rules/conventions.md` and `.claude/rules/backend-services.md`: stateless module functions in `app/services/protocols/template_engine.py`, models in `app/models/science.py`, migrations under `alembic/versions/`.

---

## Section 1 — Catalog

The catalog is the source of truth for what the templates must render. Two halves: data-model rows (the floor) and GxP rows (the ceiling).

### 1.1 — Data-model catalog

Legend: ✅ = currently in `KNOWN_VARIABLES` / surfaced by `build_context()`. ⚠️ = data exists in the model/JSONB but is not surfaced. ❌ = data isn't in the model at all.

| # | Catalog item | Data source | Surface today | Jinja directive needed |
|---|---|---|---|---|
| **DM — Document metadata** | | | | |
| 1 | Protocol name | `Protocol.name` | ✅ `{{ protocol_name }}` | text |
| 2 | Protocol description | `Protocol.description` | ✅ `{{ protocol_description }}` | text + `{% if %}` |
| 3 | Version number | `Protocol.version` | ✅ `{{ version_number }}` | text |
| 4 | Created date | `Protocol.created_at` | ✅ `{{ created_at }}` | text |
| 5 | Project name | `Project.name` | ✅ `{{ project_name }}` | text |
| 6 | Organization name | `Organization.name` | ✅ `{{ organization_name }}` | text |
| **GS — Graph structure** | | | | |
| 7 | Role-based vs flat | derived (graph has lanes) | ✅ `is_role_based` | top-level `{% if is_role_based %}…{% else %}…{% endif %}` |
| 8 | Time-enabled (column visibility) | `graph.timeEnabled` | ⚠️ not in context | `{%tc if time_enabled %}` |
| 9 | Layout direction | `graph.layout` | ⚠️ not in context | intentionally not surfaced — editor-only state |
| 10 | Schedule start time | `graph.startTime` | ⚠️ not in context | text |
| 11 | Pixels per hour | `graph.pixelsPerHour` | n/a | intentionally not surfaced |
| **RL — Roles & lanes** | | | | |
| 12 | Role list (in graph order) | `roles_with_steps` | ✅ `{% for role in roles %}` | outer loop |
| 13 | Role name / process name / process description | `role.role_name`, `role.process_name`, `role.process_description` | ✅ via RichText pre-compute | per-role header |
| 14 | Role color (lane swatch) | swimLane node `data.color` | ⚠️ not in context | optional inline color marker |
| 15 | Steps under each role | `role.steps` | ✅ `{% for step in role.steps %}` | nested loop |
| **ST — Per-step content (SOP-shaped)** | | | | |
| 16 | Step name | `step.name` | ✅ `{{ step.name }}` | text |
| 17 | Step description (with `{{ }}` interpolation) | `step.description` | ✅ via `_render_template` regex pass | text |
| 18 | Pre-computed SOP body (RichText) | derived: desc + params + duration | ✅ `{{r step.sop_body }}` | RichText |
| 19 | Param sentence ("Set X to Y") | derived from `step.params` + `param_schema` | ✅ inside `sop_body` | text |
| 20 | Duration (minutes) | `step.duration_min` | ✅ `{{ step.duration_min }}` | text + `{% if %}` |
| 21 | Multi-param steps | `len(editable_params) > 1` | ✅ `{{ step.has_multi_params }}` | `{% if step.has_multi_params %}` |
| 22 | Single-param value | `step.single_value` | ✅ | `{% if step.single_value %}` |
| 23 | Step parameters (raw dict) | `step.params` | ✅ `{{ step.params.<key> }}` | text |
| 24 | Param schema (label, unit, type) | `step.param_schema` | partial (internal) | — |
| **EX — Execution state (BR only)** | | | | |
| 25 | (Dropped — `step.status` is internal plumbing, not a template surface.) | — | — | — |
| 26 | Completed timestamp | `execution_data[id].completed_at` | ✅ inside step_ctx | text |
| 27 | Recorded value display (with GMP strikethrough) | derived RichText `value_display` | ✅ `{{r step.value_display }}` | RichText |
| 28 | Multi-param details list | derived `param_details` | ✅ `{% for pd in step.param_details %}` | inner loop + `{% if pd.is_edited %}` |
| 29 | Original value (pre-edit) | `original_results[key]` | ✅ inside param_details | conditional |
| 30 | Editor initials | `umap.get(edited_by_user_id)` | ✅ | conditional |
| 31 | Edit date | `execution_data[id].edited_at` | ✅ | conditional |
| 32 | Step-level operator initials | `_resolve_initials()` | ✅ `{{ step.initials }}` | `{% if step.initials %}` |
| 33 | Step-level notes text | `execution_data[id].notes` | ✅ `{{ step.notes_text }}` | `{% if step.notes_text %}` |
| 34 | Step-level scheduled time | derived: `start_time` + cumulative duration | ❌ not computed anywhere | new field; gated by `{%tc if time_enabled %}` |
| 35 | Step-level actual start time | no `started_at` in `execution_data` | ❌ | gap — see Half B |
| **AP — Approvals & signatures** | | | | |
| 36 | Approval block (single, latest) | `_build_approval_context()` | ✅ `{{ approval.* }}` | `{% if approval %}…{% else %}{{ unapproved_warning }}{% endif %}` |
| 37 | Approval signature image (drawn) | `approval.signature_image` | ✅ | `{% if approval.signature_image %}` |
| 38 | Approver name / role / date | `approval.actor_name`, `actor_role`, `approved_at` | ✅ | text |
| 39 | Signature statement | `approval.signature_statement` | ✅ | `{% if approval.signature_statement %}` |
| 40 | Approval history (multi-event) | `approval_history` | ✅ `{% for event in approval_history %}` | loop + `{% if approval_history|length > 1 %}` |
| 41 | Unapproved warning text | `unapproved_warning` | ✅ | text in `{% else %}` |
| 42 | Multi-stage approval (operator → reviewer → QA) | only single approver currently | ❌ | gap — see Half B |
| **NF — Notes, figures, attachments** | | | | |
| 43 | Run-level notes (chronological) | `Run.notes` | ✅ `{% for note in notes %}` | loop |
| 44 | Note author / timestamp / content | per-note fields | ✅ | text |
| 45 | Note anomaly flag → "[ANOMALY]" prefix | `note.flags` | ✅ in built context | currently flattened to prefix; could expose flag |
| 46 | Figure list (image attachments) | `Run.attachments` filtered | ✅ `{% for fig in figures %}` | loop |
| 47 | Figure inline image | `InlineImage` swap in `render_to_docx` | ✅ `{{ fig.image }}` | image |
| 48 | Figure metadata (number, filename, step scope, upload time) | derived | ✅ | text |
| 49 | Step → figure cross-references | `figure_refs` | ✅ inside `notes_display` | text |
| 50 | Non-image attachments list | filtered | ✅ `{% for att in non_image_attachments %}` | loop + `{% if %}` |
| **EQ — Equipment** | | | | |
| 51 | Equipment interpolation tokens (`{{E-001_name}}`) | `equipment_context` flat dict | ✅ via `_render_template` regex pass | inline in step desc |
| 52 | Equipment summary list (all equipment used) | derivable from graph nodes | ❌ not in context | new field; loop |
| 53 | Per-step equipment list | `node.data.equipment` | ❌ not surfaced per step | new step_ctx field; loop |
| **PG — Page break / layout** | | | | |
| 54 | Inline page break token | `page_break` (RichText `\f`) | ✅ `{{r page_break }}` | direct |
| 55 | Page break before each role | RichText embedded in `sop_header` | ✅ | — |

### 1.2 — GxP layer & gaps to close

| # | GxP item | Status | Proposed fix |
|---|---|---|---|
| **B1** | Document number / control ID | ❌ | Add `Protocol.doc_number: str?`; surface as `{{ doc_number }}` |
| **B2** | Effective date / supersedes date | ❌ | Add `Protocol.effective_date`, `Protocol.supersedes_date` (nullable) |
| **B3** | Revision history | ⚠️ `ProtocolVersion` exists but not surfaced | Build `revision_history` context list from `ProtocolVersion` rows |
| **B4** | Purpose / Scope / References / Definitions sections | ⚠️ only `description` | Add nullable text fields; gate with `{% if %}` |
| **B5** | Responsibilities matrix | ⚠️ derivable from roles + role-gated steps | Build `responsibilities` context (role → step summary) |
| **B6** | Multi-stage approval (operator → reviewer → QA) | ⚠️ depends on `ProtocolApprovalEvent` current shape | Read model first; add `stage` enum + migration if missing |
| **B7** | Step-level reviewer signature (two-signature workflow) | ❌ | Add `reviewed_by_user_id` + `reviewed_at` to `execution_data` JSONB; mirror operator-initials swap |
| **B8** | Deviation log | ⚠️ hack via `anomaly` flag on notes | Template-side filter: `deviations` = `notes` where `"anomaly" in flags`. Promote to dedicated field only if audit shows it insufficient. |
| **B9** | Scheduled vs actual times per step | ⚠️ duration exists, scheduled derivable, actual start missing | Add `started_at` to `execution_data` JSONB; compute `scheduled_at` in `build_context`; expose triple gated by `{%tc if time_enabled %}` |
| **B10** | Equipment summary table | ❌ | Walk graph nodes once, expose `equipment_summary: list[...]` |
| **B11** | Per-step equipment list | ❌ | Add `equipment` list per step_ctx |
| **B12** | Header/footer (org, doc number, page X of Y) | depends on .docx | Word headers/footers natively; Word fields for page numbers |
| **B13** | "Continued on next page" | docxtpl + Word native | — |
| **B14** | Glossary / abbreviations | YAGNI for now | Free-form `Protocol.definitions` covers it |
| **B15** | Run-level lot_number / batch_number | ❌ | Add `Run.lot_number`, `Run.batch_number` (nullable). `lot_number` presence is the experiment-vs-production signal. |
| **B16** | Final disposition / release statement | ❌ | Decide at phase-3 author time: piggyback on final approval or add a release block. Free-form text gated by `{% if %}`. |

### 1.3 — Catalog summary

- 54 data-model rows (after dropping #25). Most surfaced; major gaps are time-enabled context (#8, #34), equipment summaries (#52, #53).
- 16 GxP rows. Largest is B7 (per-step reviewer signature).
- Estimated migrations: 2 confirmed (Protocol metadata; Run.lot/batch), 1 conditional (approval stage if B6 forces it).
- No-migration JSONB additions: `execution_data` gets `started_at`, `reviewed_by_user_id`, `reviewed_at`.

---

## Section 2 — Phase 2: Close backend gaps

Ordered execution. TDD per item. Stateless module functions per Pattern A in `backend-services.md`.

### 2.1 — Migrations

**Migration A — Protocol GxP metadata** (`Protocol` + `ProtocolVersion` snapshot columns)

| Field | Type | Source row |
|---|---|---|
| `doc_number` | `str?` | B1 |
| `effective_date` | `date?` | B2 |
| `supersedes_date` | `date?` | B2 |
| `purpose` | `text?` | B4 |
| `scope` | `text?` | B4 |
| `references` | `text?` | B4 |
| `definitions` | `text?` | B4 |

Mirror columns on `ProtocolVersion` so version snapshots carry the metadata. Skip `glossary: dict` (B14) — YAGNI.

**Migration B — Run production metadata**

| Field | Type |
|---|---|
| `lot_number` | `str?` |
| `batch_number` | `str?` |

**Migration C (conditional) — `ProtocolApprovalEvent.stage`**

Read `ProtocolApprovalEvent` / `ProtocolApprovalRequest` first. If multi-stage is already supported, no migration. If not, add `stage: enum("operator"|"reviewer"|"qa")` with default `"qa"` for backward compat.

### 2.2 — JSONB-shape additions (no migration)

Per-step `execution_data[step_id]` gains optional fields:

| Field | Source row |
|---|---|
| `started_at: str?` | B9 / #35 |
| `reviewed_by_user_id: str?` | B7 |
| `reviewed_at: str?` | B7 |

Schema-less; documented in the `Run` model docstring. API endpoints that set them are filed as follow-up F-tickets.

### 2.3 — `build_context()` extensions

In `backend/app/services/protocols/template_engine.py`:

| Addition | Source data | New context keys |
|---|---|---|
| Time-axis surface | `graph.timeEnabled`, `graph.startTime` | `time_enabled: bool`, `start_time: str` |
| Per-step scheduled time | derived (cumulative `duration_min` from `start_time`) | `step.scheduled_at` |
| Per-step actual start/end | `execution_data[id].started_at`, `.completed_at` | `step.actual_started_at`, `step.actual_completed_at` |
| Per-step reviewer | `execution_data[id].reviewed_by_user_id`, `.reviewed_at`, `umap`, `user_signatures` | `step.reviewer_initials` (swapped in `render_to_docx`) |
| Equipment summary | walk `graph.nodes[*].data.equipment[*]`; fetch Equipment rows | `equipment_summary: list[{local_id, name, description, serial_number}]` |
| Per-step equipment | `node.data.equipment[]` | `step.equipment: list[{local_id, name}]` |
| Revision history | query `ProtocolVersion` by protocol_id | `revision_history: list[{version, created_at, created_by, change_summary}]` |
| Protocol metadata pass-through | new fields from Migration A | `doc_number`, `effective_date`, `supersedes_date`, `purpose`, `scope`, `references`, `definitions` |
| Run metadata pass-through | new fields from Migration B | `lot_number`, `batch_number` |
| Responsibilities matrix | derived from `roles_with_steps` | `responsibilities: list[{role_name, step_summary}]` |
| Deviation list (template-side filter) | `notes` filtered by `"anomaly" in flags` | `deviations: list[same shape as notes]` |
| Approval stages (if Migration C lands) | re-shape `approval` / `approval_history` | `approvals: list[stage events]` |
| Reviewer-enabled flag | `any step with reviewed_by_user_id` | `reviewer_enabled: bool` (drives `{%tc if%}` on the reviewer column) |

### 2.4 — `KNOWN_VARIABLES` additions

Append to the set in `template_engine.py:25`:

```
time_enabled, start_time, reviewer_enabled,
equipment_summary,
revision_history, responsibilities, deviations,
doc_number, effective_date, supersedes_date,
purpose, scope, references, definitions,
lot_number, batch_number,
approvals (if Migration C)
```

`parse_template()` (line 55) already validates against this set; unrecognized variables in user-uploaded templates surface as warnings without further code change.

### 2.5 — `render_to_docx()` reviewer-signature swap

Mirror the existing `_swap()` helper for `step.initials` to also swap `step.reviewer_initials`:

```python
def _swap_reviewer(steps_list):
    for step in steps_list or []:
        uid = step.get("_reviewer_user_id")
        name = step.get("_reviewer_name", "")
        if not uid:
            continue
        step["reviewer_initials"] = _resolve_initials(
            user_id=uid, name=name,
            user_signatures=user_signatures, docx=doc,
        )
```

Called alongside `_swap()` for both `context["steps"]` and `role["steps"]`.

### 2.6 — Frontend: lot_number / batch_number inputs

`frontend/src/lib/components/run/` — extend the Run-start dialog with two optional text inputs (`Lot number`, `Batch number`). Reuses existing shadcn-svelte primitives (`Input`, `Label`). Wiring through `lib/api.ts` Run creation schema. Zod schema update under `lib/schemas/`.

### 2.7 — Execution order

1. Read `ProtocolApprovalEvent` / `ProtocolApprovalRequest` → decide on Migration C.
2. Migration A (Protocol + ProtocolVersion) + model + tests.
3. Migration B (Run) + model + tests.
4. Migration C (if needed) + model + tests.
5. `build_context()` additions (catalog order: time → equipment → revision → responsibilities → deviations → metadata pass-throughs → stages if applicable). Each lands with a unit test asserting the new context keys.
6. `KNOWN_VARIABLES` update + smoke test on `parse_template()`.
7. `render_to_docx` reviewer-signature swap + unit test.
8. Frontend lot/batch inputs + Vitest + Playwright e2e.

Approximate: 2–3 Alembic revisions, ~12 unit tests in phase 2.

### 2.8 — Frontend follow-up tickets (filed at task close)

- **F-XXXX**: Protocol metadata form section (doc_number, effective_date, supersedes_date, purpose, scope, references, definitions inputs on Protocol settings page).
- **F-XXXX**: Reviewer-signature button on completed steps in run UI.
- **F-XXXX (conditional)**: `Equipment.serial_number` field (only if absent today).

---

## Section 3 — Phase 3: Author the templates

Two new `.docx` files under `backend/app/services/documents/templates/`. Replace existing system defaults in `template_seeder.py`.

### 3.1 — SOP.docx layout

**Header (Word header, every page):**
- Left: `{{ organization_name }}` + `{{ doc_number }}` (if present)
- Right: `Version {{ version_number }}` + page X of Y (Word field)

**Title block (first page):**
```
{{ protocol_name }}
{% if doc_number %}Document #: {{ doc_number }}{% endif %}
Version {{ version_number }}  |  Effective: {{ effective_date }}  |  Supersedes: {{ supersedes_date }}
{{ project_name }}  |  {{ organization_name }}
```

**Sections** (each gated by `{% if %}`):
- Purpose, Scope, Definitions, References

**Revision history table** (gated by `{% if revision_history %}`):
```
| Version | Date | Author | Changes |
{% for rev in revision_history %} … {% endfor %}
```

**Responsibilities matrix** (gated by `{% if responsibilities %}`).

**Equipment summary table** (gated by `{% if equipment_summary %}`).

**Procedure** branches on `is_role_based`:
- `{% if is_role_based %}` → outer loop on `roles`, inner loop on `role.sop_steps`.
- `{% else %}` → flat loop on `steps`.
- Per step: `{{r step.sop_body }}` (RichText) + optional equipment cell `{%tc if step.equipment %}`.

**Approval block** (`{% if approval %}…{% else %}{{ unapproved_warning }}{% endif %}`).

### 3.2 — BatchRecord.docx layout

**Header (Word header):**
- Left: `{{ organization_name }}` + `{{ doc_number }}`
- Center: `Run: {{ run_name }}` + `{% if lot_number %}Lot: {{ lot_number }}{% endif %}`
- Right: page X of Y

**Title block (first page):**
```
{{ protocol_name }} — Batch Record
{% if lot_number %}Lot Number: {{ lot_number }}{% endif %}
{% if batch_number %}Batch Number: {{ batch_number }}{% endif %}
Run: {{ run_name }}  |  Status: {{ run_status }}
Started: {{ started_at }}  |  Completed: {{ completed_at }}
Project: {{ project_name }}  |  Organization: {{ organization_name }}
```

**SOP reference line:**
```
SOP Reference: {{ doc_number }} v{{ version_number }} (effective {{ effective_date }})
```

**Equipment used table** (BR-specific, with serial numbers).

**Procedure execution table** — the core. Conditional columns via `{%tc%}`:

```
| Step | Description | Param/Value | Operator
  | {%tc if reviewer_enabled %}Reviewer{%tc endif %}
  | {%tc if time_enabled %}Scheduled{%tc endif %}
  | {%tc if time_enabled %}Actual Start{%tc endif %}
  | {%tc if time_enabled %}Actual End{%tc endif %}
  | Date | Notes |

{% if is_role_based %}
  {% for role in roles %}
    {{r role.br_header }}
    {%tr for step in role.steps %}
      … row with matching {%tc if%} cells
    {%tr endfor %}
  {% endfor %}
{% else %}
  {%tr for step in steps %}
    … flat
  {%tr endfor %}
{% endif %}
```

`reviewer_enabled` is a context boolean (from Section 2.3): true if any step has `reviewed_by_user_id` populated. Avoids a dead Reviewer column on experiment runs.

**Deviations section** (`{% if deviations %}`).

**Run-level notes** (`{% if notes %}`, filters out anomaly-flagged since they're in deviations).

**Figures** (`{% if figures %}`) with `InlineImage` swap.

**Non-image attachments** (`{% if non_image_attachments %}`).

**Approval block** — multi-stage if Migration C, single otherwise, unapproved warning fallback:
```
{% if approvals %}
  {% for a in approvals %} … {% endfor %}
{% elif approval %}
  … single
{% else %}
  {{ unapproved_warning }}
{% endif %}
```

**Approval history** (`{% if approval_history and approval_history|length > 1 %}`).

**Release block** (`{% if release_statement %}`) — decision deferred to phase-3 author time.

### 3.3 — Authoring approach

Open the **current** `BatchRecord.docx` / `SOP.docx` system defaults; save-as; modify in place. Inherits existing Word styles. Style decisions are out of scope — structural correctness is the goal.

### 3.4 — Split-criterion check

BR procedure row has 5 **sibling** (not nested) `{%tc if%}` directives: reviewer + 3 time columns + per-step equipment. Above the soft threshold of >3 nested but well under the "unreadable in Word" threshold. Stay with one BR template. Re-evaluate if rendered template reads badly when opened in Word.

If we later split: BatchRecord.docx (no time columns) + BatchRecord_Timed.docx (with). Requires `DocumentTemplate.variant_key` column + resolver updates across preview / blank-download / completed-download. Out of scope for QA-0008.

### 3.5 — `template_seeder.py` update

`seed_system_templates()` repoints the system defaults at the new `.docx` paths. Existing rows updated in place (file_path swap); `is_system=True, is_default=True` flags preserved. Old templates removed from the seeder.

---

## Section 4 — Phase 4: Verification

Tests + rendered artifacts only. No DB seed CLI script. The templates are the deliverable; everything else is testing scaffolding.

### 4.1 — Directory layout

```
backend/tests/integration/test_qa0008_templates.py    # the tests
tests/fixtures/qa-0008/
├── gap-log.md          # narrative audit log
└── rendered/           # written by tests when --write-artifacts flag is on
    ├── P1_kitchen_sink/{sop,batch_record}.{docx,pdf}
    ├── P2_minimal/...
    ├── P3_role_no_time/...
    ├── P4_flat_with_time/...
    ├── P5_unapproved_deviations/...
    └── P6_multi_approval/...
```

### 4.2 — Permutation set

| # | Name | Role-based | time_enabled | Equipment | Approvals | Reviewer signing | Deviations | Edits | Lot | Renders against |
|---|---|---|---|---|---|---|---|---|---|---|
| P1 | Kitchen sink | ✅ (3 roles, 1 branch) | ✅ | ✅ | Approved + 2-event history | ✅ | ✅ (2) | ✅ (3 edits) | ✅ | SOP + BR |
| P2 | Minimal | ❌ | ❌ | ❌ | Unapproved | ❌ | ❌ | ❌ | ❌ | SOP + BR |
| P3 | Role-based, no time | ✅ | ❌ | ✅ | Approved | ❌ | ❌ | ❌ | ❌ | SOP + BR |
| P4 | Flat with time | ❌ | ✅ | ❌ | Approved | ❌ | ❌ | ❌ | ❌ | SOP + BR |
| P5 | Unapproved + deviations | ✅ | ✅ | ✅ | Unapproved | ✅ | ✅ (3) | ❌ | ❌ | BR only |
| P6 | Multi-event approval history | ✅ | ✅ | ✅ | submitted → rejected → re-approved (3 events) | ❌ | ❌ | ❌ | ✅ | BR only |

Each protocol has 4–8 unit ops. Cell-culture + harvest process flavor for realism.

### 4.3 — Coverage cross-check

| Catalog conditional | ON in | OFF in |
|---|---|---|
| `is_role_based` | P1, P3, P5, P6 | P2, P4 |
| `time_enabled` | P1, P4, P5, P6 | P2, P3 |
| `equipment_summary` | P1, P3, P5, P6 | P2, P4 |
| `approval` populated | P1, P3, P4, P6 | P2, P5 |
| `approval_history` len > 1 | P1, P6 | (others) |
| `reviewer_enabled` | P1, P5 | (others) |
| `deviations` non-empty | P1, P5 | (others) |
| `lot_number` populated | P1, P6 | (others) |
| Edits (strikethrough) | P1 | (others) |
| Per-step notes | P1, P5 | (others) |
| Figures | P1 | (others) |
| Non-image attachments | P1 | (others) |
| Run-level notes | P1, P5 | (others) |
| Multi-param vs single-param steps | mixed in P1 | — |
| Branched paths (parallel) | P1 | — |

Single-anchor items (only P1: figures, attachments, edits, parallel branch) acceptable — failure mode is "the conditional doesn't fire", easy to spot in P1's render. Add a P7 if a subtler feature-interaction surfaces during phase 3.

### 4.4 — Test pattern

```python
@pytest.fixture
def p1_context():
    return build_context(
        protocol_name="P1 — Kitchen Sink",
        is_role_based=True,
        roles_with_steps=[...],
        execution_data={...},
        # every field populated to fire every ON conditional
    )

def test_p1_br_renders_with_all_features(p1_context):
    ctx, unresolved = p1_context
    docx_bytes = render_to_docx(BR_TEMPLATE_PATH, ctx)
    text = docx_to_text(docx_bytes)

    assert unresolved == []
    assert "Reviewer" in text
    assert "Scheduled" in text
    assert "Lot Number:" in text
    assert "DEVIATION" in text

def test_p2_br_omits_optional_features(p2_context):
    ctx, _ = p2_context
    text = docx_to_text(render_to_docx(BR_TEMPLATE_PATH, ctx))
    assert "Reviewer" not in text
    assert "Scheduled" not in text
    assert "Lot Number:" not in text
```

P1 also gets an end-to-end test through `/protocols/{id}/pdf/batch-record` using a pytest DB fixture that inserts P1 as a real Protocol + Run. Proves the endpoint integration helpers (`_parse_graph_roles_and_steps`, `build_equipment_context`, `_build_user_signatures`, `_build_approval_context`) pass the new context fields through.

No pixel-level / byte-level snapshots — text-content assertions only. Survives Word XML reordering and LibreOffice version drift.

### 4.5 — Rendered artifacts

A `--write-artifacts` flag (or env var) tells the tests to **also write** the rendered `.docx` + `.pdf` to `tests/fixtures/qa-0008/rendered/`. Without the flag, tests just assert and exit fast. With it, you (or I) re-generate the side-by-side review set.

### 4.6 — Gap log

`tests/fixtures/qa-0008/gap-log.md` — narrative audit log, manually maintained. One section per gap I find during render-and-compare:

```markdown
## G7 — `time_enabled` column header rendered on P3 (role-based, time-disabled)
**Permutation**: P3
**Catalog row(s)**: #8, #34
**Symptom**: BR shows "Scheduled" column header but cells are empty.
**Root cause**: `{%tc if time_enabled %}` only on data cells, not header.
**Fix**: Wrap header cell in `{%tc if time_enabled %}` too.
**Files**: backend/app/services/documents/templates/BatchRecord.docx
**Test**: test_p3_br_omits_time_columns (asserts "Scheduled" not in text)
```

Survives the task as a reference for future template authors.

### 4.7 — Side-by-side review process

1. Run `pytest backend/tests/integration/test_qa0008_templates.py --write-artifacts` — clean re-render.
2. All 6 permutations land in `rendered/`.
3. Tests pass.
4. I walk each rendered PDF + the catalog visually; update `gap-log.md` for anything missed.
5. I show you the artifact set + the gap log + the catalog coverage matrix. You walk through, push back on rendering choices.
6. Signoff = done.

If you find gaps in step 5, they cycle through phase 2/3 (fix + new test + re-render) and we resume at step 5.

---

## Stop condition

Done when **all four** are true:

1. Catalog coverage matrix green: every catalog row exercised by ≥1 of P1–P6, both ON and OFF where conditional.
2. `pytest backend/tests/integration/test_qa0008_templates.py` green for all 6 permutations + P1 endpoint test.
3. `unresolved == []` for every permutation — no leaked `{{token}}` literals.
4. User signoff on side-by-side review.

No partial credit — all four must hold simultaneously at close.

---

## Risks

| # | Risk | Mitigation |
|---|---|---|
| R1 | `{%tc if%}` interaction with `render_to_docx`'s post-render InlineImage swap is undefined when the swapped placeholder lives inside a stripped cell. | Verify early in phase 3 with a small test. If broken, move swap logic into `build_context` (pre-render). |
| R2 | LibreOffice version drift produces different PDFs across dev machines. | Snapshot tests assert on `.docx` text content (via `python-docx`), not PDF bytes. PDFs are review artifacts only. |
| R3 | Migration C balloons (model + flow + backfill). | Read `ProtocolApprovalEvent` first. If model rework is bounded, do it; if not, surface multi-stage via `{% if approval_history|length > 1 %}` over single-event approval and file a follow-up. |
| R4 | `get_mock_context()` (template_engine.py:697) goes stale relative to the new surface. | Update it to use P1 as its data source. Part of phase-3 checklist. |
| R5 | JSONB shape additions (`started_at`, `reviewed_*`) added without endpoints to set them. | Test fixtures populate directly. Follow-up F-tickets cover endpoint writes. |
| R6 | Authoring `.docx` introduces style drift from existing system defaults. | Open existing defaults; save-as; modify in place. Style decisions out of scope. |
| R7 | Performance regression from many `{%tc if%}` per row. | Benchmark P1 render time vs current default; investigate if >50% slower. |
| R8 | Frontend follow-up tickets lag the templates; users see fields they can't populate via UI. | Templates use `{% if %}` gates so empty fields don't render. "Graceful absence", not "broken". |

---

## Open questions deferred to execution

1. Migration C necessity — resolved by reading `ProtocolApprovalEvent` at start of phase 2.
2. `release_statement` (B16) — separate field on Run vs piggyback on final approval. Decide at phase-3 author time.
3. `equipment_summary` serial numbers — does `Equipment.serial_number` exist? Surface if yes; follow-up ticket if no.
4. Frontend follow-up tickets filed at close: Protocol metadata form; reviewer-signature button; (conditional) Equipment.serial_number.

---

## Commit shape

Each commit is independently green (TDD discipline):

1. `feat(models): add Protocol GxP metadata fields + ProtocolVersion snapshot columns (QA-0008)`
2. `feat(models): add Run.lot_number / Run.batch_number (QA-0008)`
3. *(conditional)* `feat(models): add ProtocolApprovalEvent.stage (QA-0008)`
4. `feat(templates): extend build_context with time/equipment/revision/metadata surface (QA-0008)`
5. `feat(templates): add reviewer signature swap to render_to_docx (QA-0008)`
6. `feat(frontend): lot_number/batch_number inputs on run-start dialog (QA-0008)`
7. `feat(templates): production-grade SOP.docx system default (QA-0008)`
8. `feat(templates): production-grade BatchRecord.docx system default (QA-0008)`
9. `test(integration): qa-0008 template snapshot suite + permutation fixtures`
10. `docs(qa-0008): catalog coverage matrix + gap log`
11. `chore(seed): retire previous default templates, point seeder at new ones`

Follow-up F-tickets filed in ClickUp after step 11.
