"""QA-0008: KNOWN_VARIABLES surface."""

from io import BytesIO

from docx import Document

from app.services.protocols.template_engine import KNOWN_VARIABLES, parse_template

REQUIRED = {
    "time_enabled",
    "start_time",
    "reviewer_enabled",
    "equipment_summary",
    "revision_history",
    "responsibilities",
    "deviations",
    "doc_number",
    "effective_date",
    "supersedes_date",
    "purpose",
    "scope",
    "references",
    "definitions",
    "lot_number",
    "batch_number",
}


def _make_docx_with_tokens(tokens: set[str]) -> BytesIO:
    """Build an in-memory .docx with one Jinja2 token per paragraph."""
    doc = Document()
    for tok in sorted(tokens):
        doc.add_paragraph(f"{{{{ {tok} }}}}")
    buf = BytesIO()
    doc.save(buf)
    buf.seek(0)
    return buf


def test_known_variables_covers_expected_surface():
    missing = REQUIRED - KNOWN_VARIABLES
    assert missing == set(), f"missing from KNOWN_VARIABLES: {missing}"


def test_parse_template_accepts_extended_tokens(tmp_path):
    buf = _make_docx_with_tokens(REQUIRED)
    docx_path = tmp_path / "tokens.docx"
    docx_path.write_bytes(buf.getvalue())

    recognized, unrecognized = parse_template(docx_path)
    assert not unrecognized, f"parse_template flagged: {unrecognized}"
    assert set(recognized) == REQUIRED
