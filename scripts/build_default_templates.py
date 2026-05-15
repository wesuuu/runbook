"""Build production-grade SOP + Batch Record .docx templates.

Run from repo root:
    python scripts/build_default_templates.py

Writes:
    backend/app/services/documents/templates/sop_default.docx
    backend/app/services/documents/templates/batch_record_default.docx

Templates use docxtpl Jinja2 syntax: {{ var }}, {% if %}, {% for %},
{%tr for %}, {%tc if %}. RichText tokens (e.g. {{r step.sop_body }}) are
rendered as paragraph runs that already contain newlines and page breaks
when build_context populates them.
"""
from __future__ import annotations

from pathlib import Path

from docx import Document
from docx.document import Document as DocxDocument
from docx.enum.table import WD_ALIGN_VERTICAL
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Inches, Pt, RGBColor
from docx.table import _Cell
from docx.text.paragraph import Paragraph

REPO_ROOT = Path(__file__).resolve().parent.parent
TEMPLATES_DIR = REPO_ROOT / "backend/app/services/documents/templates"

# SOP design tokens — refined scientific editorial. Cambria for prose,
# Calibri for labels and the procedure number column. Grayscale ink only.
INK = "1F2937"           # body text
INK_DEEP = "0F172A"      # headings, step names
INK_MUTED = "64748B"     # meta, captions
RULE = "94A3B8"          # paragraph borders
SHADE = "F1F5F9"         # table header fill
SERIF = "Cambria"
SANS = "Calibri"


def _p(
    doc: DocxDocument,
    text: str,
    bold: bool = False,
    size: int = 11,
    align: WD_ALIGN_PARAGRAPH | None = None,
) -> Paragraph:
    p = doc.add_paragraph()
    if align is not None:
        p.alignment = align
    run = p.add_run(text)
    run.bold = bold
    run.font.size = Pt(size)
    return p


# ── SOP typography helpers ────────────────────────────────────────────


def _set_pBdr(
    p: Paragraph,
    position: str,
    color: str,
    *,
    size: int = 6,
    space: int = 4,
) -> None:
    """Apply a paragraph border edge. `size` is eighths of a point
    (6 = 0.75pt); `space` is the gap between border and text in pt."""
    pPr = p._element.get_or_add_pPr()
    pBdr = pPr.find(qn("w:pBdr"))
    if pBdr is None:
        pBdr = OxmlElement("w:pBdr")
        pPr.append(pBdr)
    edge = OxmlElement(f"w:{position}")
    edge.set(qn("w:val"), "single")
    edge.set(qn("w:sz"), str(size))
    edge.set(qn("w:space"), str(space))
    edge.set(qn("w:color"), color)
    pBdr.append(edge)


def _set_letter_spacing(run, twentieths: int) -> None:
    """Track-out runs by `twentieths` of a point. 40 = 2pt letter spacing."""
    rPr = run._element.get_or_add_rPr()
    spacing = OxmlElement("w:spacing")
    spacing.set(qn("w:val"), str(twentieths))
    rPr.append(spacing)


def _shade_cell(cell: _Cell, color: str) -> None:
    tcPr = cell._tc.get_or_add_tcPr()
    shd = OxmlElement("w:shd")
    shd.set(qn("w:val"), "clear")
    shd.set(qn("w:color"), "auto")
    shd.set(qn("w:fill"), color)
    tcPr.append(shd)


def _set_sop_default_style(doc: DocxDocument) -> None:
    """Cambria 11pt body, dark slate ink."""
    style = doc.styles["Normal"]
    style.font.name = SERIF
    style.font.size = Pt(11)
    style.font.color.rgb = RGBColor.from_string(INK)


