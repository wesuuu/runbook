"""Generate the default batch record .docx template.

One-shot generator. Mirrors the GLP Tox Batch Manufacturing Record
example structure (6 sections) using docxtpl jinja syntax wired to
the keys produced by ``template_engine.build_context``.

Conditional sub-section tables in Section 4 (Unit Operations) only
render when the protocol is role-based AND has more than one role —
otherwise a single flat steps table is rendered.

Run from ``backend/``:

    python scripts/build_batch_record_default.py
"""

from __future__ import annotations

from pathlib import Path

from docx import Document
from docx.enum.table import WD_ALIGN_VERTICAL
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Pt, RGBColor

OUT = (
    Path(__file__).resolve().parent.parent
    / "app"
    / "services"
    / "documents"
    / "templates"
    / "batch_record_default.docx"
)


def _set_cell_shading(cell, hex_fill: str) -> None:
    tc_pr = cell._tc.get_or_add_tcPr()
    shd = OxmlElement("w:shd")
    shd.set(qn("w:val"), "clear")
    shd.set(qn("w:color"), "auto")
    shd.set(qn("w:fill"), hex_fill)
    tc_pr.append(shd)


def _set_cell_border(cell, color: str = "BFBFBF", sz: int = 4) -> None:
    tc_pr = cell._tc.get_or_add_tcPr()
    tc_borders = OxmlElement("w:tcBorders")
    for edge in ("top", "left", "bottom", "right"):
        b = OxmlElement(f"w:{edge}")
        b.set(qn("w:val"), "single")
        b.set(qn("w:sz"), str(sz))
        b.set(qn("w:color"), color)
        tc_borders.append(b)
    tc_pr.append(tc_borders)


def _style_cell(
    cell,
    text: str = "",
    *,
    bold: bool = False,
    size: int = 10,
    color: str | None = None,
    fill: str | None = None,
    align=None,
):
    cell.text = ""
    p = cell.paragraphs[0]
    if align is not None:
        p.alignment = align
    run = p.add_run(text)
    run.font.size = Pt(size)
    run.bold = bold
    if color:
        run.font.color.rgb = RGBColor.from_string(color)
    if fill:
        _set_cell_shading(cell, fill)
    _set_cell_border(cell)
    cell.vertical_alignment = WD_ALIGN_VERTICAL.CENTER


def _add_para(doc, text: str, *, bold: bool = False, size: int = 11,
              color: str | None = None, align=None, italic: bool = False):
    p = doc.add_paragraph()
    if align is not None:
        p.alignment = align
    run = p.add_run(text)
    run.bold = bold
    run.italic = italic
    run.font.size = Pt(size)
    if color:
        run.font.color.rgb = RGBColor.from_string(color)
    return p


def _add_heading(doc, text: str, level: int = 2):
    """Add a section heading with consistent styling."""
    size = {1: 18, 2: 14, 3: 12}.get(level, 11)
    p = doc.add_paragraph()
    p.paragraph_format.space_before = Pt(12)
    p.paragraph_format.space_after = Pt(4)
    run = p.add_run(text)
    run.bold = True
    run.font.size = Pt(size)
    run.font.color.rgb = RGBColor.from_string("1F2937")
    return p


def _add_jinja_para(doc, jinja: str):
    """Add a plain paragraph carrying a single jinja control tag (e.g.,
    ``{%p for role in roles %}``). docxtpl scans paragraph text for
    these and strips the carrier paragraph."""
    p = doc.add_paragraph()
    run = p.add_run(jinja)
    run.font.size = Pt(8)
    return p


HEADER_FILL = "1F2937"  # slate-800
SUBHEAD_FILL = "F1F5F9"  # slate-100
ROW_BORDER = "BFBFBF"


