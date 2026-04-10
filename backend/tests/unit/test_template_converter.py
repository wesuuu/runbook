"""Unit tests for template_converter service helpers.

Tests the pure/mechanical functions that don't require an AI model:
- _extract_body_xml: parsing AI output to get OpenXML body content
- _wrap_in_docx: wrapping OpenXML into a valid .docx file
- _extract_jinja_variables: extracting variable names from XML
- _try_render: rendering a template with mock data and checking for issues
- _to_pdf: converting input files to PDF
- ConversionState: filesystem-based conversion session management
"""

import json
import tempfile
from pathlib import Path
from uuid import uuid4

import pytest

from app.services.template_converter import (
    ConversionState,
    _extract_body_xml,
    _extract_jinja_variables,
    _try_render,
    _wrap_in_docx,
    _to_pdf,
    JINJA_PATTERN,
    MAX_VERIFICATION_ROUNDS,
)


# ── _extract_body_xml tests ──


class TestExtractBodyXml:
    def test_extracts_body_content_from_tags(self):
        """Should extract content between <w:body> tags."""
        raw = '<w:body><w:p><w:r><w:t>Hello</w:t></w:r></w:p></w:body>'
        result = _extract_body_xml(raw)
        assert result == '<w:p><w:r><w:t>Hello</w:t></w:r></w:p>'

    def test_strips_markdown_code_fences(self):
        """Should strip ```xml code fences wrapping the output."""
        raw = '```xml\n<w:body><w:p><w:r><w:t>Hello</w:t></w:r></w:p></w:body>\n```'
        result = _extract_body_xml(raw)
        assert result == '<w:p><w:r><w:t>Hello</w:t></w:r></w:p>'

    def test_handles_bare_content_without_body_tags(self):
        """Should return content as-is if no <w:body> tags."""
        raw = '<w:p><w:r><w:t>Hello</w:t></w:r></w:p>'
        result = _extract_body_xml(raw)
        assert result == '<w:p><w:r><w:t>Hello</w:t></w:r></w:p>'

    def test_strips_whitespace(self):
        """Should strip leading/trailing whitespace."""
        raw = '  \n<w:p><w:r><w:t>Hello</w:t></w:r></w:p>\n  '
        result = _extract_body_xml(raw)
        assert result == '<w:p><w:r><w:t>Hello</w:t></w:r></w:p>'

    def test_handles_code_fence_with_language(self):
        """Should handle code fences with various language tags."""
        raw = '```openxml\n<w:p><w:r><w:t>Test</w:t></w:r></w:p>\n```'
        result = _extract_body_xml(raw)
        assert '<w:t>Test</w:t>' in result

    def test_preserves_jinja_syntax(self):
        """Should preserve Jinja2 placeholders in the XML."""
        raw = '<w:body><w:p><w:r><w:t>{{ protocol_name }}</w:t></w:r></w:p></w:body>'
        result = _extract_body_xml(raw)
        assert '{{ protocol_name }}' in result


# ── _wrap_in_docx tests ──


