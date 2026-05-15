"""QA-0008 permutation suite.

Each Pn renders against the templates it's configured for, then asserts
that expected_on substrings appear and expected_off substrings do not.

Pass --write-artifacts to also emit .docx + .pdf into
tests/fixtures/template-permutations/rendered/<Pn>/.
"""
from __future__ import annotations

import io
import subprocess
from pathlib import Path

import pytest
from docx import Document

from app.services.protocols.template_engine import build_context, render_to_docx
from tests.integration.fixtures.template_permutations import builders

SOP_PATH = (
    Path(__file__).resolve().parents[2]
    / "app/services/documents/templates/sop_default.docx"
)
BR_PATH = (
    Path(__file__).resolve().parents[2]
    / "app/services/documents/templates/batch_record_default.docx"
)
ARTIFACT_ROOT = (
    Path(__file__).resolve().parents[3]
    / "tests/fixtures/template-permutations/rendered"
)


def _doc_text(blob: bytes) -> str:
    d = Document(io.BytesIO(blob))
    parts = [p.text for p in d.paragraphs]
    for t in d.tables:
        for row in t.rows:
            for cell in row.cells:
                parts.append(cell.text)
    return "\n".join(parts)


def _convert_to_pdf(docx_path: Path) -> Path | None:
    try:
        subprocess.run(
            ["libreoffice", "--headless", "--convert-to", "pdf",
             "--outdir", str(docx_path.parent), str(docx_path)],
            check=True, capture_output=True, timeout=60,
        )
    except (FileNotFoundError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return None
    pdf_path = docx_path.with_suffix(".pdf")
    return pdf_path if pdf_path.exists() else None


@pytest.mark.parametrize("builder_name,template_key,template_path", [
    ("build_p1", "batch_record", str(BR_PATH)),
    ("build_p2", "sop", str(SOP_PATH)),
    ("build_p3", "sop", str(SOP_PATH)),
    ("build_p4", "batch_record", str(BR_PATH)),
    ("build_p5", "batch_record", str(BR_PATH)),
    ("build_p6", "batch_record", str(BR_PATH)),
])
def test_permutation_renders(builder_name, template_key, template_path, write_artifacts):
    built = getattr(builders, builder_name)()
    if template_key not in built.renders_against:
        pytest.skip(f"{built.name} not configured to render against {template_key}")

    ctx, unresolved = build_context(**built.kwargs)
    ctx.setdefault("approval", None)
    ctx.setdefault("approval_history", [])
    ctx.setdefault("unapproved_warning", "")
    if built.context_overrides:
        ctx.update(built.context_overrides)

    assert unresolved == [], f"{built.name}: unresolved tokens: {unresolved}"

    docx_bytes = render_to_docx(template_path, ctx)
    text = _doc_text(docx_bytes)

    for needle in built.expected_on:
        assert needle in text, f"{built.name}/{template_key}: missing '{needle}'"
    for needle in built.expected_off:
        assert needle not in text, f"{built.name}/{template_key}: unexpected '{needle}'"

    if write_artifacts:
        outdir = ARTIFACT_ROOT / built.name
        outdir.mkdir(parents=True, exist_ok=True)
        docx_path = outdir / f"{template_key}.docx"
        docx_path.write_bytes(docx_bytes)
        _convert_to_pdf(docx_path)
