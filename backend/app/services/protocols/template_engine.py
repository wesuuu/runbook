"""Document template engine — renders .docx templates to PDF.

Pipeline: docxtpl fills .docx → LibreOffice headless converts to PDF.
"""

import subprocess
import tempfile
from datetime import datetime
from io import BytesIO
from pathlib import Path
from typing import Any

from docx.shared import Mm
from docxtpl import DocxTemplate, InlineImage, RichText

# SOP typography (raw half-points; see "Pt()" footnote below the RichText
# helpers in this file). Body 11pt, meta 10pt, role header 14pt.
_BODY_HP = 22
_META_HP = 20
_ROLE_HP = 28
_INK = "#1F2937"
_INK_DEEP = "#0F172A"
_INK_MUTED = "#64748B"
_SERIF = "Cambria"
_SANS = "Calibri"


def _build_sop_body(
    step_number: int,
    name: str,
    desc: str,
    param_sentence: str,
    duration_min: int | None,
) -> RichText:
    """Compose a SOP procedure step as a single paragraph with soft
    line breaks. Hanging indent + tab stop on the template paragraph
    aligns the number column; wrapped lines hang under the step text.

    Layout:
        N.<TAB><bold step name>
                <description>
                <param sentence>
                Allow N minutes for this step.
    """
    rt = RichText()
    # Number column — sans, distinct from prose
    rt.add(
        f"{step_number}.\t",
        bold=True,
        size=_BODY_HP,
        color=_INK_DEEP,
        font=_SANS,
    )
    if name:
        rt.add(name, bold=True, size=_BODY_HP, color=_INK_DEEP, font=_SERIF)
    if desc:
        rt.add("\n")
        rt.add(desc, size=_BODY_HP, color=_INK, font=_SERIF)
    if param_sentence:
        rt.add("\n")
        rt.add(
            param_sentence,
            italic=True,
            size=_META_HP,
            color=_INK_MUTED,
            font=_SERIF,
        )
    if duration_min:
        rt.add("\n")
        rt.add(
            f"Allow {duration_min} minutes for this step.",
            italic=True,
            size=_META_HP,
            color=_INK_MUTED,
            font=_SERIF,
        )
    return rt


def _build_br_card_header(
    step_number: int,
    name: str,
    duration_min: int | None,
) -> RichText:
    """Compose a Batch Record step-card header as a single paragraph.

    Layout (two tab stops: 0.4in left, ~5.8in right):
        NN.<TAB><bold step name><TAB><italic muted duration>

    The number column is sans for distinction from the serif body; the
    name is bold serif; the duration sits on a right-tab in muted sans
    italic so it reads as metadata, not as part of the step name.
    """
    rt = RichText()
    rt.add(
        f"{step_number:02d}.\t",
        bold=True,
        size=_BODY_HP,
        color=_INK_DEEP,
        font=_SANS,
    )
    rt.add(
        name or "Step",
        bold=True,
        size=_BODY_HP,
        color=_INK_DEEP,
        font=_SERIF,
    )
    if duration_min:
        rt.add(
            f"\t{duration_min} min",
            italic=True,
            size=_META_HP,
            color=_INK_MUTED,
            font=_SANS,
        )
    return rt


from app.services.core.file_storage import IMAGE_MIME_TYPES, FileStorageService
from app.services.documents.pdf_base import (_build_param_sentence,
                                             _format_value,
                                             _get_editable_params,
                                             _get_initials, _get_param_title,
                                             _render_template)

# ── Known template variables (for upload validation) ──

KNOWN_VARIABLES = {
    # Protocol
    "protocol_name",
    "protocol_description",
    "version_number",
    "created_at",
    # Run
    "run_name",
    "run_status",
    "started_at",
    "completed_at",
    # Project / Org
    "project_name",
    "organization_name",
    # Layout
    "is_role_based",
    "page_break",
    # Loops (top-level)
    "roles",
    "steps",
    "notes",
    "figures",
    "non_image_attachments",
    # Manual/optional loops — populated only when data is wired
    "materials",
    "equipment",
    "target_yield",
    # SOP-specific fields (time-course bioreactor SOP template)
    "document_number",
    "effective_date",
    "purpose_text",
    "scope_text",
    "critical_requirement",
    "is_time_based",
    "time_points",
    # Approval (F-0066)
    "approval",
    "approval_history",
    "unapproved_warning",
    # Time axis
    "time_enabled",
    "start_time",
    # Reviewer
    "reviewer_enabled",
    # Equipment / revisions / responsibilities / deviations
    "equipment_summary",
    "revision_history",
    "responsibilities",
    "deviations",
    # Document metadata
    "doc_number",
    "effective_date",
    "supersedes_date",
    # SOP sections
    "purpose",
    "scope",
    "references",
    "definitions",
    # Run identifiers
    "produces_lot",      # F-0086
    "lot_number",
    "batch_number",
    # SOP time-course mode (bioreactor-style sampling SOPs)
    "critical_requirement",
    "is_time_based",
    "time_points",
    # Batch record GxP loops
    "target_yield",
    "materials",
    "equipment",
}


