import io
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from docxtpl import DocxTemplate, InlineImage

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


def test_falls_back_to_text_initials_when_no_signature():
    docx = MagicMock(spec=DocxTemplate)

    result = _resolve_initials(
        user_id="u1",
        name="John Smith",
        user_signatures={},
        docx=docx,
    )
    assert result == "J.S."


def test_falls_back_when_path_is_missing_from_disk(tmp_path):
    docx = MagicMock(spec=DocxTemplate)
    missing_path = tmp_path / "does-not-exist.png"

    result = _resolve_initials(
        user_id="u1",
        name="John Smith",
        user_signatures={"u1": str(missing_path)},
        docx=docx,
    )
    assert result == "J.S."


def test_falls_back_when_user_unknown():
    docx = MagicMock(spec=DocxTemplate)

    result = _resolve_initials(
        user_id="not-in-map",
        name="John Smith",
        user_signatures={"someone-else": "/path/that/exists"},
        docx=docx,
    )
    assert result == "J.S."


def test_render_to_docx_swaps_initials_to_inline_image(tmp_path):
    """Smoke: when a step has _initials_user_id and that user has a
    signature path on the user_signatures map (passed via render_to_docx),
    the rendered docx must embed the image rather than the text fallback."""
    from app.services.protocols.template_engine import render_to_docx

    sig = tmp_path / "sig.png"
    # Minimal valid PNG (1x1 RGBA pixel) — bytes generated via
    # struct/zlib so the IDAT chunk decompresses cleanly.
    sig.write_bytes(
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00"
        b"\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\x0bIDATx"
        b"\x9cc\xf8\x0f\x04\x00\t\xfb\x03\xfd\xfb^k+\x00\x00\x00\x00IEND"
        b"\xaeB`\x82"
    )

    template_path = (
        Path(__file__).resolve().parent.parent.parent
        / "app/services/documents/templates/batch_record_default.docx"
    )

    step = {
        "_step_id": "s1",
        "name": "Step 1",
        "description": "Do thing",
        "initials": "J.S.",
        "_initials_user_id": "u1",
        "_initials_name": "John Smith",
        "value_display": "",
        "notes_display": "",
    }
    context = {
        "protocol_name": "Test",
        # The default batch-record template iterates roles[].steps; place
        # the step there so {{ step.initials }} actually renders into the
        # document. _swap walks both top-level steps and roles[].steps.
        "steps": [step],
        "_user_signatures": {"u1": str(sig)},
        "roles": [
            {
                "name": "Role 1",
                "br_header": "",
                "steps": [step],
            }
        ],
        "notes": [],
        "figures": [],
        "non_image_attachments": [],
        # F-0087: BR template references {{ run.outcome }} and
        # run.outcome_notes; build_context() emits {"run": {...}}, but this
        # test constructs the context manually so seed an empty dict.
        "run": {},
        "signoffs": {},
        "protocol_approvals": {},
    }

    docx_bytes = render_to_docx(template_path, context)
    # docx is a zip; embedded images appear under word/media/
    import zipfile

    with zipfile.ZipFile(io.BytesIO(docx_bytes)) as z:
        media = [n for n in z.namelist() if n.startswith("word/media/")]
        assert media, "expected at least one embedded media file"
