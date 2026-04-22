import enum
import uuid
from datetime import datetime
from typing import Any, List, Optional

from pgvector.sqlalchemy import Vector
from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base
from app.models.mixins import TimestampMixin, UUIDMixin

# Documents stuck in PROCESSING longer than this are considered stalled
# and eligible for recovery by another pod on startup.
STALE_PROCESSING_SECONDS = 300  # 5 minutes


# --- Constants ---

ALLOWED_DOCUMENT_TYPES = {
    "application/pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "text/plain",
    "text/markdown",
    "application/rtf",
    "image/jpeg",
    "image/png",
    "image/heic",
    "text/html",
}

MAX_DOCUMENT_SIZE_BYTES = 50 * 1024 * 1024  # 50 MB
MAX_URL_RESPONSE_BYTES = 10 * 1024 * 1024   # 10 MB

# Map MIME types to expected file extensions
MIME_EXTENSION_MAP = {
    "application/pdf": {".pdf"},
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": {
        ".docx",
    },
    "text/plain": {".txt", ".text"},
    "text/markdown": {".md", ".markdown"},
    "application/rtf": {".rtf"},
    "image/jpeg": {".jpg", ".jpeg"},
    "image/png": {".png"},
    "image/heic": {".heic"},
    "text/html": {".html", ".htm"},
}

# Magic byte signatures for file validation
MAGIC_BYTES = {
    "application/pdf": b"%PDF-",
    "image/png": b"\x89PNG\r\n\x1a\n",
    "image/jpeg": b"\xff\xd8\xff",
}


class DocumentStatus(str, enum.Enum):
    UPLOADED = "UPLOADED"
    QUEUED = "QUEUED"
    PROCESSING = "PROCESSING"
    INDEXED = "INDEXED"      # Legacy — treated as READY
    ENRICHED = "ENRICHED"    # Legacy — treated as READY
    READY = "READY"
    FAILED = "FAILED"


# Statuses that indicate a document is viewable (has content)
VIEWABLE_STATUSES = {
    DocumentStatus.INDEXED.value,
    DocumentStatus.ENRICHED.value,
    DocumentStatus.READY.value,
}


def validate_file_content(content: bytes, claimed_mime: str) -> bool:
    """Validate file content matches claimed MIME type via magic bytes.

    For types with known magic byte signatures, checks that the file
    starts with the expected bytes. For DOCX, validates it is a valid
    ZIP containing [Content_Types].xml. Returns True if validation
    passes or if no signature check is available for the type.
    """
    if claimed_mime in MAGIC_BYTES:
        return content.startswith(MAGIC_BYTES[claimed_mime])

    if claimed_mime == (
        "application/vnd.openxmlformats-officedocument"
        ".wordprocessingml.document"
    ):
        # DOCX files are ZIP archives starting with PK signature
        return content[:2] == b"PK"

    # No magic byte check available — allow
    return True


# --- Models ---


class Document(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "documents"

    org_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id"), nullable=False
    )
    project_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("projects.id"), nullable=True
    )
    uploaded_by_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id"), nullable=False
    )
    title: Mapped[str] = mapped_column(String(150), nullable=False)
    original_filename: Mapped[str] = mapped_column(String, nullable=False)
    mime_type: Mapped[str] = mapped_column(String, nullable=False)
    file_size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    file_path: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(
        String, default=DocumentStatus.UPLOADED.value,
        server_default="UPLOADED", nullable=False,
    )
    page_count: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    tags: Mapped[list[Any]] = mapped_column(
        JSONB, default=list, server_default="[]", nullable=False
    )
    doc_metadata: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, default=dict, server_default="{}", nullable=False
    )
    error_message: Mapped[Optional[str]] = mapped_column(
        String, nullable=True
    )
    source_url: Mapped[Optional[str]] = mapped_column(
        String, nullable=True
    )
    processing_started_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    structure_metadata: Mapped[Optional[dict[str, Any]]] = mapped_column(
        JSONB, nullable=True
    )

    # Relationships
    chunks: Mapped[List["DocumentChunk"]] = relationship(
        back_populates="document",
        cascade="all, delete-orphan",
        order_by="DocumentChunk.chunk_index",
    )


# Embedding dimensions — matches nomic-embed-text (768d) and
# OpenAI text-embedding-3-small (1536d). We use 1536 as the column
# size since it's the max we expect; shorter vectors are zero-padded
# by pgvector automatically.
EMBEDDING_DIMENSIONS = 1536


class DocumentChunk(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "document_chunks"
    __table_args__ = (
        Index(
            "ix_chunk_embedding",
            "embedding",
            postgresql_using="hnsw",
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
    )

    document_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), nullable=False
    )
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    token_count: Mapped[int] = mapped_column(Integer, nullable=False)
    page_number: Mapped[Optional[int]] = mapped_column(
        Integer, nullable=True
    )
    chunk_metadata: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, default=dict, server_default="{}", nullable=False
    )
    embedding = mapped_column(
        Vector(EMBEDDING_DIMENSIONS), nullable=True
    )

    # Relationships
    document: Mapped["Document"] = relationship(back_populates="chunks")
