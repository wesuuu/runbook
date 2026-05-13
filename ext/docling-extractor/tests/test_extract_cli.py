import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


def _fake_docling_doc(markdown: str, page_count: int):
    doc = MagicMock()
    doc.export_to_markdown.return_value = markdown
    doc.num_pages.return_value = page_count
    doc.pictures = []
    return doc


def _run_cli(input_path: Path, output_dir: Path, num_threads: int = 4):
    """Invoke extract.main() with patched docling for deterministic tests."""
    import extract

    convert_result = MagicMock()
    convert_result.document = _fake_docling_doc("# Title\n\nBody.", 3)

    with patch.object(extract, "DocumentConverter") as ConverterCls:
        ConverterCls.return_value.convert.return_value = convert_result
        argv = [
            "extract.py",
            "--input", str(input_path),
            "--output-dir", str(output_dir),
            "--num-threads", str(num_threads),
        ]
        with patch.object(sys, "argv", argv):
            return extract.main()


def test_cli_writes_artifacts(tmp_path: Path):
    pdf = tmp_path / "x.pdf"
    pdf.write_bytes(b"%PDF-1.4 fake")
    out = tmp_path / "out"

    exit_code = _run_cli(pdf, out)
    assert exit_code == 0

    refined = (out / "refined.md").read_text()
    assert refined == "# Title\n\nBody."
    result = json.loads((out / "result.json").read_text())
    assert result["page_count"] == 3
    assert result["image_count"] == 0
    assert result["ocr_engine"] == "easyocr"
    assert result["source_format"] == "PDF"


def test_cli_creates_output_dir_if_missing(tmp_path: Path):
    pdf = tmp_path / "x.pdf"
    pdf.write_bytes(b"%PDF-1.4 fake")
    out = tmp_path / "deeper" / "out"

    exit_code = _run_cli(pdf, out)
    assert exit_code == 0
    assert (out / "refined.md").exists()


def test_cli_missing_input_returns_nonzero(tmp_path: Path):
    out = tmp_path / "out"
    import extract
    argv = ["extract.py", "--input", str(tmp_path / "missing.pdf"),
            "--output-dir", str(out)]
    with patch.object(sys, "argv", argv):
        exit_code = extract.main()
    assert exit_code != 0
