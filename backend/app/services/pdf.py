"""PDF generation service using fpdf2.

Provides SOP (numbered instruction-manual style) and batch record
(tabular) PDF generation from extracted graph data.
"""

import re
from datetime import date
from typing import Any

from fpdf import FPDF

from app.services.fonts import FONTS_DIR


# ── Default format options ──

DEFAULT_FORMAT: dict[str, Any] = {
    "font_family": "Helvetica",
    "font_size": "medium",       # small | medium | large
    "header_color": [30, 41, 59],  # RGB for table header / section accents
    "row_spacing": "normal",     # compact | normal | relaxed
}

# Font-size presets: maps (size_name) → (body, step_title, section_title, doc_title)
_FONT_SIZES = {
    "small":  {"body": 8,  "step_title": 9,  "section": 12, "title": 16, "table": 7},
    "medium": {"body": 10, "step_title": 11, "section": 14, "title": 18, "table": 8},
    "large":  {"body": 12, "step_title": 13, "section": 16, "title": 20, "table": 10},
}

# Row-spacing presets: maps name → (line_h, min_row_h, step_gap)
_ROW_SPACING = {
    "compact":  {"line_h": 3.5, "min_row_h": 6,  "step_gap": 2},
    "normal":   {"line_h": 4,   "min_row_h": 8,  "step_gap": 3},
    "relaxed":  {"line_h": 5,   "min_row_h": 10, "step_gap": 5},
}


def _resolve_format(fmt: dict[str, Any] | None) -> dict[str, Any]:
    """Merge user format options with defaults."""
    resolved = dict(DEFAULT_FORMAT)
    if fmt:
        for k, v in fmt.items():
            if v is not None:
                resolved[k] = v
    return resolved


def _fs(fmt: dict[str, Any]) -> dict[str, int]:
    """Get font-size preset dict from format."""
    return _FONT_SIZES.get(fmt["font_size"], _FONT_SIZES["medium"])


def _rs(fmt: dict[str, Any]) -> dict[str, float]:
    """Get row-spacing preset dict from format."""
    return _ROW_SPACING.get(fmt["row_spacing"], _ROW_SPACING["normal"])


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


class _BatchPdf(FPDF):
    """Custom FPDF subclass for batch record documents."""

    def __init__(
        self,
        font_family: str = "Helvetica",
        protocol_title: str = "",
        version_label: str = "",
        last_modified: str = "",
    ) -> None:
        super().__init__(orientation="P", unit="mm", format="Letter")
        self.set_auto_page_break(auto=True, margin=25)
        self._ff = font_family
        self._protocol_title = protocol_title
        self._version_label = version_label
        self._last_modified = last_modified

    def header(self) -> None:
        w = self.epw
        self.set_font(self._ff, "I", 9)
        self.set_text_color(120, 120, 120)
        # Left: "BATCH RECORD: Protocol Title"
        header_left = "BATCH RECORD"
        if self._protocol_title:
            header_left = f"{header_left}: {self._protocol_title}"
        self.cell(w / 2, 6, header_left, align="L")
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


def _get_initials(display_name: str) -> str:
    """Derive initials from a display name.

    "John Smith" → "J.S."
    "Alice" → "A."
    "alice@example.com" → "A."
    """
    name = display_name.strip()
    if not name:
        return ""
    # If it looks like an email, use the local part
    if "@" in name:
        name = name.split("@")[0]
    parts = name.split()
    initials = ".".join(p[0].upper() for p in parts if p) + "."
    return initials


_CURSIVE_FONT_PATH = str(FONTS_DIR / "DancingScript-Regular.ttf")


def _draw_cursive_initials(
    pdf: FPDF,
    text: str,
    x: float,
    y: float,
    w: float,
    h: float,
    font_size: float = 12,
) -> None:
    """Render initials in cursive font, centered in the given cell area."""
    if not text:
        return
    saved_family = pdf.font_family
    saved_size = pdf.font_size_pt
    saved_style = pdf.font_style

    pdf.set_font("Cursive", "", font_size)
    pdf.set_xy(x, y + (h - font_size * 0.35) / 2)
    pdf.cell(w, font_size * 0.35, text, border=0, align="C")

    pdf.set_font(saved_family, saved_style, saved_size)


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


