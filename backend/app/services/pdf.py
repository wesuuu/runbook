"""PDF generation service using fpdf2.

Provides SOP (numbered instruction-manual style) and batch record
(tabular) PDF generation from extracted graph data.
"""

import re
from datetime import date
from typing import Any

from fpdf import FPDF


class _SopPdf(FPDF):
    """Custom FPDF subclass for SOP documents."""

    def __init__(self) -> None:
        super().__init__(orientation="P", unit="mm", format="Letter")
        self.set_auto_page_break(auto=True, margin=25)

    def header(self) -> None:
        self.set_font("Helvetica", "I", 9)
        self.set_text_color(120, 120, 120)
        self.cell(0, 6, "STANDARD OPERATING PROCEDURE", align="C")
        self.ln(10)

    def footer(self) -> None:
        self.set_y(-20)
        self.set_font("Helvetica", "", 8)
        self.set_text_color(150, 150, 150)
        self.cell(0, 5, f"Page {self.page_no()}/{{nb}}", align="C")


class _BatchPdf(FPDF):
    """Custom FPDF subclass for batch record documents."""

    def __init__(self) -> None:
        super().__init__(orientation="P", unit="mm", format="Letter")
        self.set_auto_page_break(auto=True, margin=25)

    def header(self) -> None:
        self.set_font("Helvetica", "I", 9)
        self.set_text_color(120, 120, 120)
        self.cell(0, 6, "BATCH RECORD", align="C")
        self.ln(10)

    def footer(self) -> None:
        self.set_y(-20)
        self.set_font("Helvetica", "", 8)
        self.set_text_color(150, 150, 150)
        self.cell(0, 5, f"Page {self.page_no()}/{{nb}}", align="C")


def _get_param_title(key: str, param_schema: dict[str, Any] | None) -> str:
    """Get a human-readable title for a parameter key.

    Uses the title field from the JSON Schema if available,
    otherwise converts snake_case to Title Case.
    """
    if param_schema:
        props = param_schema.get("properties", {})
        prop = props.get(key, {})
        if prop.get("title"):
            return prop["title"]
    # Fallback: convert snake_case to readable
    return key.replace("_", " ").replace("  ", " ").strip().title()


def _format_value(val: Any) -> str:
    """Format a parameter value for human-readable display."""
    if isinstance(val, bool):
        return "Yes" if val else "No"
    if isinstance(val, float):
        # Drop unnecessary trailing zeros
        return f"{val:g}"
    if isinstance(val, list):
        return ", ".join(str(v) for v in val)
    return str(val)


def _render_template(
    template: str,
    params: dict[str, Any] | None,
) -> str:
    """Substitute ``{{key}}`` placeholders with formatted param values.

    Uses ``_format_value`` for consistent formatting.  Unfilled params
    (missing key or None/empty value) keep the raw ``{{key}}`` syntax
    so the user can see what still needs filling.
    """
    if not params:
        return template

    def _replace(match: re.Match) -> str:
        key = match.group(1)
        val = params.get(key)
        if val is None or val == "" or val == []:
            return match.group(0)  # keep raw placeholder
        return _format_value(val)

    return re.sub(r"\{\{(\w+)\}\}", _replace, template)


def _build_param_sentence(
    params: dict[str, Any] | None,
    param_schema: dict[str, Any] | None,
) -> str:
    """Build a single prose sentence describing the parameters.

    Example: "Use 500 mL volume, mix for 45 minutes at 200 RPM,
    targeting a pH of 7.4."
    """
    if not params:
        return ""

    filled = {
        k: v for k, v in params.items()
        if v is not None and v != "" and v != []
    }
    if not filled:
        return ""

    parts = []
    for key, val in filled.items():
        title = _get_param_title(key, param_schema)
        parts.append(f"{title}: {_format_value(val)}")

    if len(parts) == 1:
        return parts[0] + "."
    return ", ".join(parts[:-1]) + ", and " + parts[-1] + "."


