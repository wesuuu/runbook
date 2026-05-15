"""Smoke test: new Batch Record template parses and renders correctly.

Asserts the rendered .docx text contains expected section headings when fed
get_mock_context(), and that no Jinja tokens leak through. Verifies that
conditional columns (Reviewer, Scheduled) appear when the mock context has
reviewer_enabled=True and time_enabled=True.
"""
import io
from pathlib import Path

from docx import Document
from docxtpl import DocxTemplate

from app.services.protocols.template_engine import get_mock_context

BR_PATH = (
    Path(__file__).resolve().parents[2]
    / "app/services/documents/templates/batch_record_default.docx"
)


def _doc_text(blob: bytes) -> str:
    parts = []
    d = Document(io.BytesIO(blob))
    for p in d.paragraphs:
        parts.append(p.text)
    for t in d.tables:
        for row in t.rows:
            for cell in row.cells:
                parts.append(cell.text)
    return "\n".join(parts)


def test_br_template_renders_mock_context_without_unresolved_tokens():
    tpl = DocxTemplate(BR_PATH)
    tpl.render(get_mock_context())
    buf = io.BytesIO()
    tpl.save(buf)
    text = _doc_text(buf.getvalue())

    # Section headers (introduced in this template)
    for heading in (
        "Batch Record",
        "Equipment Used",
        "Procedure Execution",
        "Notes",
        "Approval",
    ):
        assert heading in text, f"missing section: {heading}"

    # No leaked Jinja tokens
    assert "{{" not in text
    assert "{%" not in text

    # When mock context has time_enabled and reviewer_enabled, columns appear
    assert "Reviewer" in text
    assert "Scheduled" in text
    assert "Lot Number" in text or "Lot:" in text