class TestWrapInDocx:
    def test_produces_valid_docx_bytes(self):
        """Should produce bytes that can be opened as a .docx file."""
        body_xml = '<w:p><w:r><w:t>Hello World</w:t></w:r></w:p>'
        result = _wrap_in_docx(body_xml)
        assert isinstance(result, bytes)
        assert len(result) > 0
        # .docx files are ZIP archives starting with PK
        assert result[:2] == b'PK'

    def test_contains_text_content(self):
        """Should contain the specified text when opened with python-docx."""
        from docx import Document
        from io import BytesIO

        body_xml = '<w:p><w:r><w:t>Hello World</w:t></w:r></w:p>'
        docx_bytes = _wrap_in_docx(body_xml)
        doc = Document(BytesIO(docx_bytes))
        all_text = "\n".join(p.text for p in doc.paragraphs)
        assert "Hello World" in all_text

    def test_preserves_jinja_placeholders(self):
        """Jinja2 syntax should appear as literal text in the .docx."""
        from docx import Document
        from io import BytesIO

        body_xml = '<w:p><w:r><w:t>Name: {{ operator_name }}</w:t></w:r></w:p>'
        docx_bytes = _wrap_in_docx(body_xml)
        doc = Document(BytesIO(docx_bytes))
        all_text = "\n".join(p.text for p in doc.paragraphs)
        assert "{{ operator_name }}" in all_text

    def test_handles_table_xml(self):
        """Should handle table structures in the XML."""
        body_xml = """
        <w:tbl>
            <w:tr>
                <w:tc><w:p><w:r><w:t>Header</w:t></w:r></w:p></w:tc>
            </w:tr>
            <w:tr>
                <w:tc><w:p><w:r><w:t>Cell</w:t></w:r></w:p></w:tc>
            </w:tr>
        </w:tbl>
        """
        docx_bytes = _wrap_in_docx(body_xml)
        assert isinstance(docx_bytes, bytes)
        assert docx_bytes[:2] == b'PK'

    def test_fallback_on_invalid_xml(self):
        """Should not crash on malformed XML — uses fallback."""
        body_xml = '<w:p><w:r><w:t>Unclosed tag'
        docx_bytes = _wrap_in_docx(body_xml)
        # Should still produce a valid .docx (with fallback content)
        assert isinstance(docx_bytes, bytes)
        assert docx_bytes[:2] == b'PK'


# ── _extract_jinja_variables tests ──


class TestExtractJinjaVariables:
    def test_extracts_simple_variables(self):
        """Should extract top-level variable names from {{ }}."""
        xml = '<w:t>{{ protocol_name }}</w:t><w:t>{{ operator_name }}</w:t>'
        result = _extract_jinja_variables(xml)
        assert "protocol_name" in result
        assert "operator_name" in result

    def test_extracts_dotted_variable_top_level(self):
        """Should extract the top-level name from dotted references."""
        xml = '<w:t>{{ step.name }}</w:t><w:t>{{ step.description }}</w:t>'
        result = _extract_jinja_variables(xml)
        assert "step" in result

    def test_extracts_loop_collections(self):
        """Should extract collection names from {% for %} loops."""
        xml = '{% for step in steps %}<w:t>{{ step.name }}</w:t>{% endfor %}'
        result = _extract_jinja_variables(xml)
        assert "steps" in result

    def test_empty_input(self):
        """Should return empty set for no variables."""
        result = _extract_jinja_variables('<w:t>Plain text</w:t>')
        assert result == set()

    def test_deduplicates(self):
        """Should return unique variables."""
        xml = '<w:t>{{ name }}</w:t><w:t>{{ name }}</w:t>'
        result = _extract_jinja_variables(xml)
        assert result == {"name"}

    def test_mixed_variables_and_loops(self):
        """Should extract both standalone variables and loop collections."""
        xml = """
        <w:t>{{ protocol_name }}</w:t>
        <w:t>{{ version_number }}</w:t>
        {% for step in steps %}
        <w:t>{{ step.name }}</w:t>
        {% endfor %}
        {% for role in roles %}
        <w:t>{{ role.name }}</w:t>
        {% endfor %}
        """
        result = _extract_jinja_variables(xml)
        assert "protocol_name" in result
        assert "version_number" in result
        assert "steps" in result
        assert "roles" in result
        assert "step" in result
        assert "role" in result


# ── JINJA_PATTERN tests ──


class TestJinjaPattern:
    def test_matches_double_braces(self):
        assert JINJA_PATTERN.findall("Hello {{ name }} world")

    def test_matches_block_tags(self):
        assert JINJA_PATTERN.findall("{% for x in y %}")

    def test_no_match_on_plain_text(self):
        assert not JINJA_PATTERN.findall("Hello world")


# ── ConversionState tests ──


