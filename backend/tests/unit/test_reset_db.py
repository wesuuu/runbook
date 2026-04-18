"""Unit tests for app.db.reset (pure functions + constant sanity)."""
from unittest.mock import patch

import pytest

from app.db.reset import (
    PRESERVED_TABLES,
    WIPE_TABLES,
    assert_local_dev_db,
    confirm_reset,
    mask_database_url,
)


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


def test_wipe_tables_matches_expected_set():
    assert set(WIPE_TABLES) == EXPECTED_WIPE


def test_wipe_tables_excludes_preserve_tables():
    # Single source of truth: import PRESERVED_TABLES from the module rather
    # than duplicating it here.
    assert set(WIPE_TABLES).isdisjoint(set(PRESERVED_TABLES))


def test_wipe_tables_has_no_duplicates():
    assert len(WIPE_TABLES) == len(set(WIPE_TABLES))


def test_preserved_tables_has_no_duplicates():
    assert len(PRESERVED_TABLES) == len(set(PRESERVED_TABLES))


def test_mask_database_url_masks_simple_password():
    url = "postgresql+asyncpg://postgres:postgres@localhost:5432/batchrite"
    masked = mask_database_url(url)
    assert masked == "postgresql+asyncpg://postgres:***@localhost:5432/batchrite"


def test_mask_database_url_masks_password_with_unencoded_at_sign():
    # The password contains unencoded ``@`` and ``#`` — the masker must anchor
    # on the LAST ``@`` before the host, not the first one.
    url = "postgresql+asyncpg://user:p@ss!w0rd#1@db.host.internal:5432/mydb"
    masked = mask_database_url(url)
    assert masked == "postgresql+asyncpg://user:***@db.host.internal:5432/mydb"


def test_mask_database_url_passes_through_url_without_userinfo():
    url = "postgresql+asyncpg://localhost:5432/batchrite"
    masked = mask_database_url(url)
    assert masked == url


def test_mask_database_url_passes_through_url_with_user_but_no_password():
    url = "postgresql+asyncpg://user@localhost:5432/batchrite"
    masked = mask_database_url(url)
    assert masked == url


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


def test_confirm_reset_aborts_when_stdin_not_tty(capsys):
    with patch("sys.stdin") as fake_stdin:
        fake_stdin.isatty.return_value = False
        result = confirm_reset()
    assert result is False
    captured = capsys.readouterr()
    assert "not a TTY" in captured.err or "not a TTY" in captured.out


def test_confirm_reset_accepts_lowercase_y():
    with patch("sys.stdin") as fake_stdin, \
            patch("builtins.input", return_value="y"):
        fake_stdin.isatty.return_value = True
        assert confirm_reset() is True


def test_confirm_reset_accepts_uppercase_y():
    # ``Y`` is lowercased by ``.lower()`` and must compare equal to ``"y"``.
    with patch("sys.stdin") as fake_stdin, \
            patch("builtins.input", return_value="Y"):
        fake_stdin.isatty.return_value = True
        assert confirm_reset() is True


@pytest.mark.parametrize("answer", ["yes", "n", "N", "", " ", "proceed", "YES"])
def test_confirm_reset_rejects_non_y_answers(answer):
    with patch("sys.stdin") as fake_stdin, \
            patch("builtins.input", return_value=answer):
        fake_stdin.isatty.return_value = True
        assert confirm_reset() is False, (
            f"confirm_reset() should reject {answer!r} — only exact ``y``/``Y`` "
            "counts as confirmation"
        )


def test_confirm_reset_handles_eof_as_abort():
    # Piping /dev/null or pressing ^D closes stdin — input() raises EOFError.
    with patch("sys.stdin") as fake_stdin, \
            patch("builtins.input", side_effect=EOFError):
        fake_stdin.isatty.return_value = True
        assert confirm_reset() is False


def test_confirm_reset_handles_keyboard_interrupt_as_abort():
    # Operator hits ^C at the prompt — treat as an explicit "no".
    with patch("sys.stdin") as fake_stdin, \
            patch("builtins.input", side_effect=KeyboardInterrupt):
        fake_stdin.isatty.return_value = True
        assert confirm_reset() is False
