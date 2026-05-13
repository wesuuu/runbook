import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from app.services.documents.extraction import extract_job


def _write_artifacts(output_dir: Path, *, markdown: str, image_count: int,
                     page_count: int, flags=None):
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "refined.md").write_text(markdown)
    (output_dir / "images").mkdir(parents=True, exist_ok=True)
    for n in range(image_count):
        (output_dir / "images" / f"{n}.png").write_bytes(b"\x89PNG fake")
    (output_dir / "result.json").write_text(json.dumps({
        "page_count": page_count,
        "image_count": image_count,
        "flags": flags or [],
        "ocr_engine": "easyocr",
        "source_format": "PDF",
    }))


@pytest.mark.asyncio
async def test_run_extraction_invokes_subprocess_with_expected_args(tmp_path):
    captured: dict = {}

    async def _fake_exec(*argv, **kwargs):
        captured["argv"] = argv
        captured["kwargs"] = kwargs
        out_dir = Path(argv[argv.index("--output-dir") + 1])
        _write_artifacts(out_dir, markdown="# Hi\n\n![](images/0.png)",
                         image_count=1, page_count=2)
        proc = MagicMock()
        proc.returncode = 0
        proc.communicate = AsyncMock(return_value=(b"", b""))
        return proc

    fake_doc = MagicMock(
        id=uuid4(), mime_type="application/pdf",
        file_path="uploads/x.pdf",
        page_count=None, status="UPLOADED",
    )

    with patch.object(extract_job, "asyncio") as fake_asyncio, \
         patch.object(extract_job, "_load_and_claim_document",
                      AsyncMock(return_value=(fake_doc, MagicMock()))), \
         patch.object(extract_job, "_persist_success", AsyncMock()) as persist, \
         patch.object(extract_job, "_resolve_paths",
                      return_value=(Path("/tmp/in.pdf"), tmp_path / "out")):
        fake_asyncio.create_subprocess_exec = AsyncMock(side_effect=_fake_exec)
        fake_asyncio.subprocess = MagicMock()
        fake_asyncio.subprocess.PIPE = -1
        await extract_job.run_extraction(fake_doc.id)

    argv = captured["argv"]
    assert "--input" in argv
    assert "--output-dir" in argv
    assert "--num-threads" in argv
    persist.assert_awaited()


@pytest.mark.asyncio
async def test_run_extraction_marks_failed_on_nonzero_exit(tmp_path):
    async def _fake_exec(*argv, **kwargs):
        proc = MagicMock()
        proc.returncode = 2
        proc.communicate = AsyncMock(return_value=(b"", b"bad input"))
        return proc

    fake_doc = MagicMock(
        id=uuid4(), mime_type="application/pdf",
        file_path="uploads/x.pdf", status="UPLOADED",
    )

    with patch.object(extract_job, "asyncio") as fake_asyncio, \
         patch.object(extract_job, "_load_and_claim_document",
                      AsyncMock(return_value=(fake_doc, MagicMock()))), \
         patch.object(extract_job, "_persist_failure", AsyncMock()) as fail, \
         patch.object(extract_job, "_persist_success", AsyncMock()) as ok, \
         patch.object(extract_job, "_resolve_paths",
                      return_value=(Path("/tmp/in.pdf"), tmp_path / "out")):
        fake_asyncio.create_subprocess_exec = AsyncMock(side_effect=_fake_exec)
        fake_asyncio.subprocess = MagicMock()
        fake_asyncio.subprocess.PIPE = -1
        await extract_job.run_extraction(fake_doc.id)

    fail.assert_awaited()
    ok.assert_not_awaited()
