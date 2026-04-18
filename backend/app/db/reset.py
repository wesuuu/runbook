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

from urllib.parse import urlsplit


def mask_database_url(url: str) -> str:
    """Return ``url`` with the password segment replaced by ``***``.

    Anchors on the LAST ``@`` before the path component (the one that actually
    separates userinfo from ``host[:port]/db``). This correctly handles
    passwords containing unencoded ``@`` characters, where ``urlsplit`` would
    otherwise split on the first ``@`` and leak the rest of the password into
    the displayed host segment.
    """
    scheme_sep = url.find("://")
    if scheme_sep < 0:
        return url
    scheme_end = scheme_sep + 3  # position just after "://"
    # Find the first ":" after the scheme (start of the password).
    first_colon = url.find(":", scheme_end)
    if first_colon < 0:
        return url
    # Search for the password-terminating "@" only within the authority
    # component (before the path starts).
    path_start = url.find("/", scheme_end)
    search_region_end = path_start if path_start >= 0 else len(url)
    last_at = url.rfind("@", first_colon + 1, search_region_end)
    if last_at < 0:
        return url
    return url[:first_colon + 1] + "***" + url[last_at:]


ALLOWED_HOSTS: frozenset[str] = frozenset({"localhost", "127.0.0.1"})
ALLOWED_DB_NAME: str = "batchrite"


def assert_local_dev_db(url: str) -> None:
    """Raise RuntimeError unless ``url`` points at the local dev DB.

    Hard-coded allow-list (``localhost``/``127.0.0.1`` + ``batchrite``) so a
    misconfigured ``DATABASE_URL`` can't wipe a non-local database. Intentional
    non-local resets require editing this constant.
    """
    parts = urlsplit(url)
    host = parts.hostname or ""
    # path is like "/batchrite" — strip the leading slash
    db_name = parts.path.lstrip("/")
    if host not in ALLOWED_HOSTS:
        raise RuntimeError(
            f"Refusing to reset: DATABASE_URL host is {host!r}, "
            f"not in allow-list {sorted(ALLOWED_HOSTS)}."
        )
    if db_name != ALLOWED_DB_NAME:
        raise RuntimeError(
            f"Refusing to reset: DATABASE_URL database is {db_name!r}, "
            f"expected {ALLOWED_DB_NAME!r}."
        )


from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.seed import (
    seed_org,
    seed_permissions,
    seed_projects,
    seed_teams,
    seed_unit_ops,
    seed_users,
)


async def reset_database(session: AsyncSession) -> None:
    """Wipe ``WIPE_TABLES`` and re-apply the seed baseline.

    The caller is responsible for the transaction — in the CLI path we wrap
    this in ``async with session.begin()`` for atomicity; in tests we call it
    inside the per-test SAVEPOINT.
    """
    tables = ", ".join(WIPE_TABLES)
    await session.execute(text(f"TRUNCATE {tables} RESTART IDENTITY CASCADE"))
    # Temporarily disable FK checks so we can seed tables that have
    # mutual FK dependencies (users.selected_org_id ↔ organization_members)
    # without worrying about insertion order. ``session_replication_role``
    # is a session-local GUC; its effect is confined to this transaction.
    await session.execute(text("SET session_replication_role = 'replica'"))
    try:
        await seed_users(session)
        await seed_org(session)
        await seed_teams(session)
        await seed_projects(session)
        await seed_permissions(session)
        await seed_unit_ops(session)
    finally:
        await session.execute(text("SET session_replication_role = 'origin'"))


import asyncio
import sys

from app.core.config import settings
from app.db.session import AsyncSessionLocal


def confirm_reset() -> bool:
    """Print plan + prompt y/N. Return True only on explicit ``y``.

    Auto-aborts when stdin is not a TTY so the script can't be driven by
    ``yes`` or a forgotten pipe.
    """
    if not sys.stdin.isatty():
        print(
            "[reset-db] stdin is not a TTY; aborting to prevent unattended reset.",
            file=sys.stderr,
        )
        return False

    print()
    print(f"Target database: {mask_database_url(settings.database_url)}")
    print()
    print("The following tables will be WIPED (TRUNCATE ... RESTART IDENTITY CASCADE):")
    for table in WIPE_TABLES:
        print(f"  - {table}")
    print()
    print(
        "Preserved/re-seeded: users, organizations, organization_members, teams, "
        "team_members, projects, object_permissions, unit_op_definitions, "
        "ai_provider_configs."
    )
    print()
    answer = input("Proceed? [y/N]: ").strip().lower()
    return answer == "y"


async def _run() -> int:
    try:
        assert_local_dev_db(settings.database_url)
    except RuntimeError as exc:
        print(f"[reset-db] {exc}", file=sys.stderr)
        return 2

    if not confirm_reset():
        print("[reset-db] Aborted. No changes made.")
        return 1

    async with AsyncSessionLocal() as session:
        async with session.begin():
            await reset_database(session)
    print("[reset-db] Reset complete.")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(_run()))
