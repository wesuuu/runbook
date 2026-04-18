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


from app.db.reset import mask_database_url


def test_mask_database_url_masks_simple_password():
    url = "postgresql+asyncpg://postgres:postgres@localhost:5432/batchrite"
    masked = mask_database_url(url)
    assert masked == "postgresql+asyncpg://postgres:***@localhost:5432/batchrite"


def test_mask_database_url_masks_complex_password():
    url = "postgresql+asyncpg://user:p@ss!w0rd#1@db.host.internal:5432/mydb"
    masked = mask_database_url(url)
    # Password runs up to the LAST @ before the host segment.
    assert "p@ss!w0rd#1" not in masked
    assert "***" in masked
    assert "db.host.internal" in masked


def test_mask_database_url_passes_through_url_without_password():
    url = "postgresql+asyncpg://localhost:5432/batchrite"
    masked = mask_database_url(url)
    assert masked == url


import pytest

from app.db.reset import assert_local_dev_db


def test_assert_local_dev_db_accepts_localhost():
    assert_local_dev_db("postgresql+asyncpg://postgres:postgres@localhost:5432/batchrite")


def test_assert_local_dev_db_accepts_127_0_0_1():
    assert_local_dev_db("postgresql+asyncpg://postgres:postgres@127.0.0.1:5432/batchrite")


def test_assert_local_dev_db_rejects_non_local_host():
    url = "postgresql+asyncpg://postgres:postgres@prod.db.internal:5432/batchrite"
    with pytest.raises(RuntimeError) as exc:
        assert_local_dev_db(url)
    assert "prod.db.internal" in str(exc.value)


def test_assert_local_dev_db_rejects_wrong_db_name():
    url = "postgresql+asyncpg://postgres:postgres@localhost:5432/batchrite_prod"
    with pytest.raises(RuntimeError) as exc:
        assert_local_dev_db(url)
    assert "batchrite_prod" in str(exc.value)


def test_assert_local_dev_db_rejects_empty_db_name():
    url = "postgresql+asyncpg://postgres:postgres@localhost:5432/"
    with pytest.raises(RuntimeError):
        assert_local_dev_db(url)
