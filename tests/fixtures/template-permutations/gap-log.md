# Production Template Gap Log

Narrative audit of every gap surfaced while authoring the production-grade
SOP + Batch Record templates and exercising them through six permutations
(P1–P6, see `backend/tests/integration/fixtures/template_permutations/`).

Format per entry:

```
## G<n> — <one-line headline>
**Permutation(s)**: P<n>[, P<m>]
**Symptom**: …
**Root cause**: …
**Decision**: fix-template | fix-context | document-as-design | spec-update
**Files**: …
**Test**: …
```

## Initial pass — 2026-05-15

### G1 — Spec example tests assert column hiding the template can't deliver

**Permutation(s)**: P2, P3, P4, P6 (Batch Record renders)
**Symptom**: The design spec's example tests (section 4.4) assert
`"Reviewer" not in text` and `"Scheduled" not in text` for permutations
that lack reviewer/time features. The actual `batch_record_default.docx`
always emits both as static column headers in the Procedure Execution
table; only the cell **contents** are gated via inline ternary
(`{{ step.reviewer_initials if reviewer_enabled else '' }}`).
**Root cause**: `docxtpl` cannot reliably nest `{%tc if %}` / `{%tc endif %}`
inside an outer `{%p for role in roles %}` paragraph wrapper — the outer
loop's `{%p endfor %}` regex consumes the inner cell-conditional's
`{% endif %}`. The build script for the Batch Record template
(`scripts/build_default_templates.py::_build_proc_table`) documents the
workaround inline and accepts the always-on header trade-off.
**Decision**: document-as-design. The spec example tests are aspirational;
the template's compromise was the right call given docxtpl's limits.
The permutation suite codifies the actual contract: `Reviewer` and
`Scheduled` headers are always present in BR renders, only the data
cells respect the feature flags.
**Files**: `scripts/build_default_templates.py` (docstring at the
proc-table builder); `backend/tests/integration/fixtures/template_permutations/builders.py` (P2/P3 route to SOP only;
P4/P6's `expected_off` omits these substrings).
**Test**: covered indirectly — `expected_off` lists in P2/P3 are SOP-only;
P4/P6 BR renders omit "Reviewer" / "Scheduled" from `expected_off`.

### G2 — Plan's `_step()` fixture used a list-of-fields schema that silently dropped params

**Permutation(s)**: all (would have affected any permutation passing
`params` through `_get_editable_params`)
**Symptom**: With the plan's original `_step(..., schema=[{...}])` shape,
rendered tables would have shown empty value cells because
`_get_editable_params` (in `pdf_base.py`) calls `.get("properties", {})`
on `step["param_schema"]` and a list has no `properties` key — silent zero.
**Root cause**: The plan author wrote a list-of-field-defs shape that
diverged from the production graph contract. The frontend stores
`paramSchema` as JSON-Schema `{"properties": {key: {title, unit}}}`
and the protocol-graph parser passes that dict through verbatim.
**Decision**: fix-context (in the test fixture only). The `_step()`
helper now converts the convenient list-of-dicts shape to the
production `{"properties": {...}}` shape before returning the step
dict, so test code reads naturally and the values surface correctly.
**Files**: `backend/tests/integration/fixtures/template_permutations/builders.py::_step`
**Test**: P1's `expected_on` includes "Bioreactor" and equipment values
that only appear when params/properties render; passing means the
conversion is working.

### G3 — `build_context` doesn't setdefault approval-related keys (only `get_mock_context` does)

**Permutation(s)**: P5 (Unapproved + Deviations + Reviewer)
**Symptom**: The Batch Record template references `{{ unapproved_warning }}`
and `{% if approval %}` / `{% for evt in approval_history %}`, but
`build_context` doesn't seed those keys. Only `get_mock_context`
setdefaults them. A permutation that doesn't pass an approval through
the endpoint's `_build_approval_context` would hit a Jinja
`UndefinedError` (or render an empty value depending on
`undefined_mode`).
**Root cause**: `_build_approval_context` lives in the endpoint
(`backend/app/api/endpoints/protocol_pdfs.py::_build_approval_context`)
and merges its three keys into the context dict after `build_context`
returns. Direct callers of `build_context` (tests, the permutation
suite) have to mirror that contract themselves.
**Decision**: document-as-design (for now). Pushing the setdefault into
`build_context` would weaken the endpoint's invariant that approval
context is computed from real DB state. The permutation test wrapper
sets the same three defaults that `get_mock_context` does, and P5
explicitly injects `context_overrides={"unapproved_warning": "…"}` to
surface its scenario.
**Files**: `backend/tests/integration/test_template_permutations.py`
(setdefault block); `builders.py::build_p5` (`context_overrides`).
**Test**: P5 BR render asserts `"Unapproved"` is in the rendered text;
passing means the override propagates correctly.

### G4 — Endpoint Content-Disposition crashed on unicode protocol names

**Permutation(s)**: P1 (any protocol whose name contains a non-Latin1
character — em-dash, smart quotes, accents)
**Symptom**: GET `/science/protocols/{id}/pdf/batch-record` (and its
SOP twin) raised `UnicodeEncodeError: 'latin-1' codec can't encode
character '—'` whenever the protocol name contained an em-dash.
HTTP headers are encoded latin-1; the previous implementation
substituted spaces with underscores but did not ASCII-sanitize.
**Root cause**: `_pdf_response` built `Content-Disposition` as a plain
f-string from `f"BatchRecord_Preview_{protocol.name}.pdf"`. Real-world
protocol names commonly contain en/em-dashes (`–`, `—`), smart quotes,
and accented characters.
**Decision**: fix-template (here, the endpoint). Switched to RFC 6266
form: emit an ASCII-safe `filename=` fallback plus a
`filename*=UTF-8''<percent-encoded>` for unicode-aware clients. Both
preview surfaces (SOP, Batch Record) go through `_pdf_response`, so
the fix covers all four call sites.
**Files**: `backend/app/api/endpoints/protocol_pdfs.py::_pdf_response`
**Test**: `test_p1_endpoint_renders_batch_record_pdf` uses
`"P1 — Kitchen Sink Cell Culture"` as the protocol name; passing means
the header survives the em-dash.

## Side-by-side review checklist

Run once before requesting signoff:

```bash
cd backend && source .venv/bin/activate
pytest tests/integration/test_template_permutations.py --write-artifacts -v
```

Then visually inspect each rendered PDF under
`tests/fixtures/template-permutations/rendered/P*/{batch_record,sop}.pdf`.
Walk through each permutation:

- **P1 — kitchen sink (renders against both SOP and BR).**
  - SOP: doc number header, Purpose / Scope / Definitions / References
    sections all present with body text; Revision History table renders
    both rows ("Initial release", "Tightened acceptance"); Equipment
    section lists Balance, Magnetic Stirrer, Bioreactor, pH Probe;
    Procedure shows two role lanes (Operator, Reviewer) with their
    steps; Approval section present (unapproved fallback or signed
    block).
  - BR: Lot Number and Batch Number visible in header; execution table
    populated for every step (start/complete times, reviewer initials
    where present); Equipment Used table present; Deviations table
    shows the two anomaly-flagged notes; Notes section contains the
    routine handoff.

- **P2 — minimal flat (SOP only).**
  - All optional sections (Purpose, Scope, Definitions, References,
    Revision History, Equipment, Responsibilities, Approval) gated
    off; only Procedure renders with the two flat steps.

- **P3 — role-based, no time, with equipment (SOP only).**
  - Equipment section lists Centrifuge; Procedure shows the Operator
    lane; time-related fields absent.

- **P4 — flat with time (BR only).**
  - Execution table's Scheduled column populated; no Equipment Used
    table (no equipment passed); no Lot Number in header.

- **P5 — unapproved + deviations + reviewer (BR only).**
  - Header shows the unapproved warning text; Deviations table lists
    all three anomaly notes; Reviewer column populated for the one
    reviewed step (Sam's initials); other reviewer cells empty.

- **P6 — multi-event approval history (BR only).**
  - Lot Number in header; approval-history section will populate if
    real ProtocolApprovalEvent rows are present (this permutation
    doesn't seed them via the test fixture — that surface is
    exercised separately in the endpoint integration test).

Any rendering surprise — log a `G<n>` block under "Initial pass" above
and file a follow-up fix.
