"""Unit tests for app.db.reset (pure functions + constant sanity)."""
from app.db.reset import WIPE_TABLES


EXPECTED_WIPE = {
    "experiments",
    "protocols",
    "protocol_roles",
    "protocol_versions",
    "runs",
    "run_role_assignments",
    "equipment",
    "documents",
    "document_chunks",
    "document_templates",
    "batch_record_imports",
    "chat_sessions",
    "chat_messages",
    "run_images",
    "image_conversations",
    "audit_logs",
    "background_jobs",
    "notifications",
    "notification_channels",
    "notification_subscriptions",
    "notification_deliveries",
    "revoked_offline_tokens",
    "invitations",
    "verification_tokens",
}

PRESERVE_TABLES = {
    "users",
    "organizations",
    "organization_members",
    "teams",
    "team_members",
    "projects",
    "object_permissions",
    "unit_op_definitions",
    "ai_provider_configs",
}


def test_wipe_tables_matches_expected_set():
    assert set(WIPE_TABLES) == EXPECTED_WIPE


def test_wipe_tables_excludes_preserve_tables():
    assert set(WIPE_TABLES).isdisjoint(PRESERVE_TABLES)


def test_wipe_tables_has_no_duplicates():
    assert len(WIPE_TABLES) == len(set(WIPE_TABLES))
