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
    # {{ loop.index }} prefixes each step with its 1-based ordinal — the
    # role-based inner loop restarts numbering per role, the flat loop
    # numbers sequentially across the whole procedure.
    _p(doc, "Procedure", bold=True, size=14)
    _p(doc, "{%p if is_role_based %}")
    _p(doc, "{%p for role in roles %}")
    _p(doc, "{{r role.sop_header }}")
    _p(doc, "{%p for step in role.sop_steps %}")
    _p(doc, "{{ loop.index }}. {{r step.sop_body }}")
    _p(doc, "{%p endfor %}")
    _p(doc, "{%p endfor %}")
    _p(doc, "{%p else %}")
    _p(doc, "{%p for step in steps %}")
    _p(doc, "{{ loop.index }}. {{r step.sop_body }}")
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
