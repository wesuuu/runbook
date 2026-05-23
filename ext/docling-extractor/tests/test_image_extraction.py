"""Regression test: image input must extract without Errno 2 (BUG-0009 #4).

Uses a tiny solid-color PNG and runs the pipeline with do_ocr=False, so
the test does not depend on the EasyOCR model cache being present.
"""

import json
from pathlib import Path

import pytest

# Skip cleanly if docling cannot be imported in the test environment
# (e.g. CI without the heavy model deps). The bug is in the docling
# call path, so a mock would not catch it - we must run the real call.
docling = pytest.importorskip("docling", reason="docling not installed")

from docling_extractor.pipeline import run_pipeline


FIXTURE = Path(__file__).parent / "fixtures" / "tiny.png"


def test_runs_pipeline_on_image_without_errno_2(tmp_path):
    """Calling run_pipeline on a PNG must succeed (no FileNotFoundError,
    no '[Errno 2]'). Output content quality is not asserted; we only
    care that the pipeline reaches a returnable ExtractionResult."""
    result = run_pipeline(FIXTURE, num_threads=1)
    assert result is not None
    assert isinstance(result.markdown, str)
    assert isinstance(result.page_count, int)


def test_extract_cli_on_image_writes_artifacts(tmp_path):
    """Drives extract.main() on the PNG fixture and asserts artifacts."""
    import sys

    from extract import main

    output_dir = tmp_path / "out"
    sys.argv = [
        "extract.py",
        "--input", str(FIXTURE),
        "--output-dir", str(output_dir),
        "--num-threads", "1",
    ]
    rc = main()
    assert rc == 0
    assert (output_dir / "refined.md").exists()
    assert (output_dir / "result.json").exists()
    result_json = json.loads((output_dir / "result.json").read_text())
    assert result_json.get("source_format") == "IMAGE"
    refined = (output_dir / "refined.md").read_text()
    assert isinstance(refined, str)