def parse_template(file_path: str | Path) -> tuple[list[str], list[str]]:
    """Extract Jinja2 variable names from a .docx template.

    Returns:
        (recognized, unrecognized) — two sorted lists of variable names.
    """
    doc = DocxTemplate(str(file_path))
    variables = doc.get_undeclared_template_variables()

    recognized = []
    unrecognized = []
    for var in sorted(variables):
        top_level = var.split(".")[0]
        if var in KNOWN_VARIABLES or top_level in KNOWN_VARIABLES:
            recognized.append(var)
        else:
            unrecognized.append(var)

    return recognized, unrecognized


def _resolve_initials(
    *,
    user_id: str,
    name: str,
    user_signatures: dict,
    docx: DocxTemplate,
):
    """Return an InlineImage of the user's drawn initials if registered,
    else the auto-generated text initials. The template uses
    `{{ step.initials }}` (plain), which renders InlineImage objects
    natively but cannot render RichText — so the fallback is a plain
    string, matching pre-F-0080 behavior.

    Accepts both the legacy ``{user_id: path_str}`` shape and the
    F-0066 ``{user_id: {"signature_initials_path": path,
    "signature_full_path": path}}`` shape."""
    entry = user_signatures.get(user_id)
    if isinstance(entry, dict):
        path = entry.get("signature_initials_path")
    else:
        path = entry
    if path and Path(path).exists():
        return InlineImage(docx, path, width=Mm(20))
    return _get_initials(name)


def _compute_scheduled_at(start_time: str, prior_minutes: int) -> str:
    """Add ``prior_minutes`` to an ``HH:MM`` start time, returning ``HH:MM``."""
    if not start_time:
        return ""
    try:
        hh, mm = start_time.split(":")
        total = int(hh) * 60 + int(mm) + max(0, int(prior_minutes))
    except (ValueError, AttributeError):
        return ""
    return f"{(total // 60) % 24:02d}:{total % 60:02d}"


def _apply_step_reviewer(
    step_ctx: dict[str, Any],
    *,
    step_id: str,
    execution_data: dict[str, Any],
    user_map: dict[str, str],
) -> None:
    """Mutate ``step_ctx`` with reviewer fields from execution data.

    Populates ``reviewer_initials`` (up to 3 uppercase initials derived
    from the reviewer's display name), ``reviewed_at`` (ISO timestamp),
    and the underscore-prefixed ``_reviewer_user_id`` /
    ``_reviewer_name`` audit fields. All fields default to empty
    strings when the step has not been reviewed.

    Callers responsible for any aliasing must shallow-copy the dict
    before passing it in.
    """
    exec_row = execution_data.get(step_id, {})
    reviewer_uid = exec_row.get("reviewed_by_user_id", "")
    reviewer_name = user_map.get(reviewer_uid, "") if reviewer_uid else ""
    step_ctx["_reviewer_user_id"] = reviewer_uid
    step_ctx["_reviewer_name"] = reviewer_name
    step_ctx["reviewed_at"] = exec_row.get("reviewed_at", "")
    if reviewer_uid and reviewer_name:
        step_ctx["reviewer_initials"] = "".join(
            p[0].upper() for p in reviewer_name.split() if p
        )[:3]
    else:
        step_ctx["reviewer_initials"] = ""


def _apply_step_timing(
    step_ctx: dict[str, Any],
    *,
    start_time: str,
    prior_minutes: int,
    execution_data: dict[str, Any],
) -> int:
    """Mutate ``step_ctx`` in place with scheduled/actual timestamps.

    Sets ``scheduled_at`` (derived from ``start_time`` + ``prior_minutes``)
    and ``actual_started_at`` / ``actual_completed_at`` (looked up by the
    step's ``id`` in ``execution_data``). Returns the new cumulative
    minutes including this step's duration so callers can advance their
    timeline counter.

    Callers responsible for any aliasing must shallow-copy the dict
    before passing it in.
    """
    step_ctx["scheduled_at"] = _compute_scheduled_at(start_time, prior_minutes)
    step_id = step_ctx.get("_step_id") or step_ctx.get("id", "")
    exec_row = execution_data.get(step_id, {})
    step_ctx["actual_started_at"] = exec_row.get("started_at", "")
    step_ctx["actual_completed_at"] = exec_row.get("completed_at", "")
    return prior_minutes + int(step_ctx.get("duration_min") or 0)