def _section_heading(doc: DocxDocument, text: str) -> Paragraph:
    """Calibri 12pt bold, uppercase, letter-spaced, with thin bottom
    rule. Generous space before, kept with next so the heading never
    strands at the bottom of a page."""
    p = doc.add_paragraph()
    pf = p.paragraph_format
    pf.space_before = Pt(22)
    pf.space_after = Pt(8)
    pf.keep_with_next = True
    run = p.add_run(text.upper())
    run.font.name = SANS
    run.font.size = Pt(12)
    run.bold = True
    run.font.color.rgb = RGBColor.from_string(INK_DEEP)
    _set_letter_spacing(run, 40)  # 2pt tracking
    _set_pBdr(p, "bottom", RULE, size=4, space=6)
    return p


def _doc_subtitle(doc: DocxDocument, text: str) -> Paragraph:
    p = doc.add_paragraph()
    p.paragraph_format.space_after = Pt(2)
    run = p.add_run(text)
    run.font.name = SANS
    run.font.size = Pt(9)
    run.font.color.rgb = RGBColor.from_string(INK_MUTED)
    _set_letter_spacing(run, 60)
    return p


def _doc_title(doc: DocxDocument, text: str) -> Paragraph:
    p = doc.add_paragraph()
    p.paragraph_format.space_after = Pt(4)
    run = p.add_run(text)
    run.font.name = SERIF
    run.font.size = Pt(24)
    run.bold = True
    run.font.color.rgb = RGBColor.from_string(INK_DEEP)
    return p


def _doc_meta(doc: DocxDocument, text: str) -> Paragraph:
    p = doc.add_paragraph()
    p.paragraph_format.space_after = Pt(2)
    run = p.add_run(text)
    run.font.name = SANS
    run.font.size = Pt(9.5)
    run.font.color.rgb = RGBColor.from_string(INK_MUTED)
    return p


def _body_p(doc: DocxDocument, text: str) -> Paragraph:
    """Body paragraph — 11pt Cambria, 1.35 line height, space-after 6pt."""
    p = doc.add_paragraph()
    pf = p.paragraph_format
    pf.space_after = Pt(6)
    pf.line_spacing = 1.35
    run = p.add_run(text)
    run.font.name = SERIF
    run.font.size = Pt(11)
    run.font.color.rgb = RGBColor.from_string(INK)
    return p


def _control_p(doc: DocxDocument, text: str) -> Paragraph:
    """Tiny paragraph carrying a Jinja control tag. Minimised so the
    leftover whitespace after docxtpl strips the tag is negligible."""
    p = doc.add_paragraph()
    p.paragraph_format.space_before = Pt(0)
    p.paragraph_format.space_after = Pt(0)
    run = p.add_run(text)
    run.font.size = Pt(1)
    return p


def _table_header_cell(cell: _Cell, text: str) -> None:
    """Style a table header cell: Calibri bold 9pt all-caps, shaded."""
    _shade_cell(cell, SHADE)
    cell.vertical_alignment = WD_ALIGN_VERTICAL.CENTER
    p = cell.paragraphs[0]
    p.text = ""
    run = p.add_run(text.upper())
    run.font.name = SANS
    run.font.size = Pt(9)
    run.bold = True
    run.font.color.rgb = RGBColor.from_string(INK_DEEP)
    _set_letter_spacing(run, 30)


def _add_role_header_paragraph(doc: DocxDocument) -> Paragraph:
    """Template paragraph that the RichText role header lands in.
    Carries a bottom border and generous spacing; the RichText itself
    sets fonts/sizes/colors for the role name."""
    p = doc.add_paragraph()
    pf = p.paragraph_format
    pf.space_before = Pt(16)
    pf.space_after = Pt(10)
    pf.keep_with_next = True
    _set_pBdr(p, "bottom", RULE, size=4, space=6)
    return p


def _add_procedure_step_paragraph(doc: DocxDocument) -> Paragraph:
    """Template paragraph for a single procedure step. Hanging indent
    at 0.4" so the step number sits in the left margin and wrapped
    lines align under the step text. Tab stop at the indent so the
    \\t between number and step name lands flush."""
    p = doc.add_paragraph()
    pf = p.paragraph_format
    pf.left_indent = Inches(0.4)
    pf.first_line_indent = Inches(-0.4)
    pf.space_after = Pt(10)
    pf.line_spacing = 1.3
    pf.keep_together = True
    pf.tab_stops.add_tab_stop(Inches(0.4))
    return p


