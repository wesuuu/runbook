"""SOP (Standard Operating Procedure) PDF generator.

Produces a numbered instruction-manual style PDF from extracted
graph data (roles_with_steps).
"""

from typing import Any

from fpdf import FPDF

from app.services.pdf_base import (
    _resolve_format,
    _fs,
    _rs,
    _render_template,
    _build_param_sentence,
)


class _SopPdf(FPDF):
    """Custom FPDF subclass for SOP documents."""

    def __init__(
        self,
        font_family: str = "Helvetica",
        last_modified: str = "",
        version_label: str = "",
    ) -> None:
        super().__init__(orientation="P", unit="mm", format="Letter")
        self.set_auto_page_break(auto=True, margin=25)
        self._ff = font_family
        self._last_modified = last_modified
        self._version_label = version_label

    def header(self) -> None:
        w = self.epw
        self.set_font(self._ff, "I", 9)
        self.set_text_color(120, 120, 120)
        # Left: "STANDARD OPERATING PROCEDURE"
        self.cell(w / 2, 6, "STANDARD OPERATING PROCEDURE", align="L")
        # Right: version + date
        right_parts: list[str] = []
        if self._version_label:
            right_parts.append(self._version_label)
        if self._last_modified:
            right_parts.append(self._last_modified)
        self.cell(w / 2, 6, "  |  ".join(right_parts), align="R")
        self.ln(10)

    def footer(self) -> None:
        self.set_y(-20)
        self.set_font(self._ff, "", 8)
        self.set_text_color(150, 150, 150)
        self.cell(0, 5, f"Page {self.page_no()}/{{nb}}", align="C")