def build_context(
    *,
    protocol_name: str = "",
    protocol_description: str = "",
    version_number: int | None = None,
    created_at: str = "",
    run_name: str | None = None,
    run_status: str | None = None,
    started_at: str | None = None,
    completed_at: str | None = None,
    project_name: str = "",
    organization_name: str = "",
    roles_with_steps: list[dict[str, Any]] | None = None,
    flat_steps: list[dict[str, Any]] | None = None,
    is_role_based: bool = True,
    execution_data: dict[str, Any] | None = None,
    user_map: dict[str, str] | None = None,
    user_signatures: dict[str, dict[str, str]] | None = None,
    started_by_id: str | None = None,
    notes: list[dict[str, Any]] | None = None,
    attachments: list[dict[str, Any]] | None = None,
    storage: FileStorageService | None = None,
    equipment_context: dict[str, str] | None = None,
    time_enabled: bool = False,
    start_time: str = "",
    doc_number: str = "",
    effective_date: str = "",
    supersedes_date: str = "",
    purpose: str = "",
    scope: str = "",
    references: str = "",
    definitions: str = "",
    lot_number: str = "",
    batch_number: str = "",
    produces_lot: bool = False,
    revision_history: list[dict[str, Any]] | None = None,
    critical_requirement: str = "",
    is_time_based: bool = False,
    time_points: list[dict[str, Any]] | None = None,
    target_yield: str = "",
    materials: list[dict[str, Any]] | None = None,
    equipment: list[dict[str, Any]] | None = None,
) -> tuple[dict[str, Any], list[str]]:
    """Assemble the Jinja2 context dict for template rendering.

    Returns ``(context, unresolved)`` where ``unresolved`` is the
    deduplicated, ordered list of ``{{token}}`` names that could not be
    resolved across all step renders. Pass ``equipment_context`` to make
    ``{{<local_id>_name}}`` / ``{{<local_id>_description}}`` resolvable;
    per-step params still win on key collision.
    """
    exec_data = execution_data or {}
    umap = user_map or {}
    sigmap = user_signatures or {}
    eq_ctx = equipment_context or {}
    unresolved_all: list[str] = []
    _seen_unresolved: set[str] = set()

    # Aggregate equipment referenced by individual steps into an ordered-
    # unique summary list keyed by ``local_id``. Per-step entries always
    # carry the lookup key + display name; the summary preserves the
    # first description encountered.
    _equipment_index: dict[str, dict[str, Any]] = {}

    def _collect_equipment(
        node_equipment: list[dict[str, Any]] | None,
    ) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for entry in node_equipment or []:
            local_id = entry.get("local_id") or ""
            if not local_id:
                continue
            if local_id not in _equipment_index:
                _equipment_index[local_id] = {
                    "local_id": local_id,
                    "name": entry.get("name", ""),
                    "description": entry.get("description", ""),
                }
            out.append({"local_id": local_id, "name": entry.get("name", "")})
        return out

    def _merge_and_render(desc: str, params: dict[str, Any] | None) -> str:
        merged = {**eq_ctx, **(params or {})}
        rendered, unresolved = _render_template(desc, merged)
        for tok in unresolved:
            if tok not in _seen_unresolved:
                _seen_unresolved.add(tok)
                unresolved_all.append(tok)
        return rendered

    # Pre-compute figure map: step_id → [figure_number, ...]
    active_atts = [a for a in (attachments or []) if not a.get("deleted")]
    figure_map: dict[str, list[int]] = {}
    fig_counter = 0
    for att in active_atts:
        if att.get("content_type", "") in IMAGE_MIME_TYPES:
            fig_counter += 1
            sid = att.get("step_id")
            if sid:
                figure_map.setdefault(sid, []).append(fig_counter)

    # Build step contexts for the flat step list (batch record table
    # and flat-mode SOP procedure)
    step_contexts = []
    _cumulative_min = 0
    for _flat_idx, step in enumerate(flat_steps or [], start=1):
        step_id = step.get("id", "")
        sd = exec_data.get(step_id, {})
        results = sd.get("results", {})
        completed_by_uid = sd.get("completed_by_user_id", "")
        edited_by_uid = sd.get("edited_by_user_id", "")
        original_results = sd.get("original_results")

        # Build description with template substitution
        desc = step.get("description", "") or ""
        params = step.get("params") or {}
        param_schema = step.get("param_schema") or {}
        has_templates = desc and "{{" in desc
        if has_templates:
            desc = _merge_and_render(desc, params)

        # Build param sentence if no inline templates
        param_sentence = ""
        if not has_templates:
            param_sentence = _build_param_sentence(params, param_schema)

        full_desc = desc
        if not has_templates and param_sentence:
            full_desc = f"{desc} {param_sentence}" if desc else param_sentence
        if not full_desc:
            full_desc = "--"

        # Editable params for multi-param display
        editable = _get_editable_params(param_schema)
        param_details = []
        for key, prop in editable:
            label = prop.get("title") or key.replace("_", " ").title()
            unit = prop.get("unit", "")
            if unit:
                label = f"{label} ({unit})"

            current_val = results.get(key)
            display_val = (
                _format_value(current_val)
                if current_val is not None and current_val != ""
                else ""
            )

            # GMP edit tracking
            orig_val = ""
            editor = ""
            edited_at = ""
            is_edited = False
            if original_results and key in original_results:
                orig = original_results.get(key)
                if orig != results.get(key):
                    is_edited = True
                    orig_val = _format_value(orig)
                    editor = _get_initials(umap.get(edited_by_uid, ""))
                    raw_edited_at = sd.get("edited_at", "")
                    if raw_edited_at:
                        try:
                            dt = datetime.fromisoformat(
                                raw_edited_at.replace("Z", "+00:00")
                            )
                            edited_at = dt.strftime("%m/%d/%y")
                        except (ValueError, AttributeError):
                            edited_at = raw_edited_at[:10]

            param_details.append(
                {
                    "label": label,
                    "value": display_val,
                    "is_edited": is_edited,
                    "original_value": orig_val,
                    "editor": editor,
                    "edited_at": edited_at,
                }
            )

        # Initials for completer
        completer_uid = completed_by_uid or (
            started_by_id if not completed_by_uid else ""
        )
        completer_name = umap.get(completer_uid, "")
        # Store both the resolved name and the user_id so render_to_docx
        # can swap in an InlineImage of the user's drawn signature
        # against the open DocxTemplate (mirrors the figure-handling
        # pattern). Falls back to text initials when none registered.
        if completer_name and sd.get("status") == "completed":
            initials_user_id = completer_uid
            initials_text_fallback = _get_initials(completer_name)
        else:
            initials_user_id = ""
            initials_text_fallback = ""
        initials = initials_text_fallback  # plain-text placeholder for now

        # Single value display (for single-param steps)
        single_value = ""
        if len(editable) == 1 and results:
            key = editable[0][0]
            val = results.get(key)
            if val is not None and val != "":
                single_value = _format_value(val)

        # Pre-computed value display as RichText (supports strikethrough
        # for GMP edits). Use {{r step.value_display}} in template.
        # Font size matches the template cell's 8pt.
        # docxtpl RichText.add(size=…) expects raw half-points
        # (Word's w:sz), not EMU. Pt() returns EMU and silently
        # produces ~half-point*6350× sizes when passed through.
        # Editorial pairing: Calibri sans label + Cambria serif value,
        # deep ink for label, body ink for value, muted ink for edit
        # annotations. 10pt body inside the step card.
        VS = 20  # 10pt
        rt = RichText()
        if len(editable) > 1:
            for idx, pd in enumerate(param_details):
                if idx > 0:
                    rt.add("\a")  # new paragraph between params
                rt.add(
                    f"{pd['label']}  ",
                    bold=True,
                    size=VS,
                    color=_INK_DEEP,
                    font=_SANS,
                )
                if pd["is_edited"]:
                    rt.add(
                        pd["original_value"],
                        strike=True,
                        size=VS,
                        color=_INK_MUTED,
                        font=_SERIF,
                    )
                    annotation = ""
                    if pd["editor"] or pd["edited_at"]:
                        parts = [p for p in (pd["editor"], pd["edited_at"]) if p]
                        annotation = " " + " ".join(parts)
                    rt.add(
                        f"{annotation} \u2192 ",
                        size=VS,
                        color=_INK_MUTED,
                        font=_SERIF,
                    )
                rt.add(pd["value"], size=VS, color=_INK, font=_SERIF)
        elif single_value:
            rt.add(single_value, size=VS, color=_INK, font=_SERIF)
        value_display = rt

        # Per-step notes text (from execution_data)
        step_notes_text = sd.get("notes", "") if exec_data else ""

        # Figure cross-references for this step
        step_fig_nums = figure_map.get(step_id, [])
        figure_refs = ""
        if step_fig_nums and exec_data:
            fig_str = ", ".join(f"Figure {n}" for n in step_fig_nums)
            figure_refs = f"See {fig_str}"

        # Combined notes display: "Notes: <text> <figure refs>"
        notes_display = ""
        if step_notes_text or figure_refs:
            parts = []
            if step_notes_text:
                parts.append(step_notes_text)
            if figure_refs:
                parts.append(figure_refs)
            notes_display = "  ".join(parts)

        # sop_body is consumed by the flat-mode SOP procedure section.
        # Role-based SOP uses the per-role sop_steps built below; this
        # one is for the {%p else %} branch of the procedure template.
        flat_sop_body = _build_sop_body(
            step_number=_flat_idx,
            name=step.get("name", ""),
            desc=desc,
            param_sentence=param_sentence,
            duration_min=step.get("duration_min"),
        )

        # Batch-record step-card header — defaults to the flat numbering.
        # The role-based branch overwrites this with per-role numbering
        # in the role loop below.
        card_header = _build_br_card_header(
            step_number=_flat_idx,
            name=step.get("name", ""),
            duration_min=step.get("duration_min"),
        )

        step_ctx = {
            "_step_id": step_id,
            "name": step.get("name", ""),
            "description": full_desc,
            "duration_min": step.get("duration_min"),
            "role_name": step.get("role_name", ""),
            "params": params,
            "equipment": _collect_equipment(step.get("equipment")),
            "param_details": param_details,
            "has_multi_params": len(editable) > 1,
            "single_value": single_value,
            "value_display": value_display,
            "initials": initials,
            "_initials_user_id": initials_user_id,
            "_initials_name": completer_name,
            "status": sd.get("status", ""),
            "notes_text": step_notes_text,
            "figure_refs": figure_refs,
            "notes_display": notes_display,
            "sop_body": flat_sop_body,
            "card_header": card_header,
        }
        # Per-step scheduling on the global timeline.
        _cumulative_min = _apply_step_timing(
            step_ctx,
            start_time=start_time,
            prior_minutes=_cumulative_min,
            execution_data=exec_data,
        )
        _apply_step_reviewer(
            step_ctx,
            step_id=step_id,
            execution_data=exec_data,
            user_map=umap,
        )
        step_contexts.append(step_ctx)

    # Build role contexts — each role contains both SOP-style steps
    # (description + param_sentence + duration for SOP template) and
    # batch-record-style steps (full step_ctx for batch record template).
    # Index step_contexts by step ID for lookup.
    step_ctx_by_id = {sc.get("_step_id", ""): sc for sc in step_contexts}

    role_contexts = []
    for role_data in roles_with_steps or []:
        sop_steps = []
        br_steps = []
        # Per-role timeline restarts at start_time.
        _cumulative_min = 0
        for step_idx, s in enumerate(role_data.get("steps", []), start=1):
            # SOP-style step
            desc = s.get("description", "") or ""
            params = s.get("params") or {}
            param_schema = s.get("param_schema") or {}
            has_templates = desc and "{{" in desc
            if has_templates:
                desc = _merge_and_render(desc, params)
            param_sentence = ""
            if not has_templates:
                param_sentence = _build_param_sentence(params, param_schema)

            sop_body = _build_sop_body(
                step_number=step_idx,
                name=s.get("name", ""),
                desc=desc,
                param_sentence=param_sentence,
                duration_min=s.get("duration_min"),
            )

            sop_steps.append(
                {
                    "name": s.get("name", ""),
                    "sop_body": sop_body,
                }
            )

            # Batch-record-style step (reuse from step_contexts if available).
            # Shallow-copy so the per-role timeline doesn't mutate the shared
            # step_ctx dict already appended to the global step_contexts list.
            step_id = s.get("id", "")
            shared = step_ctx_by_id.get(step_id)
            if shared:
                br_step = dict(shared)
            else:
                # Fallback: build a minimal step context from role step data
                br_step = {
                    "_step_id": step_id,
                    "name": s.get("name", ""),
                    "description": desc or param_sentence or "--",
                    "duration_min": s.get("duration_min"),
                    "role_name": role_data.get("role_name", ""),
                    "equipment": _collect_equipment(s.get("equipment")),
                    "value_display": "",
                    "initials": "",
                    "_initials_user_id": "",
                    "_initials_name": "",
                    "notes_display": "",
                    "card_header": RichText(),
                }
            # Per-step scheduling on the per-role timeline.
            _cumulative_min = _apply_step_timing(
                br_step,
                start_time=start_time,
                prior_minutes=_cumulative_min,
                execution_data=exec_data,
            )
            _apply_step_reviewer(
                br_step,
                step_id=step_id,
                execution_data=exec_data,
                user_map=umap,
            )
            # Per-role step numbering for the BR card header (replaces
            # the global flat-mode card_header inherited from step_ctx).
            br_step["card_header"] = _build_br_card_header(
                step_number=step_idx,
                name=s.get("name", ""),
                duration_min=s.get("duration_min"),
            )
            br_steps.append(br_step)

        # Pre-compute role header as RichText to avoid empty
        # conditional paragraphs that create whitespace gaps in Word
        role_name = role_data.get("role_name", "")
        process_name = role_data.get("process_name", "")
        process_desc = role_data.get("process_description", "")
        header_name = process_name or role_name

        # Role header \u2014 a single paragraph the template paragraph wraps
        # with a bottom border, so we don't draw a Unicode rule inline.
        # process_desc (if any) sits on a soft line break in the same
        # paragraph, italicized and muted; \f forces a page break before
        # non-first roles so each role's procedure starts on its own page.
        sop_header = RichText()
        is_first_role = len(role_contexts) == 0
        if not is_first_role:
            sop_header.add("\f")
        if header_name:
            sop_header.add(
                header_name,
                bold=True,
                size=_ROLE_HP,
                color=_INK_DEEP,
                font=_SANS,
            )
            if process_desc:
                sop_header.add("\n")
                sop_header.add(
                    process_desc,
                    italic=True,
                    size=_META_HP,
                    color=_INK_MUTED,
                    font=_SERIF,
                )

        # Pre-compute batch record header (page break + uppercase role
        # name in Calibri). The template paragraph adds the bottom rule
        # and keep_with_next semantics.
        br_header = RichText()
        if not is_first_role:
            br_header.add("\f")  # page break before non-first roles
        if header_name:
            br_header.add(
                header_name.upper(),
                bold=True,
                size=_ROLE_HP,
                color=_INK_DEEP,
                font=_SANS,
            )

        role_contexts.append(
            {
                "name": role_name,
                "process_name": process_name,
                "process_description": process_desc,
                "sop_header": sop_header,
                "br_header": br_header,
                "sop_steps": sop_steps,
                "steps": br_steps,  # used by batch record template
            }
        )

    # Build notes contexts
    note_contexts = []
    for note in notes or []:
        created = note.get("created_at", "")
        ts = created[:19].replace("T", " ") if created else ""
        flags = note.get("flags", [])
        flag_prefix = "[ANOMALY] " if "anomaly" in flags else ""
        meta_parts = [note.get("author_name", "Unknown"), ts]
        run_status = note.get("run_status", "")
        if run_status:
            meta_parts.append(run_status)
        note_contexts.append(
            {
                "author_name": note.get("author_name", "Unknown"),
                "created_at": ts,
                "meta": "  |  ".join(meta_parts),
                "content": f"{flag_prefix}{note.get('content', '')}",
                "run_status": run_status,
            }
        )

    # Build figure contexts (image attachments)
    figure_contexts = []
    non_image_att_contexts = []

    # Step name lookup
    step_name_map = {s.get("id", ""): s.get("name", "") for s in flat_steps or []}

    fig_num = 0
    for att in active_atts:
        sid = att.get("step_id")
        scope = step_name_map.get(sid, sid) if sid else "Run-level"
        uploaded_at = att.get("uploaded_at", "")
        ts = uploaded_at[:16].replace("T", " ") if uploaded_at else ""

        if att.get("content_type", "") in IMAGE_MIME_TYPES:
            fig_num += 1
            fig_ctx: dict[str, Any] = {
                "number": fig_num,
                "filename": att.get("filename", ""),
                "step_name": scope,
                "uploaded_at": ts,
                "_file_path": att.get("file_path", ""),
            }
            figure_contexts.append(fig_ctx)
        else:
            ctype = att.get("content_type", "").split("/")[-1]
            non_image_att_contexts.append(
                {
                    "filename": att.get("filename", "Unknown"),
                    "type": ctype,
                    "scope": scope,
                    "uploaded_at": ts,
                }
            )

    # Pre-compute protocol subtitle (run name + description) as RichText
    # to avoid empty conditional paragraphs
    protocol_subtitle = RichText()
    if run_name:
        protocol_subtitle.add(
            f"Run: {run_name}", bold=True, size=20, color="#334155"
        )
    if protocol_description:
        if run_name:
            protocol_subtitle.add("\a")
        protocol_subtitle.add(protocol_description, size=20, color="#64748B")

    context: dict[str, Any] = {
        "protocol_name": protocol_name,
        "protocol_subtitle": protocol_subtitle,
        "protocol_description": protocol_description,
        "version_number": version_number,
        "created_at": created_at,
        "run_name": run_name or "",
        "run_status": run_status or "",
        "started_at": started_at or "",
        "completed_at": completed_at or "",
        "project_name": project_name,
        "organization_name": organization_name,
        "is_role_based": is_role_based,
        "time_enabled": bool(time_enabled),
        "start_time": start_time or "",
        "page_break": RichText("\f"),
        "steps": step_contexts,
        "roles": role_contexts,
        "equipment_summary": list(_equipment_index.values()),
        "notes": note_contexts,
        "figures": figure_contexts,
        "non_image_attachments": non_image_att_contexts,
        "_user_signatures": sigmap,
    }

    for _k in (
        "doc_number",
        "effective_date",
        "supersedes_date",
        "purpose",
        "scope",
        "references",
        "definitions",
        "lot_number",
        "batch_number",
    ):
        context[_k] = locals()[_k] or ""

    # F-0086: explicit boolean — the batch-record template uses {%tr if produces_lot %}.
    context["produces_lot"] = bool(produces_lot)

    # Responsibilities matrix (role-based only)
    if is_role_based:
        context["responsibilities"] = [
            {
                "role_name": role.get("role_name", ""),
                "step_summary": "; ".join(
                    s.get("name", "") for s in role.get("steps", []) if s.get("name")
                ),
            }
            for role in (roles_with_steps or [])
        ]
    else:
        context["responsibilities"] = []

    context["revision_history"] = list(revision_history or [])
    context["critical_requirement"] = critical_requirement or ""
    context["is_time_based"] = bool(is_time_based)
    context["time_points"] = list(time_points or [])
    context["target_yield"] = target_yield or ""
    context["materials"] = list(materials or [])
    context["equipment"] = list(equipment or [])

    # Deviations: subset of notes where flags include "anomaly"
    context["deviations"] = [
        n for n in (notes or []) if "anomaly" in (n.get("flags") or [])
    ]

    # reviewer_enabled: True if any step has reviewed_by_user_id in execution_data
    _exec = execution_data or {}
    context["reviewer_enabled"] = any(
        bool((_exec.get(sid) or {}).get("reviewed_by_user_id")) for sid in _exec
    )

    return context, unresolved_all


