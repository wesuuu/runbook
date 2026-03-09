import uuid
from typing import Any, List, Optional

from sqlalchemy import Boolean, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base
from app.models.mixins import UUIDMixin, TimestampMixin


SUPPORTED_PROVIDERS = ("ollama", "anthropic", "google", "openai")

SUPPORTED_CAPABILITIES = ("vision", "audio", "text")

DEFAULT_CONFIGS = {
    "vision": {
        "provider": "ollama",
        "model_name": "llama3.2-vision",
    },
    "audio": {
        "provider": "ollama",
        "model_name": "whisper",
    },
    "text": {
        "provider": "ollama",
        "model_name": "llama3.2",
    },
}


class AiProviderConfig(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "ai_provider_configs"
    __table_args__ = (
        UniqueConstraint("capability", name="uq_ai_capability"),
    )

    capability: Mapped[str] = mapped_column(
        String, nullable=False
    )
    provider: Mapped[str] = mapped_column(
        String, nullable=False
    )
    model_name: Mapped[str] = mapped_column(
        String, nullable=False
    )
    api_key: Mapped[Optional[str]] = mapped_column(
        String, nullable=True
    )
    base_url: Mapped[Optional[str]] = mapped_column(
        String, nullable=True
    )
    is_enabled: Mapped[bool] = mapped_column(
        Boolean, default=True, nullable=False
    )


ALLOWED_IMAGE_TYPES = (
    "image/jpeg",
    "image/png",
    "image/webp",
    "image/heic",
    "image/heif",
    "image/tiff",
)

MAX_IMAGE_SIZE_BYTES = 20 * 1024 * 1024  # 20 MB


class RunImage(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "run_images"

    run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("runs.id", ondelete="CASCADE"), nullable=False
    )
    step_id: Mapped[str] = mapped_column(String, nullable=False)
    file_path: Mapped[str] = mapped_column(String, nullable=False)
    original_filename: Mapped[str] = mapped_column(String, nullable=False)
    mime_type: Mapped[str] = mapped_column(String, nullable=False)
    file_size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    uploaded_by_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("users.id"), nullable=True
    )
    parameter_tags: Mapped[Optional[List[str]]] = mapped_column(
        JSONB, nullable=True, default=None
    )

    # Relationships
    conversations: Mapped[List["ImageConversation"]] = relationship(
        back_populates="image", cascade="all, delete-orphan"
    )


class ConversationStatus(str):
    PENDING = "pending"
    ANALYZING = "analyzing"
    NEEDS_CLARIFICATION = "needs_clarification"
    CONFIRMED = "confirmed"
    FAILED = "failed"


class ImageConversation(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "image_conversations"

    image_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("run_images.id", ondelete="CASCADE"), nullable=False
    )
    messages: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, default=list, server_default="[]", nullable=False
    )
    extracted_values: Mapped[dict[str, Any]] = mapped_column(
        JSONB, default=dict, server_default="{}", nullable=False
    )
    status: Mapped[str] = mapped_column(
        String, default=ConversationStatus.PENDING, nullable=False
    )

    # Relationships
    image: Mapped["RunImage"] = relationship(back_populates="conversations")