class TestConversionState:
    def test_ensure_dir_creates_directory(self):
        """Should create the conversion directory under storage root."""
        with tempfile.TemporaryDirectory() as tmpdir:
            org_id = uuid4()
            conv_id = uuid4()
            state = ConversionState(org_id, conv_id, storage_root=tmpdir)
            state.ensure_dir()
            expected_dir = Path(tmpdir) / str(org_id) / "conversions" / str(conv_id)
            assert expected_dir.is_dir()

    def test_write_and_read(self):
        """Should write and read files in the conversion directory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            org_id = uuid4()
            conv_id = uuid4()
            state = ConversionState(org_id, conv_id, storage_root=tmpdir)
            state.ensure_dir()
            state.write("test.txt", b"hello")
            assert state.read("test.txt") == b"hello"

    def test_exists(self):
        """Should correctly report file existence."""
        with tempfile.TemporaryDirectory() as tmpdir:
            org_id = uuid4()
            conv_id = uuid4()
            state = ConversionState(org_id, conv_id, storage_root=tmpdir)
            state.ensure_dir()
            assert not state.exists("missing.txt")
            state.write("present.txt", b"data")
            assert state.exists("present.txt")

    def test_write_json_and_read_json(self):
        """Should serialize/deserialize JSON data."""
        with tempfile.TemporaryDirectory() as tmpdir:
            org_id = uuid4()
            conv_id = uuid4()
            state = ConversionState(org_id, conv_id, storage_root=tmpdir)
            state.ensure_dir()
            data = {"vars": ["protocol_name", "operator_name"], "count": 2}
            state.write_json("meta.json", data)
            result = state.read_json("meta.json")
            assert result == data

    def test_preview_url(self):
        """Should return correct preview URL."""
        org_id = uuid4()
        conv_id = uuid4()
        state = ConversionState(org_id, conv_id)
        assert state.preview_url == f"/science/templates/conversions/{conv_id}/preview.pdf"

    def test_template_url(self):
        """Should return correct template download URL."""
        org_id = uuid4()
        conv_id = uuid4()
        state = ConversionState(org_id, conv_id)
        assert state.template_url == f"/science/templates/conversions/{conv_id}/template.docx"


# ── _to_pdf tests ──


class TestToPdf:
    @pytest.mark.asyncio
    async def test_pdf_passthrough(self):
        """PDF input should be returned as-is."""
        fake_pdf = b"%PDF-1.4 fake content"
        result = await _to_pdf(fake_pdf, "document.pdf")
        assert result == fake_pdf

    @pytest.mark.asyncio
    async def test_image_passthrough(self):
        """Image input should be returned as-is (fed to model directly)."""
        fake_img = b"\x89PNG fake image"
        for ext in ("image.png", "photo.jpg", "scan.jpeg"):
            result = await _to_pdf(fake_img, ext)
            assert result == fake_img


# ── _try_render tests ──


class TestTryRender:
    def test_valid_template_renders(self):
        """A template with known variables should render without jinja remnants."""
        from docx import Document
        from io import BytesIO

        # Create a minimal template with a known variable
        doc = Document()
        doc.add_paragraph("Protocol: {{ protocol_name }}")
        buf = BytesIO()
        doc.save(buf)
        template_bytes = buf.getvalue()

        result = _try_render(template_bytes, "SOP")
        assert result.jinja_remnants == []

    def test_invalid_jinja_detected(self):
        """A template with malformed Jinja2 should report remnants."""
        from docx import Document
        from io import BytesIO

        doc = Document()
        # Deliberately malformed — unclosed tag
        doc.add_paragraph("Protocol: {{ broken_var ")
        buf = BytesIO()
        doc.save(buf)
        template_bytes = buf.getvalue()

        result = _try_render(template_bytes, "SOP")
        # The render should either fail or leave remnants
        assert result.jinja_remnants or result.render_error

    def test_plain_text_template(self):
        """A template with no Jinja2 should render cleanly."""
        from docx import Document
        from io import BytesIO

        doc = Document()
        doc.add_paragraph("This is plain text with no variables.")
        buf = BytesIO()
        doc.save(buf)
        template_bytes = buf.getvalue()

        result = _try_render(template_bytes, "SOP")
        assert result.jinja_remnants == []
        assert not result.render_error


# ── MAX_VERIFICATION_ROUNDS constant ──


class TestConstants:
    def test_max_verification_rounds_is_positive(self):
        assert MAX_VERIFICATION_ROUNDS > 0
        assert MAX_VERIFICATION_ROUNDS <= 5  # sanity cap
