"""Dev DB reset: wipe user-generated data and re-seed the baseline.

Run via: python -m app.db.reset (from backend/)
Or: scripts/reset-db.sh (from repo root)

Guarded to only run against localhost/batchrite to prevent accidental
use against a staging or production database.
"""
from __future__ import annotations

WIPE_TABLES: tuple[str, ...] = (
    # Science graph
    "experiments",
    "protocols",
    "protocol_roles",
    "protocol_versions",
    "runs",
    "run_role_assignments",
    "equipment",
    # Library / documents
    "documents",
    "document_chunks",
    "document_templates",
    "batch_record_imports",
    # Chat
    "chat_sessions",
    "chat_messages",
    # AI / images
    "run_images",
    "image_conversations",
    # Audit / jobs
    "audit_logs",
    "background_jobs",
    # Notifications
    "notifications",
    "notification_channels",
    "notification_subscriptions",
    "notification_deliveries",
    # Auth ephemera
    "revoked_offline_tokens",
    "invitations",
    "verification_tokens",
)