def render_to_docx(
    template_path: str | Path,
    context: dict[str, Any],
) -> bytes:
    """Render a .docx template with context, return .docx bytes."""
    doc = DocxTemplate(str(template_path))

    # Convert figure file paths to InlineImage objects. We .get() rather
    # than .pop() the path so render_to_pdf can call us twice — popping
    # would leave the second pass with stale InlineImage refs pointing at
    # the previous DocxTemplate, which Word silently renders as invisible.
    for fig in context.get("figures", []):
        fpath_str = fig.get("_file_path")
        if fpath_str:
            fpath = Path(fpath_str)
            if fpath.exists():
                fig["image"] = InlineImage(doc, str(fpath), width=Mm(150))
            else:
                fig["image"] = f"[Image not found: {fpath.name}]"
        elif "image" not in fig:
            fig["image"] = ""

    # Same handling for per-time-point figures (SOP time-course mode).
    for tp in context.get("time_points", []) or []:
        fig = tp.get("figure")
        if not isinstance(fig, dict):
            continue
        fpath_str = fig.get("_file_path")
        if fpath_str:
            fpath = Path(fpath_str)
            if fpath.exists():
                fig["image"] = InlineImage(doc, str(fpath), width=Mm(120))
            else:
                fig["image"] = f"[Image not found: {fpath.name}]"
        elif "image" not in fig:
            fig["image"] = ""

    # Same handling for per-time-point figures in SOP time-course mode.
    for tp in context.get("time_points", []) or []:
        fig = tp.get("figure")
        if not isinstance(fig, dict):
            continue
        fpath_str = fig.get("_file_path")
        if fpath_str:
            fpath = Path(fpath_str)
            if fpath.exists():
                fig["image"] = InlineImage(doc, str(fpath), width=Mm(120))
            else:
                fig["image"] = f"[Image not found: {fpath.name}]"
        elif "image" not in fig:
            fig["image"] = ""

    # F-0080 — swap step.initials to an InlineImage of the user's drawn
    # signature, or a cursive RichText fallback. Mirrors the figure
    # handling above: build_context puts placeholders, render_to_docx
    # finalizes them against the open DocxTemplate.
    user_signatures = context.get("_user_signatures") or {}

    def _swap(steps_list):
        for step in steps_list or []:
            uid = step.get("_initials_user_id")
            name = step.get("_initials_name", "")
            if not uid:
                continue
            step["initials"] = _resolve_initials(
                user_id=uid,
                name=name,
                user_signatures=user_signatures,
                docx=doc,
            )

    def _swap_reviewer(steps_list):
        for step in steps_list or []:
            uid = step.get("_reviewer_user_id")
            name = step.get("_reviewer_name", "")
            if not uid:
                continue
            step["reviewer_initials"] = _resolve_initials(
                user_id=uid,
                name=name,
                user_signatures=user_signatures,
                docx=doc,
            )

    _swap(context.get("steps"))
    _swap_reviewer(context.get("steps"))
    for role in context.get("roles", []) or []:
        _swap(role.get("steps"))
        _swap(role.get("br_steps"))
        _swap_reviewer(role.get("steps"))
        _swap_reviewer(role.get("br_steps"))

    # F-0066 — swap approval.signature_image_path to an InlineImage so
    # the template can render `{{ approval.signature_image }}`. Mirrors
    # the figure handling above.
    approval = context.get("approval")
    if isinstance(approval, dict):
        sig_path = approval.get("signature_image_path")
        if sig_path and Path(sig_path).exists():
            approval["signature_image"] = InlineImage(doc, str(sig_path), width=Mm(40))

    doc.render(context)

    buf = BytesIO()
    doc.save(buf)
    return buf.getvalue()


