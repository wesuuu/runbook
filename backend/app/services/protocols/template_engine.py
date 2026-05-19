"""Document template engine — renders .docx templates to PDF.

Pipeline: docxtpl fills .docx → LibreOffice headless converts to PDF.
"""

import subprocess
import tempfile
import uuid
from datetime import date, datetime, timezone
from io import BytesIO
from pathlib import Path
from typing import Any

from docx.shared import Mm, Pt
from docxtpl import DocxTemplate, InlineImage, RichText

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
    # Approval (F-0066)
    "approval",
    "approval_history",
    "unapproved_warning",
    "requires_approval",
    # GLP sign-offs (F-0087)
    "signoffs",
    "protocol_approvals",
    "run",
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


def _signoff_to_block(signoff: Any, signer: Any) -> dict[str, Any]:
    """Convert a GlpSignoff + its signer User to a template-friendly dict.

    Mirrors the shape consumed by the SOP/batch-record templates:
    ``{name, email, signature_image, attestation, signed_at, initials}``.
    ``signer`` may be ``None`` if the user row was deleted; fall back to a
    deleted-user placeholder so templates keep rendering.
    """
    if signer is None:
        name = "(deleted user)"
        email = ""
    else:
        name = getattr(signer, "full_name", None) or getattr(signer, "email", "")
        email = getattr(signer, "email", "") or ""
    return {
        "name": name,
        "email": email,
        "signature_image": getattr(signoff, "signature_image_path", None),
        "attestation": getattr(signoff, "attestation", None),
        "signed_at": getattr(signoff, "signed_at", None),
        "initials": (name or "")[:2].upper(),
    }


def _calibration_status(equipment: Any) -> str:
    """Return "OK" / "OVERDUE" / "UNKNOWN" for an Equipment row.

    ``Equipment.next_calibration_date`` is a ``date`` (not datetime); compare
    against ``date.today()`` UTC. Missing dates yield ``"UNKNOWN"``.
    """
    due = getattr(equipment, "next_calibration_date", None)
    if not due:
        return "UNKNOWN"
    today_utc = datetime.now(timezone.utc).date()
    return "OVERDUE" if due < today_utc else "OK"