def _get_editable_params(
    param_schema: dict[str, Any] | None,
) -> list[tuple[str, dict[str, Any]]]:
    """Return editable (non x-ref-type) properties from a param schema."""
    if not param_schema:
        return []
    props = param_schema.get("properties", {})
    return [
        (key, prop) for key, prop in props.items()
        if not prop.get("x-ref-type")
    ]


def _draw_multi_param_row(
    pdf: FPDF,
    col_widths: list[float],
    row_vals: list[str],
    value_col_idx: int,
    params: list[tuple[str, dict[str, Any]]],
    results: dict[str, Any] | None,
    line_h: float = 4,
    min_h: float = 8,
    aligns: list[str] | None = None,
    original_results: dict[str, Any] | None = None,
    editor_initials: str = "",
    edited_at: str = "",
) -> None:
    """Draw a batch record row with sub-rows in the Value column.

    The Value column is split into one sub-row per parameter, with
    internal horizontal dividers. All other columns span the full height.

    When original_results is provided, edited parameters show the
    original value with strikethrough, the editor initials + date on
    the same line, and the new value below (GMP audit trail).
    """
    if aligns is None:
        aligns = ["C"] * len(row_vals)

    pad = 1
    num_params = len(params)
    orig = original_results or {}

    # Calculate per-param sub-row height: edited params need an extra line
    param_sub_heights: list[float] = []
    for key, _prop in params:
        is_edited = (
            orig
            and key in orig
            and results
            and results.get(key) != orig.get(key)
        )
        if is_edited:
            # label + strikethrough original + new value = 3 content lines
            sub_h = max(min_h, line_h * 4 + pad * 4)
        else:
            sub_h = max(min_h, line_h * 3 + pad * 4)
        param_sub_heights.append(sub_h)
    total_value_h = sum(param_sub_heights)

    # Pre-wrap non-value columns to find their natural height
    wrapped: list[list[str]] = []
    for i, val in enumerate(row_vals):
        if i == value_col_idx:
            wrapped.append([])  # placeholder, drawn separately
        else:
            lines = _wrap_text(pdf, val, col_widths[i] - pad * 2)
            wrapped.append(lines)

    text_h = max(
        (len(lines) * line_h + pad * 2) for i, lines in enumerate(wrapped)
        if i != value_col_idx and lines
    ) if any(lines for i, lines in enumerate(wrapped) if i != value_col_idx) else min_h

    row_h = max(min_h, text_h, total_value_h)

    x_start = pdf.l_margin
    y_start = pdf.get_y()

    # Page break if row doesn't fit
    page_bottom = pdf.h - pdf.b_margin
    if y_start + row_h > page_bottom:
        pdf.add_page()
        y_start = pdf.get_y()

    value_w = col_widths[value_col_idx]
    value_x = x_start + sum(col_widths[:value_col_idx])

    # Draw non-value cells (spanning full row height)
    for i, lines in enumerate(wrapped):
        if i == value_col_idx:
            continue
        x = x_start + sum(col_widths[:i])
        cell_w = col_widths[i]
        pdf.rect(x, y_start, cell_w, row_h, style="D")
        for j, line in enumerate(lines):
            pdf.set_xy(x + pad, y_start + pad + j * line_h)
            pdf.cell(cell_w - pad * 2, line_h, line, border=0, align=aligns[i])

    # Draw value column outer border
    pdf.rect(value_x, y_start, value_w, row_h, style="D")

    # Draw each parameter sub-row inside the value column
    results = results or {}
    inner_w = value_w - pad * 2

    saved_family = pdf.font_family
    saved_size = pdf.font_size_pt
    saved_style = pdf.font_style

    # Scale sub-row heights proportionally if total_value_h < row_h
    scale = row_h / total_value_h if total_value_h > 0 else 1
    cumulative_y = 0.0

    for p_idx, (key, prop) in enumerate(params):
        actual_sub_h = param_sub_heights[p_idx] * scale
        sub_y = y_start + cumulative_y
        cumulative_y += actual_sub_h

        label = prop.get("title") or key.replace("_", " ").title()
        unit = prop.get("unit", "")
        if unit:
            label = f"{label} ({unit})"

        is_edited = (
            orig
            and key in orig
            and results.get(key) != orig.get(key)
        )

        # Internal horizontal divider (skip for first sub-row)
        if p_idx > 0:
            pdf.set_draw_color(200, 200, 200)
            pdf.line(value_x, sub_y, value_x + value_w, sub_y)
            pdf.set_draw_color(0, 0, 0)

        # Bold label on first line
        pdf.set_xy(value_x + pad, sub_y + pad)
        pdf.set_font(saved_family, "B", saved_size)
        pdf.cell(inner_w, line_h, label, border=0, align="L")

        if is_edited:
            # Strikethrough original value in gray, with editor
            # initials + date on the same line (GMP correction format)
            orig_val = _format_value(orig[key])
            annotation = ""
            if editor_initials or edited_at:
                parts = [p for p in (editor_initials, edited_at) if p]
                annotation = "  " + " ".join(parts)

            pdf.set_xy(value_x + pad, sub_y + pad + line_h)
            pdf.set_text_color(160, 160, 160)
            pdf.set_font(saved_family, "S", saved_size)
            struck_w = pdf.get_string_width(orig_val)
            pdf.cell(struck_w, line_h, orig_val, border=0, align="L")
            # Editor initials + date in normal (non-struck) style
            if annotation:
                pdf.set_font(saved_family, "I", max(saved_size - 1, 6))
                pdf.cell(inner_w - struck_w, line_h, annotation,
                         border=0, align="L")

            # New value on third line in normal style
            new_val = _format_value(results[key]) if results.get(key) is not None else ""
            pdf.set_xy(value_x + pad, sub_y + pad + line_h * 2)
            pdf.set_text_color(51, 65, 85)
            pdf.set_font(saved_family, "", saved_size)
            pdf.cell(inner_w, line_h, new_val, border=0, align="L")
        else:
            # Value on second line (filled mode) or blank for handwriting
            filled_val = results.get(key)
            display_val = (
                _format_value(filled_val)
                if filled_val is not None and filled_val != ""
                else ""
            )
            pdf.set_xy(value_x + pad, sub_y + pad + line_h)
            pdf.set_font(saved_family, "", saved_size)
            pdf.cell(inner_w, line_h, display_val, border=0, align="L")

    # Restore original font state
    pdf.set_text_color(51, 65, 85)
    pdf.set_font(saved_family, saved_style, saved_size)
    pdf.set_xy(x_start, y_start + row_h)