def convert_to_pdf(docx_bytes: bytes) -> bytes:
    """Convert .docx bytes to PDF via LibreOffice headless."""
    with tempfile.TemporaryDirectory() as tmpdir:
        docx_path = Path(tmpdir) / "output.docx"
        docx_path.write_bytes(docx_bytes)

        subprocess.run(
            [
                "libreoffice",
                "--headless",
                "--convert-to",
                "pdf",
                "--outdir",
                tmpdir,
                str(docx_path),
            ],
            check=True,
            timeout=30,
            capture_output=True,
        )

        pdf_path = Path(tmpdir) / "output.pdf"
        if not pdf_path.exists():
            raise RuntimeError(
                "LibreOffice PDF conversion failed: output.pdf not found"
            )
        return pdf_path.read_bytes()


def render_to_pdf(
    template_path: str | Path,
    context: dict[str, Any],
) -> bytes:
    """Render a .docx template with context and convert to PDF.

    Convenience wrapper: render_to_docx() → convert_to_pdf().
    """
    docx_bytes = render_to_docx(template_path, context)
    return convert_to_pdf(docx_bytes)


# ── Default template resolution ──


async def resolve_default_template_id(
    db,
    project_id,
    org_id,
    template_type: str,
):
    """Resolve the default template ID: project > org > system.

    Args:
        db: AsyncSession
        project_id: UUID of the project
        org_id: UUID of the organization
        template_type: "SOP" or "BATCH_RECORD"

    Returns:
        UUID of the resolved template, or None if no default found.
    """
    from sqlalchemy import select

    from app.models.iam import Organization
    from app.models.science import Project
    from app.models.templates import DocumentTemplate

    col_attr = (
        "default_sop_template_id"
        if template_type == "SOP"
        else "default_batch_record_template_id"
    )

    # 1. Project default
    result = await db.execute(select(Project).where(Project.id == project_id))
    project = result.scalar_one_or_none()
    if project:
        val = getattr(project, col_attr, None)
        if val:
            return val

    # 2. Org default
    result = await db.execute(select(Organization).where(Organization.id == org_id))
    org = result.scalar_one_or_none()
    if org:
        val = getattr(org, col_attr, None)
        if val:
            return val

    # 3. System default
    result = await db.execute(
        select(DocumentTemplate.id).where(
            DocumentTemplate.is_system == True,
            DocumentTemplate.is_default == True,
            DocumentTemplate.template_type == template_type,
        )
    )
    return result.scalar_one_or_none()