def generate_sop_pdf(
    protocol_name: str,
    run_name: str | None,
    roles_with_steps: list[dict[str, Any]],
    protocol_description: str = "",
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

    Returns:
        PDF file contents as bytes.
    """
    pdf = _SopPdf()
    pdf.alias_nb_pages()
    pdf.add_page()

    today = date.today().strftime("%B %d, %Y")
    multi_role = len(roles_with_steps) > 1
    w = pdf.epw  # effective page width

    # ── Title ──
    pdf.set_font("Helvetica", "B", 18)
    pdf.set_text_color(15, 23, 42)
    pdf.cell(0, 10, "Standard Operating Procedure", align="C")
    pdf.ln(12)

    # ── Document info ──
    half = w / 2

    pdf.set_font("Helvetica", "B", 10)
    pdf.set_text_color(51, 65, 85)
    pdf.cell(half, 6, f"Protocol: {protocol_name}", align="L")
    pdf.set_font("Helvetica", "", 10)
    pdf.cell(half, 6, f"Date: {today}", align="R")
    pdf.ln(7)

    if run_name:
        pdf.set_font("Helvetica", "B", 10)
        pdf.set_text_color(51, 65, 85)
        pdf.cell(half, 6, f"Run: {run_name}", align="L")
        pdf.ln(7)

    # ── Protocol description ──
    if protocol_description:
        pdf.ln(2)
        pdf.set_font("Helvetica", "", 10)
        pdf.set_text_color(71, 85, 105)
        pdf.multi_cell(w, 5, protocol_description)
        pdf.ln(2)

    # Divider
    pdf.set_draw_color(200, 200, 200)
    pdf.line(pdf.l_margin, pdf.get_y(), pdf.l_margin + w, pdf.get_y())
    pdf.ln(6)

    # Check if roles are real named roles (swimlane-based) vs unnamed
    # process groups. Only force page breaks between named roles.
    has_named_roles = any(
        rd.get("role_name") for rd in roles_with_steps
    )

    # ── Steps by role ──
    step_counter = 0
    for role_idx, role_data in enumerate(roles_with_steps):
        role_name = role_data["role_name"]
        steps = role_data["steps"]

        # Page break between named roles only (not unnamed process groups)
        if role_idx > 0 and has_named_roles and role_name:
            pdf.add_page()

        # Role header (for multi-role docs with named roles)
        if multi_role and role_name and has_named_roles:
            pdf.set_font("Helvetica", "B", 14)
            pdf.set_text_color(15, 23, 42)
            pdf.cell(0, 8, role_name)
            pdf.ln(10)
            pdf.set_draw_color(200, 200, 200)
            pdf.line(pdf.l_margin, pdf.get_y(), pdf.l_margin + w, pdf.get_y())
            pdf.ln(6)

        # Numbered steps (continuous numbering across groups)
        for step in steps:
            step_counter += 1
            name = step.get("name", "Unnamed Step")
            description = step.get("description", "")
            params = step.get("params")
            param_schema = step.get("param_schema")
            duration = step.get("duration_min")

            # Step number and name
            pdf.set_font("Helvetica", "B", 11)
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
                pdf.set_font("Helvetica", "", 10)
                pdf.set_text_color(51, 65, 85)
                pdf.multi_cell(w - 8, 5, description)
                pdf.ln(2)

            # Parameters as a prose sentence (skip when templates
            # already inlined the values into the description)
            if not has_templates:
                param_text = _build_param_sentence(params, param_schema)
                if param_text:
                    pdf.set_x(pdf.l_margin + 8)
                    pdf.set_font("Helvetica", "", 10)
                    pdf.set_text_color(51, 65, 85)
                    pdf.multi_cell(w - 8, 5, param_text)
                    pdf.ln(2)

            # Duration as prose
            if duration:
                pdf.set_x(pdf.l_margin + 8)
                pdf.set_font("Helvetica", "I", 10)
                pdf.set_text_color(100, 116, 139)
                pdf.cell(0, 5, f"Allow {duration} minutes for this step.")
                pdf.ln(4)

            pdf.ln(3)

    # ── Signature block ──
    pdf.ln(6)
    pdf.set_draw_color(200, 200, 200)
    pdf.line(pdf.l_margin, pdf.get_y(), pdf.l_margin + w, pdf.get_y())
    pdf.ln(6)

    pdf.set_font("Helvetica", "B", 11)
    pdf.set_text_color(15, 23, 42)
    pdf.cell(0, 6, "Approvals")
    pdf.ln(10)

    sig_w = (w - 10) / 2
    y_start = pdf.get_y()

    pdf.set_font("Helvetica", "", 9)
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


def _wrap_text(pdf: FPDF, text: str, max_width: float) -> list[str]:
    """Split text into lines that fit within max_width."""
    if not text:
        return [""]
    if pdf.get_string_width(text) <= max_width:
        return [text]
    words = text.split()
    lines: list[str] = []
    current = ""
    for word in words:
        test = f"{current} {word}".strip() if current else word
        if pdf.get_string_width(test) <= max_width:
            current = test
        else:
            if current:
                lines.append(current)
            # If a single word is too wide, add it anyway (will be truncated)
            current = word
    if current:
        lines.append(current)
    return lines if lines else [""]


def _draw_table_row(
    pdf: FPDF,
    col_widths: list[float],
    row_vals: list[str],
    line_h: float = 4,
    min_h: float = 8,
    aligns: list[str] | None = None,
    fill: bool = False,
) -> None:
    """Draw a table row with text wrapping fully contained in cells."""
    if aligns is None:
        aligns = ["C"] * len(row_vals)

    pad = 1  # 1mm internal padding

    # Pre-wrap all cells to determine the row height
    wrapped: list[list[str]] = []
    max_lines = 1
    for i, val in enumerate(row_vals):
        lines = _wrap_text(pdf, val, col_widths[i] - pad * 2)
        wrapped.append(lines)
        max_lines = max(max_lines, len(lines))
    row_h = max(min_h, max_lines * line_h + pad * 2)

    x_start = pdf.l_margin
    y_start = pdf.get_y()

    # Page break if row doesn't fit
    page_bottom = pdf.h - pdf.b_margin
    if y_start + row_h > page_bottom:
        pdf.add_page()
        y_start = pdf.get_y()

    # Draw cell borders (and optional fill), then render text line by line
    for i, lines in enumerate(wrapped):
        x = x_start + sum(col_widths[:i])
        cell_w = col_widths[i]

        # Border + fill
        if fill:
            pdf.rect(x, y_start, cell_w, row_h, style="DF")
        else:
            pdf.rect(x, y_start, cell_w, row_h, style="D")

        # Render each wrapped line using cell() — no cursor side-effects
        for j, line in enumerate(lines):
            pdf.set_xy(x + pad, y_start + pad + j * line_h)
            pdf.cell(cell_w - pad * 2, line_h, line, border=0, align=aligns[i])

    pdf.set_xy(x_start, y_start + row_h)


def generate_batch_record_pdf(
    protocol_name: str,
    run_name: str,
    roles: list[dict[str, Any]],
    steps: list[dict[str, Any]],
    filled: bool = False,
    execution_data: dict[str, Any] | None = None,
) -> bytes:
    """Generate a batch record PDF in tabular format.

    Args:
        protocol_name: Name of the protocol.
        run_name: Name of the run.
        roles: List of dicts with keys: id, name, color.
        steps: List of dicts with keys:
            id, name, description, role_name, params, duration_min.
        filled: If True, fill values from execution_data.
        execution_data: Dict mapping step ID to execution data.

    Returns:
        PDF file contents as bytes.
    """
    pdf = _BatchPdf()
    pdf.alias_nb_pages()
    pdf.add_page()

    today = date.today().strftime("%B %d, %Y")
    w = pdf.epw

    # Title
    pdf.set_font("Helvetica", "B", 18)
    pdf.set_text_color(15, 23, 42)
    pdf.cell(0, 10, "Batch Record", align="C")
    pdf.ln(14)

    # Header info
    half = w / 2
    pdf.set_font("Helvetica", "B", 10)
    pdf.set_text_color(51, 65, 85)
    pdf.cell(half, 6, f"Run: {run_name}", align="L")
    pdf.cell(half, 6, f"Date: {today}", align="R")
    pdf.ln(7)
    pdf.cell(half, 6, f"Protocol: {protocol_name}", align="L")
    pdf.cell(half, 6, "Lot/Batch #: _______________", align="R")
    pdf.ln(14)

    # Determine if any step has a real role
    has_roles = any(
        s.get("role_name") and s["role_name"] not in ("", "--", "Unassigned")
        for s in steps
    )

    # Build columns dynamically — omit Role if no roles
    if has_roles:
        col_widths = [
            w * 0.05,   # #
            w * 0.13,   # Role
            w * 0.17,   # Step Name
            w * 0.30,   # Description
            w * 0.20,   # Value/Result
            w * 0.15,   # Initials
        ]
        headers = ["#", "Role", "Step", "Description", "Value / Result",
                   "Initials"]
        header_aligns = ["C"] * 6
    else:
        col_widths = [
            w * 0.05,   # #
            w * 0.20,   # Step Name
            w * 0.40,   # Description
            w * 0.20,   # Value/Result
            w * 0.15,   # Initials
        ]
        headers = ["#", "Step", "Description", "Value / Result",
                   "Initials"]
        header_aligns = ["C"] * 5

    pdf.set_fill_color(30, 41, 59)
    pdf.set_text_color(255, 255, 255)
    pdf.set_font("Helvetica", "B", 8)

    _draw_table_row(
        pdf, col_widths, headers,
        line_h=4, min_h=8,
        aligns=header_aligns, fill=True,
    )

    # Table rows
    pdf.set_text_color(51, 65, 85)
    pdf.set_font("Helvetica", "", 8)
    pdf.set_draw_color(200, 200, 200)

    exec_data = execution_data or {}

    for idx, step in enumerate(steps, start=1):
        step_id = step.get("id", "")
        row_data = exec_data.get(step_id, {}) if filled else {}

        # Build description: use step description + param summary
        desc = step.get("description", "") or ""
        has_templates = desc and "{{" in desc
        if has_templates:
            desc = _render_template(desc, step.get("params"))

        if has_templates:
            full_desc = desc or "--"
        else:
            param_summary = _build_param_sentence(
                step.get("params"), step.get("param_schema"),
            )
            if desc and param_summary:
                full_desc = f"{desc} {param_summary}"
            else:
                full_desc = desc or param_summary or "--"

        if has_roles:
            row_vals = [
                str(idx),
                step.get("role_name", "") or "",
                step.get("name", "--"),
                full_desc,
                row_data.get("value", "") if filled else "",
                row_data.get("initials", "") if filled else "",
            ]
            aligns = ["C", "C", "L", "L", "C", "C"]
        else:
            row_vals = [
                str(idx),
                step.get("name", "--"),
                full_desc,
                row_data.get("value", "") if filled else "",
                row_data.get("initials", "") if filled else "",
            ]
            aligns = ["C", "L", "L", "C", "C"]

        _draw_table_row(
            pdf, col_widths, row_vals,
            line_h=4, min_h=8, aligns=aligns,
        )

    pdf.ln(12)

    # Role sign-off section (only if roles exist)
    if roles:
        pdf.set_font("Helvetica", "B", 11)
        pdf.set_text_color(15, 23, 42)
        pdf.cell(0, 7, "Role Sign-Off")
        pdf.ln(10)

        pdf.set_font("Helvetica", "", 9)
        pdf.set_text_color(51, 65, 85)

        for role in roles:
            role_name = role.get("name", "Unknown")
            pdf.set_font("Helvetica", "B", 9)
            pdf.cell(0, 6, role_name)
            pdf.ln(12)
            y = pdf.get_y()
            pdf.line(pdf.l_margin, y, pdf.l_margin + 80, y)
            pdf.ln(2)
            pdf.set_font("Helvetica", "", 7)
            pdf.set_text_color(100, 100, 100)
            pdf.cell(0, 4, "Signature / Date")
            pdf.ln(8)
            pdf.set_text_color(51, 65, 85)

    return bytes(pdf.output())
