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
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.shared import Cm, Pt
from docx.text.paragraph import Paragraph

REPO_ROOT = Path(__file__).resolve().parent.parent
TEMPLATES_DIR = REPO_ROOT / "backend/app/services/documents/templates"


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


def build_sop(output_path: Path) -> None:
    doc = Document()
    section = doc.sections[0]
    section.top_margin = Cm(2.0)
    section.bottom_margin = Cm(2.0)
    section.left_margin = Cm(2.0)
    section.right_margin = Cm(2.0)

    # Header (repeats on every page)
    hdr = section.header.paragraphs[0]
    hdr.text = (
        "{{ organization_name }}"
        "    {% if doc_number %}{{ doc_number }}{% endif %}"
        "    Version {{ version_number }}"
    )

    # Title block (always rendered)
    _p(doc, "{{ protocol_name }}", bold=True, size=18)
    _p(doc, "{% if doc_number %}Document #: {{ doc_number }}{% endif %}")
    _p(
        doc,
        "Version {{ version_number }}"
        "  |  Effective: {{ effective_date }}"
        "  |  Supersedes: {{ supersedes_date }}",
    )
    _p(doc, "{{ project_name }}  |  {{ organization_name }}")

    # Gated text sections — use {%p if/endif %} so docxtpl removes the
    # control paragraph entirely (no blank line artifact).
    for heading, gate, body in [
        ("Purpose", "purpose", "{{ purpose }}"),
        ("Scope", "scope", "{{ scope }}"),
        ("Definitions", "definitions", "{{ definitions }}"),
        ("References", "references", "{{ references }}"),
    ]:
        _p(doc, "{%p if " + gate + " %}", size=1)
        _p(doc, heading, bold=True, size=14)
        _p(doc, body)
        _p(doc, "{%p endif %}", size=1)

    # Revision History table (gated).
    # {%tr for %} and {%tr endfor %} MUST be in separate rows (each as the
    # sole tag in the first cell); docxtpl's regex strips the whole row when
    # it finds a {%tr ...%} tag.
    _p(doc, "{%p if revision_history %}", size=1)
    _p(doc, "Revision History", bold=True, size=14)
    table = doc.add_table(rows=1, cols=4)
    table.style = "Light Grid Accent 1"
    hdr_row = table.rows[0].cells
    hdr_row[0].text = "Version"
    hdr_row[1].text = "Date"
    hdr_row[2].text = "Author"
    hdr_row[3].text = "Changes"
    # loop-open row — sole tag in first cell; other cells empty
    for_row = table.add_row().cells
    for_row[0].text = "{%tr for rev in revision_history %}"
    # data row
    data_row = table.add_row().cells
    data_row[0].text = "{{ rev.version_number }}"
    data_row[1].text = "{{ rev.created_at }}"
    data_row[2].text = "{{ rev.created_by }}"
    data_row[3].text = "{{ rev.change_summary }}"
    # loop-close row
    end_row = table.add_row().cells
    end_row[0].text = "{%tr endfor %}"
    _p(doc, "{%p endif %}", size=1)

    # Responsibilities table (gated)
    _p(doc, "{%p if responsibilities %}", size=1)
    _p(doc, "Responsibilities", bold=True, size=14)
    r_table = doc.add_table(rows=1, cols=2)
    r_table.style = "Light Grid Accent 1"
    r_table.rows[0].cells[0].text = "Role"
    r_table.rows[0].cells[1].text = "Responsibility summary"
    r_for = r_table.add_row().cells
    r_for[0].text = "{%tr for resp in responsibilities %}"
    r_data = r_table.add_row().cells
    r_data[0].text = "{{ resp.role_name }}"
    r_data[1].text = "{{ resp.step_summary }}"
    r_end = r_table.add_row().cells
    r_end[0].text = "{%tr endfor %}"
    _p(doc, "{%p endif %}", size=1)

    # Equipment summary table (gated)
    _p(doc, "{%p if equipment_summary %}", size=1)
    _p(doc, "Equipment", bold=True, size=14)
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

    # Procedure (always present; branches on is_role_based)
    # Use {%p if/for/endfor/endif %} for paragraph-level control flow.
    _p(doc, "Procedure", bold=True, size=14)
    _p(doc, "{%p if is_role_based %}")
    _p(doc, "{%p for role in roles %}")
    _p(doc, "{{r role.sop_header }}")
    _p(doc, "{%p for step in role.sop_steps %}")
    _p(doc, "{{r step.sop_body }}")
    _p(doc, "{%p endfor %}")
    _p(doc, "{%p endfor %}")
    _p(doc, "{%p else %}")
    _p(doc, "{%p for step in steps %}")
    _p(doc, "{{r step.sop_body }}")
    _p(doc, "{%p endfor %}")
    _p(doc, "{%p endif %}")

    # Approval block
    _p(doc, "Approval", bold=True, size=14)
    _p(doc, "{%p if approval %}")
    _p(doc, "Approved by: {{ approval.actor_name }} ({{ approval.actor_role }})")
    _p(doc, "Date: {{ approval.approved_at }}")
    _p(doc, "{%p if approval.signature_statement %}")
    _p(doc, "Statement: {{ approval.signature_statement }}")
    _p(doc, "{%p endif %}")
    _p(doc, "{%p else %}")
    _p(doc, "{{ unapproved_warning }}")
    _p(doc, "{%p endif %}")

    doc.save(output_path)


if __name__ == "__main__":
    TEMPLATES_DIR.mkdir(parents=True, exist_ok=True)
    sop = TEMPLATES_DIR / "sop_default.docx"
    build_sop(sop)
    print(f"wrote {sop}")