# ── Mock data for template preview ──


def get_mock_context() -> dict[str, Any]:
    """Build mock context for template preview. Lazy — only called when needed."""
    ctx, _ = build_context(
        protocol_name="Example Protocol — Buffer Preparation",
        protocol_description=(
            "This protocol describes the preparation of phosphate-buffered "
            "saline (PBS) for use in downstream cell culture applications."
        ),
        version_number=3,
        created_at="January 15, 2026",
        run_name="Run-2026-001",
        run_status="COMPLETED",
        started_at="2026-01-20 08:00",
        completed_at="2026-01-20 14:30",
        project_name="AAV Production Campaign Q1",
        organization_name="Acme Therapeutics",
        is_role_based=True,
        roles_with_steps=[
            {
                "role_name": "Media Prep",
                "steps": [
                    {
                        "name": "Weigh Reagents",
                        "description": "Weigh out NaCl, KCl, and phosphate salts.",
                        "params": {"nacl_g": 8.0, "kcl_g": 0.2},
                        "param_schema": {
                            "properties": {
                                "nacl_g": {"title": "NaCl", "unit": "g"},
                                "kcl_g": {"title": "KCl", "unit": "g"},
                            }
                        },
                        "duration_min": 10,
                    },
                    {
                        "name": "Dissolve in Water",
                        "description": (
                            "Add reagents to {{volume}} mL of purified water "
                            "and stir until dissolved."
                        ),
                        "params": {"volume": 1000},
                        "param_schema": {
                            "properties": {"volume": {"title": "Volume", "unit": "mL"}}
                        },
                        "duration_min": 15,
                    },
                ],
            },
            {
                "role_name": "QC",
                "steps": [
                    {
                        "name": "Measure pH",
                        "description": "Measure pH and adjust to target.",
                        "params": {"target_ph": 7.4},
                        "param_schema": {
                            "properties": {"target_ph": {"title": "Target pH"}}
                        },
                        "duration_min": 5,
                    },
                ],
            },
        ],
        flat_steps=[
            {
                "id": "s1",
                "name": "Weigh Reagents",
                "description": "Weigh out NaCl, KCl, and phosphate salts.",
                "role_name": "Media Prep",
                "params": {"nacl_g": 8.0, "kcl_g": 0.2},
                "param_schema": {
                    "properties": {
                        "nacl_g": {"title": "NaCl", "unit": "g"},
                        "kcl_g": {"title": "KCl", "unit": "g"},
                    }
                },
                "duration_min": 10,
            },
            {
                "id": "s2",
                "name": "Dissolve in Water",
                "description": (
                    "Add reagents to {{volume}} mL of purified water "
                    "and stir until dissolved."
                ),
                "role_name": "Media Prep",
                "params": {"volume": 1000},
                "param_schema": {
                    "properties": {"volume": {"title": "Volume", "unit": "mL"}}
                },
                "duration_min": 15,
            },
            {
                "id": "s3",
                "name": "Measure pH",
                "description": "Measure pH and adjust to target.",
                "role_name": "QC",
                "params": {"target_ph": 7.4},
                "param_schema": {"properties": {"target_ph": {"title": "Target pH"}}},
                "duration_min": 5,
            },
        ],
    )
    ctx["time_enabled"] = True
    ctx["start_time"] = "08:00"
    ctx["reviewer_enabled"] = True
    ctx["doc_number"] = "SOP-DEMO-001"
    ctx["effective_date"] = "2026-01-01"
    ctx["supersedes_date"] = "2025-01-01"
    ctx["purpose"] = "Demonstrate the end-to-end template surface."
    ctx["scope"] = "Applies to preview rendering only."
    ctx["references"] = "ICH Q7; internal SOP-CORE-001"
    ctx["definitions"] = "CIP = clean-in-place. SOP = Standard Operating Procedure."
    ctx["lot_number"] = "LOT-DEMO-2026-001"
    ctx["batch_number"] = "BAT-DEMO-7"
    # F-0086: demo a lot-producing run so the batch-record template's
    # {%tr if produces_lot %}-gated lot row is exercised in previews.
    ctx["produces_lot"] = True
    ctx["equipment_summary"] = [
        {
            "local_id": "E-001",
            "name": "5L Bioreactor",
            "description": "Sartorius BioStat B Plus",
        },
        {
            "local_id": "E-002",
            "name": "Peristaltic Pump",
            "description": "Cole-Parmer Masterflex",
        },
    ]
    ctx["revision_history"] = [
        {
            "version_number": 1,
            "created_at": "2025-12-01",
            "created_by": "Alice Author",
            "change_summary": "Initial release",
        },
        {
            "version_number": 2,
            "created_at": "2026-01-15",
            "created_by": "Bob Editor",
            "change_summary": "Tightened acceptance criteria",
        },
    ]
    ctx["responsibilities"] = [
        {"role_name": "Operator", "step_summary": "Prep buffer; seed culture; harvest"},
        {"role_name": "Reviewer", "step_summary": "Verify pH; verify volume; sign off"},
    ]
    ctx["deviations"] = []
    ctx.setdefault("approval", None)
    ctx.setdefault("approval_history", [])
    ctx.setdefault("unapproved_warning", "")
    return ctx