def _stacked_actual_value(step_exec: dict[str, Any]) -> str:
    """Render a plain-text "Target / Recorded / initials • ts" block.

    Templates may render this via ``{{r step.actual_value_block }}`` once
    RichText support lands; for now the plain string is forwards-compatible.
    """
    if not step_exec:
        return ""
    results = step_exec.get("results") or {}
    target = step_exec.get("target", "")
    unit = step_exec.get("unit", "")
    value = step_exec.get("value")
    if value is None and results:
        # Single-value steps store the result under whichever key the schema
        # exposes; fall back to the first non-empty value.
        for v in results.values():
            if v not in (None, ""):
                value = v
                break
    if value is None:
        value = ""
    delta = step_exec.get("delta_flag", "")
    initials = step_exec.get("initials", "")
    ts = step_exec.get("completed_at", "")
    lines = []
    if target != "":
        lines.append(f"Target: {target} {unit}".rstrip())
    lines.append(f"Recorded: {value} {unit} {delta}".rstrip())
    if initials or ts:
        lines.append(f"{initials} • {ts}".strip(" •"))
    return "\n".join(lines)


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
    # F-0087 GLP additions — all optional and pre-resolved by the caller
    # via assemble_signoff_context_args (keeps build_context sync).
    outcome: str | None = None,
    outcome_notes: str | None = None,
    signoffs: list[Any] | None = None,
    protocol_signoffs: list[Any] | None = None,
    signer_lookup: dict[Any, Any] | None = None,
    equipment_rows: list[Any] | None = None,
) -> tuple[dict[str, Any], list[str]]:
    """Assemble the Jinja2 context dict for template rendering.

    Returns ``(context, unresolved)`` where ``unresolved`` is the
    deduplicated, ordered list of ``{{token}}`` names that could not be
    resolved across all step renders. Pass ``equipment_context`` to make
    ``{{<local_id>_name}}`` / ``{{<local_id>_description}}`` resolvable;
    per-step params still win on key collision.

    GLP context (F-0087) is layered via the ``signoffs``,
    ``protocol_signoffs``, ``equipment_rows``, ``signer_lookup``,
    ``outcome`` and ``outcome_notes`` kwargs — all optional and gathered
    by :func:`assemble_signoff_context_args` so this function stays sync.
    """
    exec_data = execution_data or {}
    umap = user_map or {}
    sigmap = user_signatures or {}
    eq_ctx = equipment_context or {}
    unresolved_all: list[str] = []
    _seen_unresolved: set[str] = set()

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

    # Build step contexts for the flat step list (batch record table)
    step_contexts = []
    for step in flat_steps or []:
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
        VS = Pt(8)  # value font size — must match template cell
        rt = RichText()
        if len(editable) > 1:
            for idx, pd in enumerate(param_details):
                if idx > 0:
                    rt.add("\a")  # new paragraph between params
                rt.add(f"{pd['label']}: ", bold=True, size=VS)
                if pd["is_edited"]:
                    rt.add(
                        pd["original_value"],
                        strike=True,
                        color="#A0A0A0",
                        size=VS,
                    )
                    annotation = ""
                    if pd["editor"] or pd["edited_at"]:
                        parts = [p for p in (pd["editor"], pd["edited_at"]) if p]
                        annotation = " " + " ".join(parts)
                    rt.add(f"{annotation} \u2192 ", size=VS, color="#64748B")
                rt.add(pd["value"], size=VS)
        elif single_value:
            rt.add(single_value, size=VS)
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

        # F-0087: stacked Target/Recorded/initials block + edit reason for
        # GLP-compliant batch record rows. ``actual_value_block`` is a plain
        # string today (templates can switch to {{r ...}} when they add
        # RichText); ``edit_reason`` surfaces GMP-style change rationale.
        actual_value_block = _stacked_actual_value(sd)
        edit_reason = sd.get("edit_reason") or sd.get("change_reason")

        step_ctx = {
            "_step_id": step_id,
            "name": step.get("name", ""),
            "description": full_desc,
            "duration_min": step.get("duration_min"),
            "role_name": step.get("role_name", ""),
            "params": params,
            "param_details": param_details,
            "has_multi_params": len(editable) > 1,
            "single_value": single_value,
            "value_display": value_display,
            "actual_value_block": actual_value_block,
            "edit_reason": edit_reason,
            "initials": initials,
            "_initials_user_id": initials_user_id,
            "_initials_name": completer_name,
            "status": sd.get("status", ""),
            "notes_text": step_notes_text,
            "figure_refs": figure_refs,
            "notes_display": notes_display,
        }
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
        for s in role_data.get("steps", []):
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

            # Pre-compute step body as RichText to avoid empty
            # conditional paragraphs in the Word output
            sop_body = RichText()
            if desc:
                sop_body.add(f"    {desc}", size=Pt(10), color="#334155")
            if param_sentence:
                if desc:
                    sop_body.add("\a")
                sop_body.add(f"    {param_sentence}", size=Pt(10), color="#334155")
            duration = s.get("duration_min")
            if duration:
                if desc or param_sentence:
                    sop_body.add("\a")
                sop_body.add(
                    f"    Allow {duration} minutes for this step.",
                    size=Pt(10),
                    color="#64748B",
                    italic=True,
                )

            sop_steps.append(
                {
                    "name": s.get("name", ""),
                    "sop_body": sop_body,
                }
            )

            # Batch-record-style step (reuse from step_contexts if available)
            step_id = s.get("id", "")
            br_step = step_ctx_by_id.get(step_id)
            if br_step:
                br_steps.append(br_step)
            else:
                # Fallback: build a minimal step context from role step data
                br_steps.append(
                    {
                        "_step_id": step_id,
                        "name": s.get("name", ""),
                        "description": desc or param_sentence or "--",
                        "duration_min": s.get("duration_min"),
                        "role_name": role_data.get("role_name", ""),
                        "value_display": "",
                        "initials": "",
                        "_initials_user_id": "",
                        "_initials_name": "",
                        "notes_display": "",
                    }
                )

        # Pre-compute role header as RichText to avoid empty
        # conditional paragraphs that create whitespace gaps in Word
        role_name = role_data.get("role_name", "")
        process_name = role_data.get("process_name", "")
        process_desc = role_data.get("process_description", "")
        header_name = process_name or role_name

        sop_header = RichText()
        is_first_role = len(role_contexts) == 0
        # Page break before non-first roles
        if not is_first_role:
            sop_header.add("\f")
        if header_name:
            sop_header.add(header_name, bold=True, size=Pt(14))
            if process_desc:
                sop_header.add("\a")  # new paragraph
                sop_header.add(process_desc, size=Pt(10), color="#64748B")
            sop_header.add("\a")
            sop_header.add("\u2500" * 50, size=Pt(6), color="#C8C8C8")

        # Pre-compute batch record header (page break + role name)
        br_header = RichText()
        if not is_first_role:
            br_header.add("\f")  # page break before non-first roles
        if header_name:
            br_header.add(header_name, bold=True, size=Pt(14))

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
            f"Run: {run_name}", bold=True, size=Pt(10), color="#334155"
        )
    if protocol_description:
        if run_name:
            protocol_subtitle.add("\a")
        protocol_subtitle.add(protocol_description, size=Pt(10), color="#64748B")

    # ── F-0087 GLP context ──
    # Build {role_lower: block} maps from the pre-resolved signoff lists.
    # ``signer_lookup`` carries the User object for each signoff so the
    # caller (which holds the AsyncSession) controls all DB I/O.
    lookup = signer_lookup or {}

    def _resolve_signer(s: Any) -> Any:
        # Prefer the SQLAlchemy relationship when eagerly loaded; fall
        # back to the explicit lookup keyed by signer_id.
        try:
            existing = getattr(s, "signer", None)
        except Exception:
            existing = None
        if existing is not None:
            return existing
        return lookup.get(getattr(s, "signer_id", None))

    run_signoffs_map: dict[str, dict[str, Any]] = {}
    for s in signoffs or []:
        role = (getattr(s, "role", "") or "").lower()
        if role:
            run_signoffs_map[role] = _signoff_to_block(s, _resolve_signer(s))

    protocol_approvals_map: dict[str, dict[str, Any]] = {}
    for s in protocol_signoffs or []:
        role = (getattr(s, "role", "") or "").lower()
        if role:
            protocol_approvals_map[role] = _signoff_to_block(s, _resolve_signer(s))

    # Back-compat: legacy templates reference ``approval.approver_name``.
    # Prefer QAU > STUDY_DIRECTOR > SPONSOR so the strongest signature is
    # the one rendered when the template only shows a single block.
    approval_alias: dict[str, Any] | None = None
    legacy_source = (
        protocol_approvals_map.get("qau")
        or protocol_approvals_map.get("study_director")
        or protocol_approvals_map.get("sponsor")
    )
    if legacy_source:
        approval_alias = {
            "approver_name": legacy_source["name"],
            "approver_email": legacy_source["email"],
            "signature_image": legacy_source["signature_image"],
            "signature_image_path": legacy_source["signature_image"],
            "signature_statement": legacy_source["attestation"],
            "approved_at": legacy_source["signed_at"],
            "protocol_version": version_number,
        }

    run_block = {
        "outcome": outcome,
        "outcome_notes": outcome_notes,
        "started_at": started_at or "",
        "completed_at": completed_at or "",
        "name": run_name or "",
        "status": run_status or "",
    }

    # Equipment rows for the GLP "Equipment used" appendix. Each row exposes
    # serial number + calibration status so the template can flag overdue
    # instruments.
    equipment_list: list[dict[str, Any]] = []
    for eq in equipment_rows or []:
        equipment_list.append(
            {
                "id": getattr(eq, "id", None),
                "name": getattr(eq, "name", "") or "",
                "description": getattr(eq, "description", "") or "",
                "equipment_type": getattr(eq, "equipment_type", None),
                "location": getattr(eq, "location", None),
                "serial_number": getattr(eq, "serial_number", None),
                "calibration_due_at": getattr(eq, "next_calibration_date", None),
                "calibration_status": _calibration_status(eq),
            }
        )

    ctx_out: dict[str, Any] = {
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
        "page_break": RichText("\f"),
        "steps": step_contexts,
        "roles": role_contexts,
        "notes": note_contexts,
        "figures": figure_contexts,
        "non_image_attachments": non_image_att_contexts,
        "_user_signatures": sigmap,
        # F-0087 additions
        "signoffs": run_signoffs_map,
        "protocol_approvals": protocol_approvals_map,
        "run": run_block,
        "equipment": equipment_list,
    }
    if approval_alias is not None:
        # Only set when a protocol sign-off exists — preserves the
        # endpoint-level _build_approval_context output when callers
        # ``ctx.update(approval_ctx)`` after building (the legacy path
        # has approver_name/approver_email/etc. with the same keys).
        ctx_out["approval"] = approval_alias

    return (
        ctx_out,
        unresolved_all,
    )