def _table_loop(
    table,
    header_cells: list[str],
    iterator: str,
    data_cells: list[str],
) -> None:
    """Wire up a docxtpl-style table loop. Header row gets styled cells;
    a {%tr for %} row, a data row, and a {%tr endfor %} row follow."""
    for cell, label in zip(table.rows[0].cells, header_cells):
        _table_header_cell(cell, label)
    for_row = table.add_row().cells
    for_row[0].text = iterator
    data_row = table.add_row().cells
    for cell, value in zip(data_row, data_cells):
        cell.text = value
        # Body cell typography
        for p in cell.paragraphs:
            for run in p.runs:
                run.font.name = SERIF
                run.font.size = Pt(10.5)
                run.font.color.rgb = RGBColor.from_string(INK)
    end_row = table.add_row().cells
    end_row[0].text = "{%tr endfor %}"


def build_sop(output_path: Path) -> None:
    """Production-grade SOP template — refined scientific editorial.

    Cambria body + Calibri labels, grayscale ink, real Word paragraph
    borders for section dividers (no Unicode rules), hanging-indent
    numbered procedure with a tab-aligned number column.
    """
    doc = Document()
    _set_sop_default_style(doc)

    section = doc.sections[0]
    section.top_margin = Inches(1.0)
    section.bottom_margin = Inches(1.0)
    section.left_margin = Inches(1.1)
    section.right_margin = Inches(1.1)

    # Page header — small uppercase tag with org / doc # / version.
    hdr = section.header.paragraphs[0]
    hdr.text = ""
    hdr_run = hdr.add_run(
        "{{ organization_name }}    "
        "{% if doc_number %}{{ doc_number }}    {% endif %}"
        "Version {{ version_number }}"
    )
    hdr_run.font.name = SANS
    hdr_run.font.size = Pt(8.5)
    hdr_run.font.color.rgb = RGBColor.from_string(INK_MUTED)
    _set_letter_spacing(hdr_run, 30)

    # Title block: tracked-out kicker, large serif title, meta sub-line,
    # project/org footer, then a hairline rule that separates the title
    # block from the document body.
    _doc_subtitle(
        doc,
        "{% if doc_number %}{{ doc_number }}  ·  {% endif %}"
        "STANDARD OPERATING PROCEDURE",
    )
    _doc_title(doc, "{{ protocol_name }}")
    _doc_meta(
        doc,
        "Version {{ version_number }}  ·  "
        "Effective {{ effective_date }}  ·  "
        "Supersedes {{ supersedes_date }}",
    )
    _doc_meta(doc, "{{ project_name }}  ·  {{ organization_name }}")
    rule = doc.add_paragraph()
    rule.paragraph_format.space_before = Pt(6)
    rule.paragraph_format.space_after = Pt(4)
    rule.add_run("").font.size = Pt(1)
    _set_pBdr(rule, "bottom", RULE, size=4, space=2)

    # Gated text sections — Purpose / Scope / Definitions / References.
    for heading, gate, body in [
        ("Purpose", "purpose", "{{ purpose }}"),
        ("Scope", "scope", "{{ scope }}"),
        ("Definitions", "definitions", "{{ definitions }}"),
        ("References", "references", "{{ references }}"),
    ]:
        _control_p(doc, "{%p if " + gate + " %}")
        _section_heading(doc, heading)
        _body_p(doc, body)
        _control_p(doc, "{%p endif %}")

    # Revision History table.
    _control_p(doc, "{%p if revision_history %}")
    _section_heading(doc, "Revision History")
    _table_loop(
        doc.add_table(rows=1, cols=4),
        header_cells=["Version", "Date", "Author", "Changes"],
        iterator="{%tr for rev in revision_history %}",
        data_cells=[
            "{{ rev.version_number }}",
            "{{ rev.created_at }}",
            "{{ rev.created_by }}",
            "{{ rev.change_summary }}",
        ],
    )
    _control_p(doc, "{%p endif %}")

    # Responsibilities table.
    _control_p(doc, "{%p if responsibilities %}")
    _section_heading(doc, "Responsibilities")
    _table_loop(
        doc.add_table(rows=1, cols=2),
        header_cells=["Role", "Responsibility summary"],
        iterator="{%tr for resp in responsibilities %}",
        data_cells=["{{ resp.role_name }}", "{{ resp.step_summary }}"],
    )
    _control_p(doc, "{%p endif %}")

    # Equipment summary table.
    _control_p(doc, "{%p if equipment_summary %}")
    _section_heading(doc, "Equipment")
    _table_loop(
        doc.add_table(rows=1, cols=3),
        header_cells=["ID", "Name", "Description"],
        iterator="{%tr for eq in equipment_summary %}",
        data_cells=[
            "{{ eq.local_id }}",
            "{{ eq.name }}",
            "{{ eq.description }}",
        ],
    )
    _control_p(doc, "{%p endif %}")

    # Procedure — always present, branches on is_role_based. The step
    # number, name, description, and meta lines are pre-composed in
    # template_engine._build_sop_body so the RichText carries its own
    # typography; the template paragraphs only contribute layout
    # (hanging indent + tab stop) and the role-header divider rule.
    _section_heading(doc, "Procedure")
    _control_p(doc, "{%p if is_role_based %}")
    _control_p(doc, "{%p for role in roles %}")
    role_hdr = _add_role_header_paragraph(doc)
    role_hdr.add_run("{{r role.sop_header }}")
    _control_p(doc, "{%p for step in role.sop_steps %}")
    step_p = _add_procedure_step_paragraph(doc)
    step_p.add_run("{{r step.sop_body }}")
    _control_p(doc, "{%p endfor %}")
    _control_p(doc, "{%p endfor %}")
    _control_p(doc, "{%p else %}")
    _control_p(doc, "{%p for step in steps %}")
    flat_step_p = _add_procedure_step_paragraph(doc)
    flat_step_p.add_run("{{r step.sop_body }}")
    _control_p(doc, "{%p endfor %}")
    _control_p(doc, "{%p endif %}")

    # Approval block.
    _section_heading(doc, "Approval")
    _control_p(doc, "{%p if approval %}")
    _body_p(
        doc,
        "Approved by: {{ approval.actor_name }} "
        "({{ approval.actor_role }})",
    )
    _body_p(doc, "Date: {{ approval.approved_at }}")
    _control_p(doc, "{%p if approval.signature_statement %}")
    _body_p(doc, "Statement: {{ approval.signature_statement }}")
    _control_p(doc, "{%p endif %}")
    _control_p(doc, "{%p else %}")
    _body_p(doc, "{{ unapproved_warning }}")
    _control_p(doc, "{%p endif %}")

    doc.save(output_path)