def generate_batch_record_pdf(
    protocol_name: str,
    run_name: str,
    roles: list[dict[str, Any]],
    steps: list[dict[str, Any]],
    filled: bool = False,
    execution_data: dict[str, Any] | None = None,
    format_options: dict[str, Any] | None = None,
    roles_with_steps: list[dict[str, Any]] | None = None,
    is_role_based: bool = True,
    version_number: int | None = None,
    last_modified: str | None = None,
    user_map: dict[str, str] | None = None,
    started_by_id: str | None = None,
    run_status: str | None = None,
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
        format_options: Optional dict overriding PDF formatting defaults.
        roles_with_steps: Optional list of role dicts with process_name
            and process_description for section headers.
        is_role_based: If True, protocol uses swimlane roles; if False,
            process-based organization (one table per process).
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

    pdf = _BatchPdf(
        font_family=ff,
        protocol_title=protocol_name,
        version_label=version_label,
        last_modified=modified_str,
    )
    pdf.add_font("Cursive", "", _CURSIVE_FONT_PATH)
    pdf.alias_nb_pages()
    pdf.add_page()

    w = pdf.epw

    # Add spacing after header
    pdf.ln(6)

    # Helper function to draw Date and Lot/Batch fields
    def draw_batch_fields():
        half = w / 2
        pdf.set_font(ff, "B", fs["body"])
        pdf.set_text_color(51, 65, 85)

        # First row: Date and Lot/Batch
        pdf.cell(half * 0.2, 6, "Date:", align="L")
        # Underline for date (operator writes in)
        date_x = pdf.get_x()
        date_y = pdf.get_y() + 4
        pdf.line(date_x, date_y, pdf.l_margin + half - 5, date_y)
        pdf.cell(half * 0.8, 6, "", align="L")  # Space for the underline

        # Right column: Lot/Batch
        pdf.set_x(pdf.l_margin + half)
        pdf.cell(half * 0.3, 6, "Lot/Batch #:", align="L")
        # Underline for lot/batch (operator writes in)
        lot_x = pdf.get_x()
        lot_y = pdf.get_y() + 4
        pdf.line(lot_x, lot_y, pdf.l_margin + w - 5, lot_y)
        pdf.cell(half * 0.7, 6, "", align="L")  # Space for the underline
        pdf.ln(10)

    # Draw batch fields at the top of the first page
    draw_batch_fields()

    # Determine if any step has a real role (only for role-based protocols)
    has_roles = is_role_based and any(
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

    table_line_h = rs["line_h"]
    table_min_h = rs["min_row_h"]
    exec_data = execution_data or {}
    rws = roles_with_steps or []
    umap = user_map or {}

    def _step_initials(step_id: str) -> str:
        """Get cursive initials for the user who completed a step."""
        if not filled or not umap:
            return ""
        sd = exec_data.get(step_id, {})
        if sd.get("status") != "completed":
            return ""
        uid = sd.get("completed_by_user_id", "")
        name = umap.get(uid, "")
        # Fallback to started_by_id for legacy runs
        if not name and started_by_id:
            name = umap.get(started_by_id, "")
        return _get_initials(name) if name else ""

    def _step_editor_initials(step_id: str) -> str:
        """Get initials for the user who edited a step (GMP)."""
        if not filled or not umap:
            return ""
        sd = exec_data.get(step_id, {})
        editor_uid = sd.get("edited_by_user_id", "")
        if not editor_uid:
            return ""
        name = umap.get(editor_uid, "")
        return _get_initials(name) if name else ""

    def _step_original_results(step_id: str) -> dict[str, Any] | None:
        """Get original_results for an edited step, if any."""
        if not filled:
            return None
        sd = exec_data.get(step_id, {})
        return sd.get("original_results")

    def _step_edited_at(step_id: str) -> str:
        """Get formatted edited_at date for a step."""
        if not filled:
            return ""
        sd = exec_data.get(step_id, {})
        raw = sd.get("edited_at", "")
        if not raw:
            return ""
        try:
            from datetime import datetime as _dt
            dt = _dt.fromisoformat(raw.replace("Z", "+00:00"))
            return dt.strftime("%m/%d/%y")
        except (ValueError, AttributeError):
            return raw[:10] if len(raw) >= 10 else raw

    initials_col = len(col_widths) - 1  # last column is always Initials

    # Check if we should generate separate tables per process
    multi_process = not is_role_based and len(rws) > 1

    if multi_process:
        # Generate separate table for each process
        for proc_idx, process_entry in enumerate(rws):
            if proc_idx > 0:
                pdf.add_page()
                # Add spacing after header on new page
                pdf.ln(6)
                # Draw batch fields on each new page
                draw_batch_fields()

            process_name = (
                process_entry.get("process_name") or
                process_entry.get("role_name") or ""
            )
            if process_name:
                # Print process title above table
                pdf.set_font(ff, "B", fs["section"])
                pdf.set_text_color(*hc)
                pdf.cell(0, 8, process_name)
                pdf.ln(8)

            # Draw table header for this process
            pdf.set_fill_color(*hc)
            pdf.set_text_color(255, 255, 255)
            pdf.set_font(ff, "B", fs["table"])
            _draw_table_row(
                pdf, col_widths, headers,
                line_h=table_line_h, min_h=table_min_h,
                aligns=header_aligns, fill=True,
            )

            # Draw rows for this process
            pdf.set_text_color(51, 65, 85)
            pdf.set_font(ff, "", fs["table"])
            pdf.set_draw_color(200, 200, 200)

            step_counter = 0
            for step in process_entry.get("steps", []):
                step_counter += 1
                step_id = step.get("id", "")
                row_data = exec_data.get(step_id, {}) if filled else {}

                # Build description
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

                editable = _get_editable_params(step.get("param_schema"))
                use_multi = len(editable) > 1
                results = row_data.get("results", {}) if filled else {}
                initials = _step_initials(step_id)
                editor_initials = _step_editor_initials(step_id)
                orig_results = _step_original_results(step_id)
                edited_at = _step_edited_at(step_id)

                if has_roles:
                    row_vals = [
                        str(step_counter),
                        step.get("role_name", "") or "",
                        step.get("name", "--"),
                        full_desc,
                        row_data.get("value", "") if filled and not use_multi else "",
                        "",  # initials drawn separately in cursive
                    ]
                    aligns = ["C", "C", "L", "L", "C", "C"]
                    value_col = 4
                else:
                    row_vals = [
                        str(step_counter),
                        step.get("name", "--"),
                        full_desc,
                        row_data.get("value", "") if filled and not use_multi else "",
                        "",  # initials drawn separately in cursive
                    ]
                    aligns = ["C", "L", "L", "C", "C"]
                    value_col = 3

                y_before = pdf.get_y()
                if use_multi:
                    _draw_multi_param_row(
                        pdf, col_widths, row_vals,
                        value_col_idx=value_col,
                        params=editable,
                        results=results,
                        line_h=table_line_h, min_h=table_min_h,
                        aligns=aligns,
                        original_results=orig_results,
                        editor_initials=editor_initials,
                        edited_at=edited_at,
                    )
                else:
                    _draw_table_row(
                        pdf, col_widths, row_vals,
                        line_h=table_line_h, min_h=table_min_h, aligns=aligns,
                    )
                y_after = pdf.get_y()

                # Initials column: only the completer (editor info is
                # rendered inline with the strikethrough in the Value col)
                if initials:
                    ix = pdf.l_margin + sum(col_widths[:initials_col])
                    _draw_cursive_initials(
                        pdf, initials, ix, y_before,
                        col_widths[initials_col], y_after - y_before,
                    )
                    pdf.set_xy(pdf.l_margin, y_after)
    else:
        # Single table with optional section headers
        pdf.set_fill_color(*hc)
        pdf.set_text_color(255, 255, 255)
        pdf.set_font(ff, "B", fs["table"])

        _draw_table_row(
            pdf, col_widths, headers,
            line_h=table_line_h, min_h=table_min_h,
            aligns=header_aligns, fill=True,
        )

        # Table rows
        pdf.set_text_color(51, 65, 85)
        pdf.set_font(ff, "", fs["table"])
        pdf.set_draw_color(200, 200, 200)

        # Detect process sections for per-section numbering
        has_process_sections = any(
            rd.get("process_name") for rd in rws
        )

        # Build a map from step ID to its process section info
        step_section_map: dict[str, dict[str, str]] = {}
        if has_process_sections:
            for rd in rws:
                pname = rd.get("process_name", "")
                pdesc = rd.get("process_description", "")
                for s in rd.get("steps", []):
                    step_section_map[s.get("id", "")] = {
                        "process_name": pname,
                        "process_description": pdesc,
                    }

        step_counter = 0
        current_section = ""
        num_cols = len(col_widths)

        for step in steps:
            step_id = step.get("id", "")
            row_data = exec_data.get(step_id, {}) if filled else {}

            # Section header row for process sections
            if has_process_sections and step_id in step_section_map:
                section_info = step_section_map[step_id]
                section_name = section_info.get("process_name", "")
                if section_name and section_name != current_section:
                    current_section = section_name
                    step_counter = 0  # Reset numbering for new section

                    # Draw section header spanning full width
                    section_label = section_name
                    section_desc = section_info.get("process_description", "")
                    if section_desc:
                        section_label = f"{section_name} - {section_desc}"

                    pdf.set_font(ff, "B", fs["table"])
                    # Use a light tint of the header color for fill
                    pdf.set_fill_color(
                        min(hc[0] + 200, 245),
                        min(hc[1] + 200, 245),
                        min(hc[2] + 200, 245),
                    )
                    pdf.set_text_color(*hc)
                    _draw_table_row(
                        pdf, [w], [section_label],
                        line_h=table_line_h, min_h=table_min_h,
                        aligns=["L"], fill=True,
                    )
                    pdf.set_text_color(51, 65, 85)
                    pdf.set_font(ff, "", fs["table"])

            step_counter += 1

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

            editable = _get_editable_params(step.get("param_schema"))
            use_multi = len(editable) > 1
            results = row_data.get("results", {}) if filled else {}
            initials = _step_initials(step_id)
            editor_initials = _step_editor_initials(step_id)
            orig_results = _step_original_results(step_id)
            edited_at = _step_edited_at(step_id)

            if has_roles:
                row_vals = [
                    str(step_counter),
                    step.get("role_name", "") or "",
                    step.get("name", "--"),
                    full_desc,
                    row_data.get("value", "") if filled and not use_multi else "",
                    "",  # initials drawn separately in cursive
                ]
                aligns = ["C", "C", "L", "L", "C", "C"]
                value_col = 4
            else:
                row_vals = [
                    str(step_counter),
                    step.get("name", "--"),
                    full_desc,
                    row_data.get("value", "") if filled and not use_multi else "",
                    "",  # initials drawn separately in cursive
                ]
                aligns = ["C", "L", "L", "C", "C"]
                value_col = 3

            y_before = pdf.get_y()
            if use_multi:
                _draw_multi_param_row(
                    pdf, col_widths, row_vals,
                    value_col_idx=value_col,
                    params=editable,
                    results=results,
                    line_h=table_line_h, min_h=table_min_h,
                    aligns=aligns,
                    original_results=orig_results,
                    editor_initials=editor_initials,
                    edited_at=edited_at,
                )
            else:
                _draw_table_row(
                    pdf, col_widths, row_vals,
                    line_h=table_line_h, min_h=table_min_h, aligns=aligns,
                )
            y_after = pdf.get_y()

            # Initials column: only the completer (editor info is
            # rendered inline with the strikethrough in the Value col)
            if initials:
                ix = pdf.l_margin + sum(col_widths[:initials_col])
                _draw_cursive_initials(
                    pdf, initials, ix, y_before,
                    col_widths[initials_col], y_after - y_before,
                )
                pdf.set_xy(pdf.l_margin, y_after)

    pdf.ln(12)

    # Role sign-off section (only if roles exist)
    if roles:
        pdf.set_font(ff, "B", fs["step_title"])
        pdf.set_text_color(15, 23, 42)
        pdf.cell(0, 7, "Role Sign-Off")
        pdf.ln(10)

        pdf.set_font(ff, "", 9)
        pdf.set_text_color(51, 65, 85)

        for role in roles:
            role_name = role.get("name", "Unknown")
            pdf.set_font(ff, "B", 9)
            pdf.cell(0, 6, role_name)
            pdf.ln(12)
            y = pdf.get_y()
            pdf.line(pdf.l_margin, y, pdf.l_margin + 80, y)
            pdf.ln(2)
            pdf.set_font(ff, "", 7)
            pdf.set_text_color(100, 100, 100)
            pdf.cell(0, 4, "Signature / Date")
            pdf.ln(8)
            pdf.set_text_color(51, 65, 85)

    return bytes(pdf.output())
