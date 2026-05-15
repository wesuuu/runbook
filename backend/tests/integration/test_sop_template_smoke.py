"""Smoke test: new SOP template parses and renders correctly.

Asserts the rendered .docx text contains expected section headings when fed
get_mock_context(), and that no Jinja tokens leak through. Also verifies
optional sections are gated out when the context has empty values.
"""
import io
from pathlib import Path

from docx import Document
from docxtpl import DocxTemplate

from app.services.protocols.template_engine import build_context, get_mock_context

SOP_PATH = (
    Path(__file__).resolve().parents[3]
    / "backend/app/services/documents/templates/sop_default.docx"
)


def _doc_text(blob: bytes) -> str:
    return "\n".join(p.text for p in Document(io.BytesIO(blob)).paragraphs)


def test_sop_template_renders_mock_context_without_unresolved_tokens():
    tpl = DocxTemplate(SOP_PATH)
    tpl.render(get_mock_context())
    buf = io.BytesIO()
    tpl.save(buf)
    text = _doc_text(buf.getvalue())

    # Section headers (introduced in this template)
    for heading in (
        "Purpose",
        "Scope",
        "Definitions",
        "References",
        "Revision History",
        "Responsibilities",
        "Equipment",
        "Procedure",
    ):
        assert heading in text, f"missing section: {heading}"

    # No leaked Jinja tokens
    assert "{{" not in text
    assert "{%" not in text


def test_sop_template_omits_optional_sections_when_blank():
    ctx, _ = build_context(protocol_name="bare")
    tpl = DocxTemplate(SOP_PATH)
    tpl.render(ctx)
    buf = io.BytesIO()
    tpl.save(buf)
    text = _doc_text(buf.getvalue())

    # `bare` context has no purpose/scope/etc.; the headings should be gated.
    assert "Purpose" not in text
    assert "Scope" not in text