def build() -> Document:
    doc = Document()

    # ── Page margins ─────────────────────────────────────────────
    for section in doc.sections:
        section.top_margin = Pt(36)
        section.bottom_margin = Pt(36)
        section.left_margin = Pt(54)
        section.right_margin = Pt(54)

    # ── Unapproved warning banner ────────────────────────────────
    _add_jinja_para(doc, "{%p if unapproved_warning %}")
    warn = doc.add_paragraph()
    warn.alignment = WD_ALIGN_PARAGRAPH.CENTER
    wrun = warn.add_run("⚠ UNAPPROVED — DRAFT ONLY")
    wrun.bold = True
    wrun.font.size = Pt(12)
    wrun.font.color.rgb = RGBColor.from_string("B91C1C")
    _add_jinja_para(doc, "{%p endif %}")

    # ── Document title ───────────────────────────────────────────
    title_p = doc.add_paragraph()
    title_p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    title_run = title_p.add_run("{{ protocol_name }}")
    title_run.bold = True
    title_run.font.size = Pt(18)
    title_run.font.color.rgb = RGBColor.from_string("0F172A")

    sub_p = doc.add_paragraph()
    sub_p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    sub_run = sub_p.add_run("Toxicology Study Material Manufacturing Record")
    sub_run.italic = True
    sub_run.font.size = Pt(11)
    sub_run.font.color.rgb = RGBColor.from_string("475569")

    desig_p = doc.add_paragraph()
    desig_p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    desig_run = desig_p.add_run('Informal Designation: "GLP Level Batch Record"')
    desig_run.font.size = Pt(9)
    desig_run.font.color.rgb = RGBColor.from_string("64748B")

    _add_para(
        doc,
        "Purpose: To document the manufacturing process for non-clinical test "
        "articles intended for use in Good Laboratory Practice (GLP) studies. "
        "This record provides a complete history of material production, including "
        "all raw materials, equipment, process steps, and deviations.",
        size=10,
        color="334155",
    )

    # ── Meta line: run + project + org + dates ──────────────────
    _add_jinja_para(doc, "{%p if run_name %}")
    _add_para(
        doc,
        "Run: {{ run_name }}    Status: {{ run_status }}    "
        "Started: {{ started_at }}    Completed: {{ completed_at }}",
        size=9,
        color="475569",
    )
    _add_jinja_para(doc, "{%p endif %}")
    _add_para(
        doc,
        "Project: {{ project_name }}    Organization: {{ organization_name }}    "
        "Protocol Version: v{{ version_number }}    Generated: {{ created_at }}",
        size=9,
        color="475569",
    )

    # ── Section 1: General Information ───────────────────────────
    _add_heading(doc, "1. General Information", level=2)

    t1 = doc.add_table(rows=4, cols=2)
    t1.autofit = True
    label_col_w = Pt(180)
    rows_data = [
        ("Product Name / Candidate", "{{ protocol_name }}"),
        ("Batch / Lot Number", "{{ run_name }}"),
        ("Target Yield / Scale", ""),
        ("Process SOP / Protocol Reference", "{{ protocol_name }} (v{{ version_number }})"),
    ]
    for r, (label, value) in enumerate(rows_data):
        _style_cell(t1.rows[r].cells[0], label, bold=True, size=10,
                    color="FFFFFF", fill=HEADER_FILL)
        _style_cell(t1.rows[r].cells[1], value, size=10)
        t1.rows[r].cells[0].width = label_col_w

    # ── Section 2: Bill of Materials ─────────────────────────────
    _add_heading(doc, "2. Bill of Materials (BOM)", level=2)
    _add_para(
        doc,
        "Record all raw materials, media, and buffers utilized in this run. "
        "If material data is captured by the system, rows are populated "
        "automatically; otherwise complete manually.",
        size=9, color="64748B", italic=True,
    )

    t2 = doc.add_table(rows=5, cols=5)
    bom_headers = [
        "Material Description",
        "Part / Lot Number",
        "Required Quantity",
        "Actual Quantity Added",
        "Operator Initials & Date",
    ]
    for ci, h in enumerate(bom_headers):
        _style_cell(t2.rows[0].cells[ci], h, bold=True, size=10,
                    color="FFFFFF", fill=HEADER_FILL)
    # jinja loop row
    _style_cell(t2.rows[1].cells[0], "{%tr for material in materials %}", size=8)
    _style_cell(t2.rows[2].cells[0], "{{ material.description }}", size=10)
    _style_cell(t2.rows[2].cells[1], "{{ material.lot_number }}", size=10)
    _style_cell(t2.rows[2].cells[2], "{{ material.required_qty }}", size=10)
    _style_cell(t2.rows[2].cells[3], "{{ material.actual_qty }}", size=10)
    _style_cell(t2.rows[2].cells[4], "{{ material.operator }}", size=10)
    _style_cell(t2.rows[3].cells[0], "{%tr endfor %}", size=8)
    # 1 manual fill-in row (always renders, useful for paper workflow)
    for ci in range(5):
        _style_cell(t2.rows[4].cells[ci], "", size=10)

    # ── Section 3: Equipment Log ─────────────────────────────────
    _add_heading(doc, "3. Equipment Log", level=2)
    _add_para(
        doc,
        "Record primary equipment used to ensure traceability in the event of "
        "equipment failure or contamination.",
        size=9, color="64748B", italic=True,
    )

    t3 = doc.add_table(rows=5, cols=4)
    eq_headers = [
        "Equipment Name / Type",
        "Equipment ID (Asset Tag)",
        "Calibration Status (Valid Until)",
        "Operator Initials & Date",
    ]
    for ci, h in enumerate(eq_headers):
        _style_cell(t3.rows[0].cells[ci], h, bold=True, size=10,
                    color="FFFFFF", fill=HEADER_FILL)
    _style_cell(t3.rows[1].cells[0], "{%tr for eq in equipment %}", size=8)
    _style_cell(t3.rows[2].cells[0], "{{ eq.name }}", size=10)
    _style_cell(t3.rows[2].cells[1], "{{ eq.asset_id }}", size=10)
    _style_cell(t3.rows[2].cells[2], "{{ eq.calibration }}", size=10)
    _style_cell(t3.rows[2].cells[3], "{{ eq.operator }}", size=10)
    _style_cell(t3.rows[3].cells[0], "{%tr endfor %}", size=8)
    for ci in range(4):
        _style_cell(t3.rows[4].cells[ci], "", size=10)

    # ── Section 4: Execution: Unit Operations ───────────────────
    _add_heading(doc, "4. Execution: Unit Operations", level=2)
    _add_para(
        doc,
        "Execute process steps. Unlike GMP, second-person verification "
        "(Verifier) is not always strictly mandated for all steps in "
        "development/tox manufacturing — apply per your SOP.",
        size=9, color="64748B", italic=True,
    )

    # Conditional: per-role tables when multiple roles
    _add_jinja_para(doc, "{%p if is_role_based and roles|length > 1 %}")
    _add_jinja_para(doc, "{%p for role in roles %}")

    role_head_p = doc.add_paragraph()
    role_head_p.paragraph_format.space_before = Pt(10)
    role_head_p.paragraph_format.space_after = Pt(4)
    rh_run = role_head_p.add_run(
        "4.{{ loop.index }}  {{ role.process_name or role.name }}"
    )
    rh_run.bold = True
    rh_run.font.size = Pt(12)
    rh_run.font.color.rgb = RGBColor.from_string("1F2937")

    t4_role = doc.add_table(rows=3, cols=6)
    step_headers = ["Step", "Instruction", "Target Parameter",
                    "Actual Value", "Operator", "Verifier"]
    for ci, h in enumerate(step_headers):
        _style_cell(t4_role.rows[0].cells[ci], h, bold=True, size=10,
                    color="FFFFFF", fill=HEADER_FILL)
    _style_cell(t4_role.rows[1].cells[0], "{%tr for step in role.steps %}", size=8)
    _style_cell(t4_role.rows[2].cells[0], "{{ loop.index }}", size=10,
                align=WD_ALIGN_PARAGRAPH.CENTER)
    _style_cell(t4_role.rows[2].cells[1], "{{ step.name }}", size=10)
    _style_cell(t4_role.rows[2].cells[2], "{{ step.description }}", size=9)
    # value_display is a RichText so use {{r ... }}
    cell_val = t4_role.rows[2].cells[3]
    cell_val.text = ""
    p_val = cell_val.paragraphs[0]
    run_val = p_val.add_run("{{r step.value_display }}")
    run_val.font.size = Pt(10)
    _set_cell_border(cell_val)
    _style_cell(t4_role.rows[2].cells[4], "{{ step.initials }}", size=10,
                align=WD_ALIGN_PARAGRAPH.CENTER)
    _style_cell(t4_role.rows[2].cells[5], "", size=10)
    # close the jinja for-row
    # We need a row after the body row carrying {%tr endfor %}
    # Add it now (a 4th row).
    t4_role.add_row()
    _style_cell(t4_role.rows[3].cells[0], "{%tr endfor %}", size=8)

    _add_jinja_para(doc, "{%p endfor %}")
    _add_jinja_para(doc, "{%p else %}")

    # Single combined table (no roles or single role)
    t4_flat = doc.add_table(rows=3, cols=6)
    for ci, h in enumerate(step_headers):
        _style_cell(t4_flat.rows[0].cells[ci], h, bold=True, size=10,
                    color="FFFFFF", fill=HEADER_FILL)
    _style_cell(t4_flat.rows[1].cells[0], "{%tr for step in steps %}", size=8)
    _style_cell(t4_flat.rows[2].cells[0], "{{ loop.index }}", size=10,
                align=WD_ALIGN_PARAGRAPH.CENTER)
    _style_cell(t4_flat.rows[2].cells[1], "{{ step.name }}", size=10)
    _style_cell(t4_flat.rows[2].cells[2], "{{ step.description }}", size=9)
    cell_val_flat = t4_flat.rows[2].cells[3]
    cell_val_flat.text = ""
    p_vf = cell_val_flat.paragraphs[0]
    rv = p_vf.add_run("{{r step.value_display }}")
    rv.font.size = Pt(10)
    _set_cell_border(cell_val_flat)
    _style_cell(t4_flat.rows[2].cells[4], "{{ step.initials }}", size=10,
                align=WD_ALIGN_PARAGRAPH.CENTER)
    _style_cell(t4_flat.rows[2].cells[5], "", size=10)
    t4_flat.add_row()
    _style_cell(t4_flat.rows[3].cells[0], "{%tr endfor %}", size=8)

    _add_jinja_para(doc, "{%p endif %}")

    # ── Section 5: Deviations and Process Comments ──────────────
    _add_heading(doc, "5. Deviations and Process Comments", level=2)
    _add_para(
        doc,
        "Log any deviations from the target parameters or standard operating "
        "procedures. In development/tox runs, deviations are expected; the "
        "key is rigorous documentation. Run notes are surfaced here.",
        size=9, color="64748B", italic=True,
    )

    t5 = doc.add_table(rows=5, cols=4)
    dev_headers = [
        "Step / Status Ref.",
        "Description of Deviation / Observation",
        "Impact Assessment Required? (Y/N)",
        "Lead Reviewer Sign-off",
    ]
    for ci, h in enumerate(dev_headers):
        _style_cell(t5.rows[0].cells[ci], h, bold=True, size=10,
                    color="FFFFFF", fill=HEADER_FILL)
    _style_cell(t5.rows[1].cells[0], "{%tr for note in notes %}", size=8)
    _style_cell(t5.rows[2].cells[0], "{{ note.run_status }}", size=10)
    _style_cell(t5.rows[2].cells[1], "{{ note.content }}", size=10)
    _style_cell(t5.rows[2].cells[2], "", size=10)
    _style_cell(t5.rows[2].cells[3],
                "{{ note.author_name }}\n{{ note.created_at }}", size=9)
    _style_cell(t5.rows[3].cells[0], "{%tr endfor %}", size=8)
    # 1 blank manual row
    for ci in range(4):
        _style_cell(t5.rows[4].cells[ci], "", size=10)

    # ── Section 6: Final Disposition & Signatures ───────────────
    _add_heading(doc, "6. Final Disposition & Signatures", level=2)
    _add_para(
        doc,
        "By signing below, I certify that the material described herein was "
        "produced according to the specified process instructions and that all "
        "deviations have been reviewed and assessed for impact on the suitability "
        "of the material for its intended non-clinical use.",
        size=9, color="64748B", italic=True,
    )

    # Approval block (system-captured) — appears when approval present
    _add_jinja_para(doc, "{%p if approval %}")
    _add_para(
        doc,
        "Approved by: {{ approval.approver_name }} "
        "<{{ approval.approver_email }}>",
        size=10, bold=True,
    )
    _add_para(
        doc,
        "Approved at: {{ approval.approved_at }}    "
        "Protocol Version: {{ approval.protocol_version }}",
        size=9, color="475569",
    )
    _add_jinja_para(doc, "{%p if approval.signature_statement %}")
    _add_para(
        doc,
        'Statement: "{{ approval.signature_statement }}"',
        size=9, color="334155", italic=True,
    )
    _add_jinja_para(doc, "{%p endif %}")
    _add_jinja_para(doc, "{%p if approval.signature_image %}")
    sig_p = doc.add_paragraph()
    sig_run = sig_p.add_run("Signature: {{ approval.signature_image }}")
    sig_run.font.size = Pt(10)
    _add_jinja_para(doc, "{%p endif %}")
    _add_jinja_para(doc, "{%p endif %}")

    # Approval history table — full audit trail
    _add_jinja_para(doc, "{%p if approval_history %}")
    _add_para(doc, "Approval History", bold=True, size=11)

    t6 = doc.add_table(rows=3, cols=4)
    sig_headers = ["Action / Role", "Name (Print)", "Signature Statement", "Date"]
    for ci, h in enumerate(sig_headers):
        _style_cell(t6.rows[0].cells[ci], h, bold=True, size=10,
                    color="FFFFFF", fill=HEADER_FILL)
    _style_cell(t6.rows[1].cells[0], "{%tr for ev in approval_history %}", size=8)
    _style_cell(t6.rows[2].cells[0], "{{ ev.action }}", size=10)
    _style_cell(t6.rows[2].cells[1], "{{ ev.actor_name }}", size=10)
    _style_cell(t6.rows[2].cells[2], "{{ ev.signature_statement }}", size=9)
    _style_cell(t6.rows[2].cells[3], "{{ ev.created_at }}", size=9)
    t6.add_row()
    _style_cell(t6.rows[3].cells[0], "{%tr endfor %}", size=8)
    _add_jinja_para(doc, "{%p endif %}")

    # Manual sign-off rows — always present for paper workflow
    _add_para(doc, "Wet-Ink Sign-Off", bold=True, size=11)
    t7 = doc.add_table(rows=4, cols=4)
    wet_headers = ["Role", "Name (Print)", "Signature", "Date"]
    for ci, h in enumerate(wet_headers):
        _style_cell(t7.rows[0].cells[ci], h, bold=True, size=10,
                    color="FFFFFF", fill=HEADER_FILL)
    wet_roles = [
        "Lead Operator / Engineer",
        "Process Development Lead",
        "Quality / Compliance (if applicable)",
    ]
    for ri, role in enumerate(wet_roles, start=1):
        _style_cell(t7.rows[ri].cells[0], role, bold=True, size=10,
                    fill=SUBHEAD_FILL)
        for ci in range(1, 4):
            _style_cell(t7.rows[ri].cells[ci], "", size=10)

    # ── Appendix: Figures (run-level images) ────────────────────
    _add_jinja_para(doc, "{%p if figures %}")
    _add_para(doc, "{{r page_break }}", size=10)
    _add_heading(doc, "Appendix A: Figures", level=2)
    _add_jinja_para(doc, "{%p for fig in figures %}")
    fig_p = doc.add_paragraph()
    fig_run = fig_p.add_run("{{ fig.image }}")
    fig_run.font.size = Pt(10)
    _add_para(
        doc,
        "Figure {{ fig.number }}: {{ fig.filename }}  ({{ fig.step_name }}, "
        "uploaded {{ fig.uploaded_at }})",
        size=9, color="475569", italic=True,
    )
    _add_jinja_para(doc, "{%p endfor %}")
    _add_jinja_para(doc, "{%p endif %}")

    # ── Appendix: Non-image attachments ─────────────────────────
    _add_jinja_para(doc, "{%p if non_image_attachments %}")
    _add_heading(doc, "Appendix B: Attachments", level=2)
    t8 = doc.add_table(rows=3, cols=4)
    att_headers = ["Filename", "Type", "Scope", "Uploaded"]
    for ci, h in enumerate(att_headers):
        _style_cell(t8.rows[0].cells[ci], h, bold=True, size=10,
                    color="FFFFFF", fill=HEADER_FILL)
    _style_cell(t8.rows[1].cells[0], "{%tr for att in non_image_attachments %}",
                size=8)
    _style_cell(t8.rows[2].cells[0], "{{ att.filename }}", size=10)
    _style_cell(t8.rows[2].cells[1], "{{ att.type }}", size=10)
    _style_cell(t8.rows[2].cells[2], "{{ att.scope }}", size=10)
    _style_cell(t8.rows[2].cells[3], "{{ att.uploaded_at }}", size=10)
    t8.add_row()
    _style_cell(t8.rows[3].cells[0], "{%tr endfor %}", size=8)
    _add_jinja_para(doc, "{%p endif %}")

    return doc


def main() -> None:
    doc = build()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    doc.save(str(OUT))
    print(f"Wrote {OUT} ({OUT.stat().st_size:,} bytes)")


if __name__ == "__main__":
    main()
