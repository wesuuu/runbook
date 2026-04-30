"""Document template engine — renders .docx templates to PDF.

Pipeline: docxtpl fills .docx → LibreOffice headless converts to PDF.
"""

import subprocess
import tempfile
from datetime import datetime
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
    user_signatures: dict[str, str],
    docx: DocxTemplate,
):
    """Return an InlineImage of the user's drawn initials if registered,
    else the auto-generated text initials. The template uses
    `{{ step.initials }}` (plain), which renders InlineImage objects
    natively but cannot render RichText — so the fallback is a plain
    string, matching pre-F-0080 behavior."""
    path = user_signatures.get(user_id)
    if path and Path(path).exists():
        return InlineImage(docx, path, width=Mm(20))
    return _get_initials(name)


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
    user_signatures: dict[str, str] | None = None,
    started_by_id: str | None = None,
    notes: list[dict[str, Any]] | None = None,
    attachments: list[dict[str, Any]] | None = None,
    storage: FileStorageService | None = None,
) -> dict[str, Any]:
    """Assemble the Jinja2 context dict for template rendering."""
    exec_data = execution_data or {}
    umap = user_map or {}
    sigmap = user_signatures or {}

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
            desc = _render_template(desc, params)

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
                desc = _render_template(desc, params)
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

    return {
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
    }


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
    return build_context(
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
