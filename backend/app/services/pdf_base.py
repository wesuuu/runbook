"""Shared PDF utilities, constants, and table drawing helpers.

Used by both SOP and batch record PDF generators.
"""

import re
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