def render_to_docx(
    template_path: str | Path,
    context: dict[str, Any],
) -> bytes:
    """Render a .docx template with context, return .docx bytes."""
    doc = DocxTemplate(str(template_path))

    # Convert figure file paths to InlineImage objects
    for fig in context.get("figures", []):
        fpath_str = fig.pop("_file_path", None)
        if fpath_str:
            fpath = Path(fpath_str)
            if fpath.exists():
                fig["image"] = InlineImage(doc, str(fpath), width=Mm(150))
            else:
                fig["image"] = f"[Image not found: {fpath.name}]"

    # F-0080 — swap step.initials to an InlineImage of the user's drawn
    # signature, or a cursive RichText fallback. Mirrors the figure
    # handling above: build_context puts placeholders, render_to_docx
    # finalizes them against the open DocxTemplate.
    user_signatures = context.pop("_user_signatures", {}) or {}

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

    _swap(context.get("steps"))
    for role in context.get("roles", []) or []:
        _swap(role.get("steps"))
        _swap(role.get("br_steps"))

    # F-0087 — swap actual_value_block plain string to a RichText so newlines
    # render as <w:br/> line breaks inside the cell. The template uses
    # `{{r step.actual_value_block }}` which expects a RichText object.
    def _swap_actual_value(steps_list):
        for step in steps_list or []:
            raw = step.get("actual_value_block")
            if isinstance(raw, str) and raw:
                rt = RichText()
                for i, line in enumerate(raw.split("\n")):
                    if i:
                        rt.add("\a")  # RichText line break
                    rt.add(line)
                step["actual_value_block"] = rt

    _swap_actual_value(context.get("steps"))
    for role in context.get("roles", []) or []:
        _swap_actual_value(role.get("steps"))
        _swap_actual_value(role.get("br_steps"))

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