def build_batch_record(output_path: Path) -> None:
    """Build the production-grade Batch Record .docx template.

    The template uses docxtpl Jinja2 syntax for dynamic content.
    Conditional columns (Reviewer, Scheduled, Actual Start, Actual End) are
    always present in the table structure; their cell content renders as
    an empty string when the gating flag is False via the inline
    ``{{ value if flag else '' }}`` form.  ``{%tc if %}`` was avoided because
    it cannot be nested inside an outer ``{%p for %}`` block without
    confusing docxtpl's directive scanner.
    """
    doc = Document()
    section = doc.sections[0]
    section.top_margin = Cm(2.0)
    section.bottom_margin = Cm(2.0)
    section.left_margin = Cm(2.0)
    section.right_margin = Cm(2.0)

    hdr = section.header.paragraphs[0]
    hdr.text = (
        "{{ organization_name }}    "
        "{% if doc_number %}{{ doc_number }}{% endif %}    "
        "Run: {{ run_name }}    "
        "{% if lot_number %}Lot: {{ lot_number }}{% endif %}"
    )

    # Title
    _p(doc, "{{ protocol_name }} — Batch Record", bold=True, size=18)
    _p(doc, "{% if lot_number %}Lot Number: {{ lot_number }}{% endif %}")
    _p(doc, "{% if batch_number %}Batch Number: {{ batch_number }}{% endif %}")
    _p(doc, "Run: {{ run_name }}  |  Status: {{ run_status }}")
    _p(doc, "Started: {{ started_at }}  |  Completed: {{ completed_at }}")
    _p(doc, "Project: {{ project_name }}  |  Organization: {{ organization_name }}")
    _p(
        doc,
        "SOP Reference: {{ doc_number }} v{{ version_number }}"
        " (effective {{ effective_date }})",
    )

    # Equipment Used (BR-specific)
    _p(doc, "{%p if equipment_summary %}", size=1)
    _p(doc, "Equipment Used", bold=True, size=14)
    e_table = doc.add_table(rows=1, cols=3)
    e_table.style = "Light Grid Accent 1"
    e_table.rows[0].cells[0].text = "ID"
    e_table.rows[0].cells[1].text = "Name"
    e_table.rows[0].cells[2].text = "Description"
    e_for = e_table.add_row().cells
    e_for[0].text = "{%tr for eq in equipment_summary %}"
    e_data = e_table.add_row().cells
    e_data[0].text = "{{ eq.local_id }}"
    e_data[1].text = "{{ eq.name }}"
    e_data[2].text = "{{ eq.description }}"
    e_end = e_table.add_row().cells
    e_end[0].text = "{%tr endfor %}"
    _p(doc, "{%p endif %}", size=1)

    # Procedure Execution.  Two tables, one per branch of is_role_based.
    # Inside each table, `{%tr for ... %}` lives in its own row (first cell
    # only) and `{%tr endfor %}` lives in a separate end row.  Header row is
    # static.  Conditional columns (Reviewer, Scheduled, Actual Start/End)
    # are always present in the table structure; their data-cell content
    # renders blank when the gating flag is False via inline
    # `{{ value if flag else '' }}`.
    _p(doc, "Procedure Execution", bold=True, size=14)

    def _build_proc_table(
        step_iter_expr: str,
        role_header_paragraph: str | None = None,
    ) -> None:
        """Build a 9-column procedure-execution table.

        `step_iter_expr` is the Jinja expression placed inside the `{%tr for%}`
        directive, e.g. "step in steps" or "step in role.steps".
        `role_header_paragraph` is an optional paragraph rendered above the
        table (used for the role-based branch).

        Conditional columns (Reviewer, Scheduled, Actual Start/End) are always
        rendered as columns; cells use the inline `{{ value if flag else '' }}`
        form so the column is blank when the gating flag is False.  We avoid
        `{%tc if %}` here because it cannot be reliably nested inside the
        outer `{%p for role in roles %}` paragraph wrapper.
        """
        if role_header_paragraph:
            _p(doc, role_header_paragraph)
        tbl = doc.add_table(rows=1, cols=9)
        tbl.style = "Light Grid Accent 1"
        hdr = tbl.rows[0].cells
        hdr[0].text = "Step"
        hdr[1].text = "Description"
        hdr[2].text = "Value"
        hdr[3].text = "Operator"
        hdr[4].text = "Reviewer"
        hdr[5].text = "Scheduled"
        hdr[6].text = "Actual Start"
        hdr[7].text = "Actual End"
        hdr[8].text = "Notes"
        # loop-open row — sole tag in first cell; other cells empty
        for_row = tbl.add_row().cells
        for_row[0].text = "{%tr for " + step_iter_expr + " %}"
        # data row
        data_row = tbl.add_row().cells
        data_row[0].text = "{{ step.name }}"
        data_row[1].text = "{{ step.description }}"
        data_row[2].text = "{{r step.value_display }}"
        data_row[3].text = "{{ step.initials }}"
        data_row[4].text = "{{ step.reviewer_initials if reviewer_enabled else '' }}"
        data_row[5].text = "{{ step.scheduled_at if time_enabled else '' }}"
        data_row[6].text = "{{ step.actual_started_at if time_enabled else '' }}"
        data_row[7].text = "{{ step.actual_completed_at if time_enabled else '' }}"
        data_row[8].text = "{{ step.notes_text }}"
        # loop-close row
        end_row = tbl.add_row().cells
        end_row[0].text = "{%tr endfor %}"

    # Role-based branch: outer {%p for role %} loop wraps a per-role header
    # paragraph + a procedure table iterating role.steps.
    _p(doc, "{%p if is_role_based %}")
    _p(doc, "{%p for role in roles %}")
    _build_proc_table("step in role.steps", role_header_paragraph="{{r role.br_header }}")
    _p(doc, "{%p endfor %}")
    _p(doc, "{%p else %}")
    # Flat branch: single table iterating steps.
    _build_proc_table("step in steps")
    _p(doc, "{%p endif %}")

    # Deviations
    _p(doc, "{%p if deviations %}", size=1)
    _p(doc, "Deviations", bold=True, size=14)
    d_table = doc.add_table(rows=1, cols=3)
    d_table.style = "Light Grid Accent 1"
    d_table.rows[0].cells[0].text = "When"
    d_table.rows[0].cells[1].text = "Author"
    d_table.rows[0].cells[2].text = "Note"
    d_for = d_table.add_row().cells
    d_for[0].text = "{%tr for d in deviations %}"
    d_data = d_table.add_row().cells
    d_data[0].text = "{{ d.created_at }}"
    d_data[1].text = "{{ d.author_name }}"
    d_data[2].text = "{{ d.content }}"
    d_end = d_table.add_row().cells
    d_end[0].text = "{%tr endfor %}"
    _p(doc, "{%p endif %}", size=1)

    # Notes
    _p(doc, "{%p if notes %}", size=1)
    _p(doc, "Notes", bold=True, size=14)
    _p(doc, "{%p for note in notes %}", size=1)
    _p(doc, "[{{ note.created_at }}] {{ note.author_name }}: {{ note.content }}")
    _p(doc, "{%p endfor %}", size=1)
    _p(doc, "{%p endif %}", size=1)

    # Figures
    _p(doc, "{%p if figures %}", size=1)
    _p(doc, "Figures", bold=True, size=14)
    _p(doc, "{%p for fig in figures %}", size=1)
    _p(doc, "Figure {{ fig.number }}: {{ fig.filename }}")
    _p(doc, "{{ fig.image }}")
    _p(doc, "{%p endfor %}", size=1)
    _p(doc, "{%p endif %}", size=1)

    # Non-image attachments
    _p(doc, "{%p if non_image_attachments %}", size=1)
    _p(doc, "Attachments", bold=True, size=14)
    _p(doc, "{%p for att in non_image_attachments %}", size=1)
    _p(doc, "{{ att.filename }} ({{ att.uploaded_at }})")
    _p(doc, "{%p endfor %}", size=1)
    _p(doc, "{%p endif %}", size=1)

    # Approval
    _p(doc, "Approval", bold=True, size=14)
    _p(doc, "{%p if approval %}", size=1)
    _p(
        doc,
        "Approved by: {{ approval.actor_name }} ({{ approval.actor_role }})"
        " on {{ approval.approved_at }}",
    )
    _p(doc, "{%p else %}", size=1)
    _p(doc, "{{ unapproved_warning }}")
    _p(doc, "{%p endif %}", size=1)
    _p(doc, "{%p if approval_history and approval_history|length > 1 %}", size=1)
    _p(doc, "Approval history:")
    _p(doc, "{%p for event in approval_history %}", size=1)
    _p(
        doc,
        "{{ event.action }} by {{ event.actor_name }} on {{ event.created_at }}",
    )
    _p(doc, "{%p endfor %}", size=1)
    _p(doc, "{%p endif %}", size=1)

    doc.save(output_path)


if __name__ == "__main__":
    TEMPLATES_DIR.mkdir(parents=True, exist_ok=True)
    sop = TEMPLATES_DIR / "sop_default.docx"
    br = TEMPLATES_DIR / "batch_record_default.docx"
    build_sop(sop)
    build_batch_record(br)
    print(f"wrote {sop}")
    print(f"wrote {br}")