def generate_sop_pdf(
    protocol_name: str,
    run_name: str | None,
    roles_with_steps: list[dict[str, Any]],
    protocol_description: str = "",
    format_options: dict[str, Any] | None = None,
    version_number: int | None = None,
    last_modified: str | None = None,
) -> bytes:
    """Generate a numbered instruction-manual style SOP PDF.

    Args:
        protocol_name: Name of the protocol.
        run_name: Optional run name (None for protocol preview).
        roles_with_steps: List of dicts, each with:
            - role_name: str (empty string if no roles)
            - steps: list of dicts with keys:
                name, description, params, param_schema, duration_min
        protocol_description: Optional description of the protocol.
        format_options: Optional dict overriding PDF formatting defaults.
        version_number: Optional protocol version number.
        last_modified: Optional last-modified date string.

    Returns:
        PDF file contents as bytes.
    """
    fmt = _resolve_format(format_options)
    ff = fmt["font_family"]
    fs = _fs(fmt)
    rs = _rs(fmt)
    hc = fmt["header_color"]

    version_label = f"v{version_number}" if version_number else ""
    modified_str = last_modified or ""

    pdf = _SopPdf(
        font_family=ff,
        last_modified=modified_str,
        version_label=version_label,
    )
    pdf.alias_nb_pages()
    pdf.add_page()

    multi_role = len(roles_with_steps) > 1
    w = pdf.epw  # effective page width

    # ── Title: protocol name, centered ──
    pdf.set_font(ff, "B", fs["title"])
    pdf.set_text_color(15, 23, 42)
    pdf.cell(0, 10, protocol_name, align="C")
    pdf.ln(10)

    if run_name:
        pdf.set_font(ff, "B", fs["body"])
        pdf.set_text_color(51, 65, 85)
        pdf.cell(0, 6, f"Run: {run_name}", align="C")
        pdf.ln(7)

    # ── Protocol description ──
    if protocol_description:
        pdf.ln(2)
        pdf.set_font(ff, "", fs["body"])
        pdf.set_text_color(71, 85, 105)
        pdf.multi_cell(w, 5, protocol_description)

    # Check if roles are real named roles (swimlane-based) vs unnamed
    # process groups. Only force page breaks between named roles.
    has_named_roles = any(
        rd.get("role_name") for rd in roles_with_steps
    )

    # Detect process sections (from processStart nodes)
    has_process_sections = any(
        rd.get("process_name") for rd in roles_with_steps
    )

    # Only draw the top divider when there are no process section headers
    # (process sections provide their own visual separation)
    if not has_process_sections:
        pdf.ln(2)
        pdf.set_draw_color(*hc)
        pdf.line(pdf.l_margin, pdf.get_y(), pdf.l_margin + w, pdf.get_y())
        pdf.ln(6)
    else:
        pdf.ln(4)

    # ── Steps by role ──
    step_counter = 0
    for role_idx, role_data in enumerate(roles_with_steps):
        role_name = role_data["role_name"]
        steps = role_data["steps"]
        process_name = role_data.get("process_name", "")
        process_desc = role_data.get("process_description", "")

        # Page break between sections
        if role_idx > 0 and (has_named_roles or has_process_sections):
            if role_name or process_name:
                pdf.add_page()

        # Process section header (from processStart node)
        if process_name:
            pdf.set_font(ff, "B", fs["section"])
            pdf.set_text_color(*hc)
            pdf.cell(0, 8, process_name)
            pdf.ln(8)
            if process_desc:
                pdf.set_font(ff, "", fs["body"])
                pdf.set_text_color(71, 85, 105)
                pdf.multi_cell(w, 5, process_desc)
            pdf.set_draw_color(*hc)
            pdf.line(pdf.l_margin, pdf.get_y(), pdf.l_margin + w, pdf.get_y())
            pdf.ln(4)
            # Reset step counter for each process section
            step_counter = 0
        elif multi_role and role_name and has_named_roles:
            # Role header (for multi-role docs with named roles)
            pdf.set_font(ff, "B", fs["section"])
            pdf.set_text_color(15, 23, 42)
            pdf.cell(0, 8, role_name)
            pdf.ln(10)
            pdf.set_draw_color(*hc)
            pdf.line(pdf.l_margin, pdf.get_y(), pdf.l_margin + w, pdf.get_y())
            pdf.ln(6)

        # Numbered steps (per-section when process sections, else continuous)
        for step in steps:
            step_counter += 1
            name = step.get("name", "Unnamed Step")
            description = step.get("description", "")
            params = step.get("params")
            param_schema = step.get("param_schema")
            duration = step.get("duration_min")

            # Step number and name
            pdf.set_font(ff, "B", fs["step_title"])
            pdf.set_text_color(15, 23, 42)
            pdf.cell(0, 6, f"{step_counter}. {name}")
            pdf.ln(7)

            # Render template placeholders in description
            has_templates = description and "{{" in description
            if has_templates:
                description = _render_template(description, params)

            # Description as prose paragraph
            if description:
                pdf.set_x(pdf.l_margin + 8)
                pdf.set_font(ff, "", fs["body"])
                pdf.set_text_color(51, 65, 85)
                pdf.multi_cell(w - 8, 5, description)
                pdf.ln(2)

            # Parameters as a prose sentence (skip when templates
            # already inlined the values into the description)
            if not has_templates:
                param_text = _build_param_sentence(params, param_schema)
                if param_text:
                    pdf.set_x(pdf.l_margin + 8)
                    pdf.set_font(ff, "", fs["body"])
                    pdf.set_text_color(51, 65, 85)
                    pdf.multi_cell(w - 8, 5, param_text)
                    pdf.ln(2)

            # Duration as prose
            if duration:
                pdf.set_x(pdf.l_margin + 8)
                pdf.set_font(ff, "I", fs["body"])
                pdf.set_text_color(100, 116, 139)
                pdf.cell(0, 5, f"Allow {duration} minutes for this step.")
                pdf.ln(4)

            pdf.ln(rs["step_gap"])

    # ── Signature block ──
    pdf.ln(6)
    pdf.set_draw_color(200, 200, 200)
    pdf.line(pdf.l_margin, pdf.get_y(), pdf.l_margin + w, pdf.get_y())
    pdf.ln(6)

    pdf.set_font(ff, "B", fs["step_title"])
    pdf.set_text_color(15, 23, 42)
    pdf.cell(0, 6, "Approvals")
    pdf.ln(10)

    sig_w = (w - 10) / 2
    y_start = pdf.get_y()

    pdf.set_font(ff, "", 9)
    pdf.set_text_color(100, 100, 100)

    # Prepared by
    pdf.line(pdf.l_margin, y_start + 16, pdf.l_margin + sig_w - 5, y_start + 16)
    pdf.set_y(y_start + 18)
    pdf.set_x(pdf.l_margin)
    pdf.cell(sig_w, 5, "Prepared by (Name / Date)")

    # Reviewed by
    pdf.line(
        pdf.l_margin + sig_w + 10,
        y_start + 16,
        pdf.l_margin + 2 * sig_w + 5,
        y_start + 16,
    )
    pdf.set_y(y_start + 18)
    pdf.set_x(pdf.l_margin + sig_w + 10)
    pdf.cell(sig_w, 5, "Reviewed by (Name / Date)")

    return bytes(pdf.output())
