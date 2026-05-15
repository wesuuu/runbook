"""QA-0008: render_to_docx must swap reviewer_initials placeholder to InlineImage when signature present."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from app.services.protocols.template_engine import render_to_docx


def test_render_to_docx_swaps_reviewer_initials_when_signature_image_present(tmp_path):
    template_path = (
        Path(__file__).parent.parent.parent
        / "app/services/documents/templates/batch_record_default.docx"
    )
    sig_path = tmp_path / "sig.png"
    # Build a minimal context with reviewer + signature
    ctx = {
        "protocol_name": "P",
        "is_role_based": True,
        "steps": [],
        "roles": [
            {
                "role_name": "Op",
                "sop_header": "",
                "br_header": "",
                "steps": [
                    {
                        "id": "s1",
                        "name": "A",
                        "_reviewer_user_id": "u-2",
                        "_reviewer_name": "Bob Reviewer",
                        "reviewer_initials": "BR",
                        "reviewed_at": "2026-05-15T09:00:00Z",
                    }
                ],
            }
        ],
        "notes": [],
        "figures": [],
        "non_image_attachments": [],
        # signature blob for user u-2 (production shape — see
        # _build_user_signatures in protocol_pdfs.py)
        "_user_signatures": {"u-2": {"signature_initials_path": str(sig_path)}},
    }
    # Drop a fake PNG so InlineImage construction can read it
    sig_path.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\0" * 64)

    with patch("app.services.protocols.template_engine.InlineImage") as mock_inline:
        mock_inline.return_value = MagicMock(name="InlineImage")
        out = render_to_docx(str(template_path), ctx)
        # InlineImage should have been called at least once (for reviewer + at most once for operator).
        called_with_paths = [
            c.kwargs.get("image_descriptor") or (c.args[1] if len(c.args) > 1 else None)
            for c in mock_inline.call_args_list
        ]
        assert any(
            str(sig_path) in str(p) for p in called_with_paths
        ), "reviewer signature path was not passed to InlineImage"
    assert isinstance(out, bytes) and len(out) > 0
