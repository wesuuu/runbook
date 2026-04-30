from pathlib import Path
from unittest.mock import MagicMock

import pytest
from docxtpl import DocxTemplate, InlineImage, RichText

from app.services.protocols.template_engine import _resolve_initials


def test_returns_inline_image_when_signature_path_exists(tmp_path):
    sig = tmp_path / "sig.png"
    sig.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 8)
    docx = MagicMock(spec=DocxTemplate)

    result = _resolve_initials(
        user_id="u1",
        name="John Smith",
        user_signatures={"u1": str(sig)},
        docx=docx,
    )
    assert isinstance(result, InlineImage)


def test_falls_back_to_cursive_richtext_when_no_signature():
    docx = MagicMock(spec=DocxTemplate)

    result = _resolve_initials(
        user_id="u1",
        name="John Smith",
        user_signatures={},
        docx=docx,
    )
    assert isinstance(result, RichText)
    # docxtpl RichText stores its XML; the font name should be embedded
    assert "Dancing Script" in result.xml or "DancingScript" in result.xml


def test_falls_back_when_path_is_missing_from_disk(tmp_path):
    docx = MagicMock(spec=DocxTemplate)
    missing_path = tmp_path / "does-not-exist.png"

    result = _resolve_initials(
        user_id="u1",
        name="John Smith",
        user_signatures={"u1": str(missing_path)},
        docx=docx,
    )
    assert isinstance(result, RichText)


def test_falls_back_when_user_unknown():
    docx = MagicMock(spec=DocxTemplate)

    result = _resolve_initials(
        user_id="not-in-map",
        name="John Smith",
        user_signatures={"someone-else": "/path/that/exists"},
        docx=docx,
    )
    assert isinstance(result, RichText)
