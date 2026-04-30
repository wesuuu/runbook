import os
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID, uuid4

from fastapi import HTTPException, UploadFile, status

IMAGE_MIME_TYPES = {"image/jpeg", "image/png", "image/tiff", "image/webp"}


@dataclass
class StoredFile:
    """Metadata returned after successfully storing a file."""

    relative_path: str
    original_filename: str
    mime_type: str
    size_bytes: int


class FileStorageService:
    """Shared file storage service for uploads.

    Handles MIME-type validation, size limits, path construction, and
    writing to the local filesystem.  Callers provide the logical
    namespace (``base_dir``, ``org_id``, ``path_segments``); this
    service owns the physical layout.

    Directory layout::

        {storage_root}/{org_id}/{base_dir}/{segment0}/{segment1}/…/{uuid}{ext}
    """

    def __init__(self, storage_root: str = "./uploads") -> None:
        self.storage_root = Path(storage_root)

    async def store_file(
        self,
        file: UploadFile,
        *,
        base_dir: str,
        org_id: UUID,
        path_segments: list[str],
        allowed_types: set[str],
        max_size_bytes: int,
    ) -> StoredFile:
        content_type = file.content_type or ""
        if content_type not in allowed_types:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=(
                    f"Unsupported file type: {content_type}. "
                    f"Allowed: {', '.join(sorted(allowed_types))}"
                ),
            )

        content = await file.read()
        if len(content) > max_size_bytes:
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail=(
                    f"File too large ({len(content)} bytes). "
                    f"Maximum: {max_size_bytes} bytes."
                ),
            )

        ext = os.path.splitext(file.filename or "file")[1].lower() or ".bin"
        file_uuid = uuid4()
        parts = [str(org_id), base_dir] + path_segments + [f"{file_uuid}{ext}"]
        relative_path = str(Path(*parts))

        full_path = self.storage_root / relative_path
        full_path.parent.mkdir(parents=True, exist_ok=True)
        full_path.write_bytes(content)

        return StoredFile(
            relative_path=relative_path,
            original_filename=file.filename or f"file{ext}",
            mime_type=content_type,
            size_bytes=len(content),
        )

    def resolve_path(self, relative_path: str) -> Path:
        """Resolve a relative path to an absolute path under storage root.

        Raises ValueError if the resolved path escapes the storage root
        (path traversal protection).
        """
        full = (self.storage_root / relative_path).resolve()
        root = self.storage_root.resolve()
        if not str(full).startswith(str(root) + os.sep) and full != root:
            raise ValueError("Path traversal detected")
        return full

    def resolve_path_for_org(self, relative_path: str, org_id: UUID | None) -> Path:
        """Resolve a file path, enforcing org or system scope.

        - System files (org_id=None): path must start with 'system/'
        - Org files: first path segment must be the org_id

        Raises PermissionError if the path doesn't match the expected scope.
        """
        full = self.resolve_path(relative_path)  # traversal guard included
        parts = Path(relative_path).parts
        if not parts:
            raise PermissionError("Empty file path")
        if org_id is None:
            if parts[0] != "system":
                raise PermissionError("System templates must be under system/")
        else:
            if parts[0] != str(org_id):
                raise PermissionError("Access denied to file outside org scope")
        return full

    def delete_file(self, relative_path: str) -> None:
        path = self.resolve_path(relative_path)
        if path.exists():
            path.unlink()