# ── F-0087: async helper that pre-resolves the new GLP context vars ──


async def assemble_signoff_context_args(
    db: Any,
    *,
    run: Any = None,
    protocol: Any = None,
) -> dict[str, Any]:
    """Gather GLP sign-off / equipment / outcome data for build_context.

    Returns a dict suitable for ``**kwargs`` splatting into the sync
    :func:`build_context`. Splits DB I/O from the pure-Python context
    shaping so callers — most of which already pre-resolve protocol,
    project, attachments and execution_data synchronously — don't have
    to be turned async.

    Looks up active GLP sign-offs on the run and/or its protocol,
    resolves each signer User, materialises Equipment rows for the
    run/protocol graph so per-row ``serial_number`` /
    ``calibration_due_at`` are available, and surfaces
    ``run.outcome`` / ``run.outcome_notes`` when present.
    """
    from sqlalchemy import select

    from app.models.iam import User
    from app.models.science import Equipment
    from app.services.signoffs.queries import list_active_signoffs

    args: dict[str, Any] = {}
    signer_ids: set[Any] = set()
    signer_lookup: dict[Any, User] = {}

    if run is not None:
        run_signoffs = list(await list_active_signoffs(db, "run", run.id))
        args["signoffs"] = run_signoffs
        for s in run_signoffs:
            if s.signer_id:
                signer_ids.add(s.signer_id)
        args["outcome"] = getattr(run, "outcome", None)
        args["outcome_notes"] = getattr(run, "outcome_notes", None)

    proto_target = protocol if protocol is not None else getattr(run, "protocol", None)
    if proto_target is not None:
        proto_signoffs = list(
            await list_active_signoffs(db, "protocol", proto_target.id)
        )
        args["protocol_signoffs"] = proto_signoffs
        for s in proto_signoffs:
            if s.signer_id:
                signer_ids.add(s.signer_id)

    # Load missing signers in one round-trip. ``list_active_signoffs``
    # selectinloads the signer on each row, but explicit lookup keeps the
    # sync helper independent of relationship loading state and tolerates
    # detached instances inside test SAVEPOINTs.
    if signer_ids:
        result = await db.execute(select(User).where(User.id.in_(signer_ids)))
        for u in result.scalars().all():
            signer_lookup[u.id] = u
    args["signer_lookup"] = signer_lookup

    # Materialise Equipment rows referenced by the run/protocol graph so
    # the template can render serial numbers and calibration status. The
    # graph stores equipment_id strings on each unit-op node.
    graph = None
    if run is not None:
        graph = run.graph or None
    elif protocol is not None:
        graph = protocol.graph or None

    eq_uuids: set[uuid.UUID] = set()
    if graph:
        for node in graph.get("nodes") or []:
            if node.get("type") != "unitOp":
                continue
            for eq in (node.get("data") or {}).get("equipment") or []:
                eq_id = eq.get("equipment_id")
                if not eq_id:
                    continue
                try:
                    eq_uuids.add(uuid.UUID(eq_id))
                except (ValueError, TypeError):
                    continue

    if eq_uuids:
        result = await db.execute(select(Equipment).where(Equipment.id.in_(eq_uuids)))
        args["equipment_rows"] = list(result.scalars().all())
    else:
        args["equipment_rows"] = []

    return args


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
    return ctx
