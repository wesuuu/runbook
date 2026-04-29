"""DEPRECATED — Batch record PDF generator (fpdf2-based).

This module is superseded by the docxtpl template engine
(app.services.protocols.template_engine). Kept for reference during the
transition to .docx-based templates. Remove once Phase 0 of
F-0065 (Custom Document Templates) is verified in production.
"""

from typing import Any

from fpdf import FPDF

from app.services.core.file_storage import IMAGE_MIME_TYPES
from app.services.documents.pdf_base import (_CURSIVE_FONT_PATH,
                                             _build_param_sentence,
                                             _draw_cursive_initials,
                                             _draw_table_row, _format_value,
                                             _fs, _get_editable_params,
                                             _get_initials, _render_template,
                                             _resolve_format, _rs, _wrap_text)


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
            orig and key in orig and results and results.get(key) != orig.get(key)
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

    text_h = (
        max(
            (len(lines) * line_h + pad * 2)
            for i, lines in enumerate(wrapped)
            if i != value_col_idx and lines
        )
        if any(lines for i, lines in enumerate(wrapped) if i != value_col_idx)
        else min_h
    )

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

        is_edited = orig and key in orig and results.get(key) != orig.get(key)

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
                pdf.cell(inner_w - struck_w, line_h, annotation, border=0, align="L")

            # New value on third line in normal style
            new_val = (
                _format_value(results[key]) if results.get(key) is not None else ""
            )
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
    notes: list[dict[str, Any]] | None = None,
    attachments: list[dict[str, Any]] | None = None,
    embed_images: bool = False,
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
            w * 0.05,  # #
            w * 0.13,  # Role
            w * 0.17,  # Step Name
            w * 0.30,  # Description
            w * 0.20,  # Value/Result
            w * 0.15,  # Initials
        ]
        headers = ["#", "Role", "Step", "Description", "Value / Result", "Initials"]
        header_aligns = ["C"] * 6
    else:
        col_widths = [
            w * 0.05,  # #
            w * 0.20,  # Step Name
            w * 0.40,  # Description
            w * 0.20,  # Value/Result
            w * 0.15,  # Initials
        ]
        headers = ["#", "Step", "Description", "Value / Result", "Initials"]
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

    # Pre-assign figure numbers to image attachments
    active_atts = [a for a in (attachments or []) if not a.get("deleted")]
    image_atts = [
        a for a in active_atts if a.get("content_type", "") in IMAGE_MIME_TYPES
    ]
    non_image_atts = [
        a for a in active_atts if a.get("content_type", "") not in IMAGE_MIME_TYPES
    ]

    # figure_map: step_id → [figure_number, ...]
    figure_map: dict[str, list[int]] = {}
    for fig_idx, att in enumerate(image_atts, start=1):
        sid = att.get("step_id")
        if sid:
            figure_map.setdefault(sid, []).append(fig_idx)

    # Build step name lookup for attachment scope labels
    step_name_map: dict[str, str] = {}
    for s in steps:
        step_name_map[s.get("id", "")] = s.get("name", "")

    def _draw_step_notes_area(
        step_id: str,
        row_data: dict[str, Any],
    ) -> None:
        """Draw a compact notes sub-area below a step row.

        On blank records: 'Notes:' label with underlines for handwriting.
        On filled records: shows note text and attachment cross-references.
        """
        step_notes_text = row_data.get("notes", "") if filled else ""
        fig_refs = figure_map.get(step_id, [])

        # Content width: skip # col (and Role col if present)
        skip_cols = 1 + (1 if has_roles else 0)
        notes_x = pdf.l_margin + sum(col_widths[:skip_cols])
        notes_w = sum(col_widths[skip_cols:])

        content_lines: list[str] = []
        if step_notes_text:
            content_lines = _wrap_text(pdf, step_notes_text, notes_w - 6)

        fig_line = ""
        if fig_refs and filled:
            fig_str = ", ".join(f"Figure {n}" for n in fig_refs)
            fig_line = f"See {fig_str}"

        lh = table_line_h
        if content_lines:
            # Filled: label line + wrapped text
            area_h = lh + len(content_lines) * lh
        else:
            # Blank: generous space for handwriting (~20mm)
            area_h = 20
        if fig_line:
            area_h += lh

        # Page break check
        if pdf.get_y() + area_h > pdf.h - 25:
            pdf.add_page()

        y_start = pdf.get_y()

        # "Notes:" label (inline, small)
        pdf.set_xy(notes_x + 2, y_start + 0.5)
        pdf.set_font(ff, "I", fs["table"] - 1)
        pdf.set_text_color(150, 155, 165)
        label_w = pdf.get_string_width("Notes:") + 2
        pdf.cell(label_w, lh, "Notes:")

        if content_lines:
            # Filled: render note text after label
            pdf.set_font(ff, "", fs["table"])
            pdf.set_text_color(51, 65, 85)
            # First line on same row as label
            pdf.cell(notes_w - label_w - 4, lh, content_lines[0])
            # Remaining lines below
            for ln in content_lines[1:]:
                pdf.set_xy(notes_x + 2, pdf.get_y() + lh)
                pdf.cell(notes_w - 4, lh, ln)
            pdf.set_xy(pdf.l_margin, y_start + area_h)

        # Attachment cross-references
        if fig_line:
            ref_y = y_start + area_h - lh
            pdf.set_xy(notes_x + 2, ref_y)
            pdf.set_font(ff, "I", fs["table"] - 1)
            pdf.set_text_color(100, 116, 139)
            pdf.cell(notes_w - 4, lh, fig_line)

        y_end = y_start + area_h
        # Border matching table width
        pdf.set_draw_color(200, 200, 200)
        pdf.rect(pdf.l_margin, y_start, sum(col_widths), area_h)
        # Left column dividers for # (and Role)
        x_acc = pdf.l_margin
        for ci in range(skip_cols):
            x_acc += col_widths[ci]
            pdf.line(x_acc, y_start, x_acc, y_end)

        pdf.set_xy(pdf.l_margin, y_end)
        pdf.set_text_color(51, 65, 85)
        pdf.set_font(ff, "", fs["table"])

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
                process_entry.get("process_name")
                or process_entry.get("role_name")
                or ""
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
                pdf,
                col_widths,
                headers,
                line_h=table_line_h,
                min_h=table_min_h,
                aligns=header_aligns,
                fill=True,
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
                        step.get("params"),
                        step.get("param_schema"),
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
                        pdf,
                        col_widths,
                        row_vals,
                        value_col_idx=value_col,
                        params=editable,
                        results=results,
                        line_h=table_line_h,
                        min_h=table_min_h,
                        aligns=aligns,
                        original_results=orig_results,
                        editor_initials=editor_initials,
                        edited_at=edited_at,
                    )
                else:
                    _draw_table_row(
                        pdf,
                        col_widths,
                        row_vals,
                        line_h=table_line_h,
                        min_h=table_min_h,
                        aligns=aligns,
                    )
                y_after = pdf.get_y()

                # Initials column: only the completer (editor info is
                # rendered inline with the strikethrough in the Value col)
                if initials:
                    ix = pdf.l_margin + sum(col_widths[:initials_col])
                    _draw_cursive_initials(
                        pdf,
                        initials,
                        ix,
                        y_before,
                        col_widths[initials_col],
                        y_after - y_before,
                    )
                    pdf.set_xy(pdf.l_margin, y_after)

                # Step-level notes sub-area
                _draw_step_notes_area(step_id, row_data)

    else:
        # Single table with optional section headers
        pdf.set_fill_color(*hc)
        pdf.set_text_color(255, 255, 255)
        pdf.set_font(ff, "B", fs["table"])

        _draw_table_row(
            pdf,
            col_widths,
            headers,
            line_h=table_line_h,
            min_h=table_min_h,
            aligns=header_aligns,
            fill=True,
        )

        # Table rows
        pdf.set_text_color(51, 65, 85)
        pdf.set_font(ff, "", fs["table"])
        pdf.set_draw_color(200, 200, 200)

        # Detect process sections for per-section numbering
        has_process_sections = any(rd.get("process_name") for rd in rws)

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
                        pdf,
                        [w],
                        [section_label],
                        line_h=table_line_h,
                        min_h=table_min_h,
                        aligns=["L"],
                        fill=True,
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
                    step.get("params"),
                    step.get("param_schema"),
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
                    pdf,
                    col_widths,
                    row_vals,
                    value_col_idx=value_col,
                    params=editable,
                    results=results,
                    line_h=table_line_h,
                    min_h=table_min_h,
                    aligns=aligns,
                    original_results=orig_results,
                    editor_initials=editor_initials,
                    edited_at=edited_at,
                )
            else:
                _draw_table_row(
                    pdf,
                    col_widths,
                    row_vals,
                    line_h=table_line_h,
                    min_h=table_min_h,
                    aligns=aligns,
                )
            y_after = pdf.get_y()

            # Initials column: only the completer (editor info is
            # rendered inline with the strikethrough in the Value col)
            if initials:
                ix = pdf.l_margin + sum(col_widths[:initials_col])
                _draw_cursive_initials(
                    pdf,
                    initials,
                    ix,
                    y_before,
                    col_widths[initials_col],
                    y_after - y_before,
                )
                pdf.set_xy(pdf.l_margin, y_after)

            # Step-level notes sub-area
            _draw_step_notes_area(step_id, row_data)

    pdf.ln(12)

    # Run-level Notes & Observations section (filled records only)
    if filled and notes:
        if pdf.get_y() > pdf.h - 60:
            pdf.add_page()

        pdf.set_font(ff, "B", fs["step_title"])
        pdf.set_text_color(15, 23, 42)
        pdf.cell(0, 7, "Notes & Observations")
        pdf.ln(10)

        for note in notes:
            if pdf.get_y() > pdf.h - 40:
                pdf.add_page()

            content = note.get("content", "")
            author = note.get("author_name", "Unknown")
            created = note.get("created_at", "")
            flags = note.get("flags", [])
            note_status = note.get("run_status", "")

            ts_display = created[:19].replace("T", " ") if created else ""
            flag_prefix = "[ANOMALY] " if "anomaly" in flags else ""

            pdf.set_font(ff, "B", fs["body"] - 1)
            pdf.set_text_color(100, 116, 139)
            meta = f"{author}  |  {ts_display}"
            if note_status:
                meta += f"  |  {note_status}"
            pdf.cell(0, 5, meta)
            pdf.ln(5)

            pdf.set_font(ff, "", fs["body"])
            pdf.set_text_color(51, 65, 85)
            for ln in _wrap_text(pdf, f"{flag_prefix}{content}", pdf.epw - 4):
                pdf.cell(0, 5, ln)
                pdf.ln(5)

            pdf.ln(4)

        pdf.ln(4)

    # Attachments reference table (non-image files, filled records only)
    if filled and non_image_atts:
        if pdf.get_y() > pdf.h - 60:
            pdf.add_page()

        pdf.set_font(ff, "B", fs["step_title"])
        pdf.set_text_color(15, 23, 42)
        pdf.cell(0, 7, f"Attachments ({len(non_image_atts)})")
        pdf.ln(10)

        ref_cols = [w * 0.35, w * 0.15, w * 0.25, w * 0.25]
        ref_headers = ["Filename", "Type", "Scope", "Uploaded"]
        pdf.set_fill_color(*hc)
        pdf.set_text_color(255, 255, 255)
        pdf.set_font(ff, "B", fs["table"])
        _draw_table_row(
            pdf,
            ref_cols,
            ref_headers,
            line_h=table_line_h,
            min_h=table_min_h,
            aligns=["L", "L", "L", "L"],
            fill=True,
        )

        pdf.set_text_color(51, 65, 85)
        pdf.set_font(ff, "", fs["table"])
        pdf.set_draw_color(200, 200, 200)

        for att in non_image_atts:
            if pdf.get_y() > pdf.h - 20:
                pdf.add_page()

            filename = att.get("filename", "Unknown")
            ctype = att.get("content_type", "").split("/")[-1]
            sid = att.get("step_id")
            scope = step_name_map.get(sid, sid) if sid else "Run-level"
            uploaded_at = att.get("uploaded_at", "")
            ts = uploaded_at[:16].replace("T", " ") if uploaded_at else ""

            _draw_table_row(
                pdf,
                ref_cols,
                [filename, ctype, scope, ts],
                line_h=table_line_h,
                min_h=table_min_h,
                aligns=["L", "L", "L", "L"],
            )

        pdf.ln(8)

    # Figures section (embedded images, filled records only)
    if filled and embed_images and image_atts:
        from io import BytesIO
        from pathlib import Path

        from app.services.core.file_storage import FileStorageService

        pdf.add_page()
        pdf.set_font(ff, "B", fs["section"])
        pdf.set_text_color(15, 23, 42)
        pdf.cell(0, 8, "Figures")
        pdf.ln(10)

        storage = FileStorageService()

        for fig_idx, att in enumerate(image_atts, start=1):
            if pdf.get_y() > pdf.h - 80:
                pdf.add_page()

            filename = att.get("filename", "")
            sid = att.get("step_id")
            scope = step_name_map.get(sid, sid) if sid else "Run-level"
            uploaded_at = att.get("uploaded_at", "")
            ts = uploaded_at[:16].replace("T", " ") if uploaded_at else ""

            file_path = storage.resolve_path(att.get("file_path", ""))
            if not file_path.exists():
                # Skip missing files but note it
                pdf.set_font(ff, "I", fs["body"])
                pdf.set_text_color(180, 50, 50)
                pdf.cell(0, 5, f"Figure {fig_idx}: {filename} — file not found")
                pdf.ln(8)
                pdf.set_text_color(51, 65, 85)
                continue

            content_type = att.get("content_type", "")
            if content_type in ("image/tiff", "image/webp"):
                from PIL import Image as PILImage

                img = PILImage.open(file_path)
                buf = BytesIO()
                img.save(buf, format="PNG")
                buf.seek(0)
                pdf.image(buf, x=pdf.l_margin, w=pdf.epw)
            else:
                pdf.image(str(file_path), x=pdf.l_margin, w=pdf.epw)

            pdf.ln(2)
            pdf.set_font(ff, "I", fs["body"] - 1)
            pdf.set_text_color(100, 116, 139)
            caption = f"Figure {fig_idx}: {filename} \u2014 {scope} \u2014 {ts}"
            pdf.cell(0, 5, caption, align="C")
            pdf.ln(10)
            pdf.set_text_color(51, 65, 85)

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
