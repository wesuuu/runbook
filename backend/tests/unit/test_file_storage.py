"""Tests for the FileStorageService."""

from io import BytesIO
from uuid import uuid4

import pytest
from fastapi import HTTPException, UploadFile

from app.services.core.file_storage import FileStorageService


def _make_upload(filename: str, content: bytes, content_type: str) -> UploadFile:
    return UploadFile(
        filename=filename,
        file=BytesIO(content),
        headers={"content-type": content_type},
    )


@pytest.mark.asyncio
async def test_store_and_resolve(tmp_path):
    svc = FileStorageService(storage_root=str(tmp_path))
    stored = await svc.store_file(
        _make_upload("report.pdf", b"%PDF-content", "application/pdf"),
        base_dir="attachments",
        org_id=uuid4(),
        path_segments=["run-1"],
        allowed_types={"application/pdf"},
        max_size_bytes=25 * 1024 * 1024,
    )

    assert stored.original_filename == "report.pdf"
    assert stored.mime_type == "application/pdf"
    assert stored.size_bytes == len(b"%PDF-content")
    assert stored.relative_path.endswith(".pdf")

    full_path = svc.resolve_path(stored.relative_path)
    assert full_path.exists()
    assert full_path.read_bytes() == b"%PDF-content"


@pytest.mark.asyncio
async def test_rejects_disallowed_type(tmp_path):
    svc = FileStorageService(storage_root=str(tmp_path))
    with pytest.raises(HTTPException) as exc_info:
        await svc.store_file(
            _make_upload("malware.exe", b"evil", "application/x-msdownload"),
            base_dir="attachments",
            org_id=uuid4(),
            path_segments=[],
            allowed_types={"application/pdf"},
            max_size_bytes=25 * 1024 * 1024,
        )
    assert exc_info.value.status_code == 422
    assert "Unsupported file type" in exc_info.value.detail


@pytest.mark.asyncio
async def test_rejects_oversized_file(tmp_path):
    svc = FileStorageService(storage_root=str(tmp_path))
    with pytest.raises(HTTPException) as exc_info:
        await svc.store_file(
            _make_upload("big.pdf", b"x" * 1000, "application/pdf"),
            base_dir="attachments",
            org_id=uuid4(),
            path_segments=[],
            allowed_types={"application/pdf"},
            max_size_bytes=100,
        )
    assert exc_info.value.status_code == 413
    assert "too large" in exc_info.value.detail


@pytest.mark.asyncio
async def test_creates_nested_directories(tmp_path):
    svc = FileStorageService(storage_root=str(tmp_path))
    org_id = uuid4()
    stored = await svc.store_file(
        _make_upload("data.csv", b"a,b,c\n1,2,3", "text/csv"),
        base_dir="attachments",
        org_id=org_id,
        path_segments=["run-abc", "step-1"],
        allowed_types={"text/csv"},
        max_size_bytes=1024,
    )
    # Path should contain org_id/attachments/run-abc/step-1/
    assert str(org_id) in stored.relative_path
    assert "attachments" in stored.relative_path


@pytest.mark.asyncio
async def test_delete_file(tmp_path):
    svc = FileStorageService(storage_root=str(tmp_path))
    stored = await svc.store_file(
        _make_upload("temp.txt", b"hello", "text/plain"),
        base_dir="attachments",
        org_id=uuid4(),
        path_segments=[],
        allowed_types={"text/plain"},
        max_size_bytes=1024,
    )
    full_path = svc.resolve_path(stored.relative_path)
    assert full_path.exists()

    svc.delete_file(stored.relative_path)
    assert not full_path.exists()


@pytest.mark.asyncio
async def test_delete_nonexistent_file_no_error(tmp_path):
    svc = FileStorageService(storage_root=str(tmp_path))
    # Should not raise
    svc.delete_file("nonexistent/path/file.txt")
