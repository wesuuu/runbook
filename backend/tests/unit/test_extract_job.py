import asyncio
import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
import pytest_asyncio

from app.models.library import DocumentStatus
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


def _make_fake_asyncio(fake_exec):
    """Build a fake asyncio namespace for patching extract_job.asyncio.

    Provides create_subprocess_exec, create_task (returns an awaitable
    no-op future), subprocess.PIPE, and wait_for (passes through to real
    asyncio so HeartbeatWatchdog's internal wait_for still works when the
    watchdog module is patched separately).
    """
    fake = MagicMock()
    fake.create_subprocess_exec = AsyncMock(side_effect=fake_exec)
    fake.subprocess = MagicMock()
    fake.subprocess.PIPE = -1
    # create_task must return an awaitable (asyncio.Future resolving None)
    fake.create_task = lambda coro: asyncio.ensure_future(coro)
    fake.TimeoutError = asyncio.TimeoutError
    fake.wait_for = asyncio.wait_for
    return fake


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
        heartbeat_token="tok",
    )

    with patch.object(extract_job, "asyncio", _make_fake_asyncio(_fake_exec)), \
         patch.object(extract_job, "_load_and_claim_document",
                      AsyncMock(return_value=(fake_doc, MagicMock()))), \
         patch.object(extract_job, "_persist_success", AsyncMock()) as persist, \
         patch.object(extract_job, "_resolve_paths",
                      return_value=(Path("/tmp/in.pdf"), tmp_path / "out")):
        await extract_job.run_extraction(fake_doc.id)

    argv = captured["argv"]
    assert "--input" in argv
    assert "--output-dir" in argv
    assert "--num-threads" in argv
    assert "--heartbeat-url" in argv
    assert "--heartbeat-token" in argv
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
        heartbeat_token="tok",
    )

    with patch.object(extract_job, "asyncio", _make_fake_asyncio(_fake_exec)), \
         patch.object(extract_job, "_load_and_claim_document",
                      AsyncMock(return_value=(fake_doc, MagicMock()))), \
         patch.object(extract_job, "_persist_failure", AsyncMock()) as fail, \
         patch.object(extract_job, "_persist_success", AsyncMock()) as ok, \
         patch.object(extract_job, "_resolve_paths",
                      return_value=(Path("/tmp/in.pdf"), tmp_path / "out")):
        await extract_job.run_extraction(fake_doc.id)

    fail.assert_awaited()
    ok.assert_not_awaited()


@pytest.mark.asyncio
async def test_late_success_is_discarded_if_watchdog_already_failed(
    async_session, seed_document_extracting, tmp_path
):
    """Subprocess finishes rc=0 but the doc was already marked FAILED
    by the watchdog. The artifacts should be removed and the row left
    in its FAILED state."""
    doc = seed_document_extracting
    doc.status = DocumentStatus.FAILED.value
    doc.heartbeat_token = None  # watchdog already cleared it
    await async_session.commit()

    output_dir = tmp_path / str(doc.id)
    output_dir.mkdir()
    (output_dir / "refined.md").write_text("# hello")
    (output_dir / "result.json").write_text(
        '{"page_count": 1, "image_count": 0, "flags": [],'
        ' "ocr_engine": "easyocr", "source_format": "pdf"}'
    )
    (output_dir / "images").mkdir()

    await extract_job._persist_success(
        async_session, doc, job=None, output_dir=output_dir
    )

    await async_session.refresh(doc)
    assert doc.status == DocumentStatus.FAILED.value


@pytest.mark.asyncio
async def test_run_extraction_honours_heartbeat_base_url_override(tmp_path):
    """When the caller passes ``heartbeat_base_url`` the subprocess receives
    a ``--heartbeat-url`` derived from that override, not the settings
    default. This is the path the upload endpoints use to wire the
    subprocess to the port uvicorn actually bound."""
    captured: dict = {}

    async def _fake_exec(*argv, **kwargs):
        captured["argv"] = argv
        out_dir = Path(argv[argv.index("--output-dir") + 1])
        _write_artifacts(out_dir, markdown="# Hi", image_count=0, page_count=1)
        proc = MagicMock()
        proc.returncode = 0
        proc.communicate = AsyncMock(return_value=(b"", b""))
        return proc

    fake_doc = MagicMock(
        id=uuid4(), mime_type="application/pdf",
        file_path="uploads/x.pdf", page_count=None, status="UPLOADED",
        heartbeat_token="tok",
    )

    with patch.object(extract_job, "asyncio", _make_fake_asyncio(_fake_exec)), \
         patch.object(extract_job, "_load_and_claim_document",
                      AsyncMock(return_value=(fake_doc, MagicMock()))), \
         patch.object(extract_job, "_persist_success", AsyncMock()), \
         patch.object(extract_job, "_resolve_paths",
                      return_value=(Path("/tmp/in.pdf"), tmp_path / "out")):
        await extract_job.run_extraction(
            fake_doc.id,
            heartbeat_base_url="http://127.0.0.1:8030/",
        )

    argv = captured["argv"]
    url = argv[argv.index("--heartbeat-url") + 1]
    assert url == f"http://127.0.0.1:8030/internal/extraction/{fake_doc.id}/heartbeat"
