#!/usr/bin/env python3
"""Migrate uploaded files to org-scoped FileStorageService directory layout.

Moves files from legacy flat directories into the org-scoped layout:
    ./uploads/{org_id}/{base_dir}/...

Handles three file types:
  1. Documents  — ./uploads/documents/{uuid}.ext → ./uploads/{org_id}/documents/{uuid}.ext
  2. Run images — ./uploads/images/{run_id}/... or ./uploads/images/{org_id}/images/...
                   → ./uploads/{org_id}/images/{run_id}/{step_id}/{uuid}.ext
  3. Avatars    — ./uploads/avatars/{user_id}.ext → ./uploads/{org_id}/avatars/{user_id}.ext

Usage:
    cd backend
    source .venv/bin/activate
    python scripts/migrate_file_storage.py [--dry-run]
"""

import argparse
import asyncio
import logging
import os
import shutil
from pathlib import Path
from uuid import UUID

import asyncpg

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)

UPLOADS_ROOT = Path("./uploads")
LEGACY_DOCUMENTS_DIR = UPLOADS_ROOT / "documents"
LEGACY_IMAGES_DIR = UPLOADS_ROOT / "images"
LEGACY_AVATARS_DIR = UPLOADS_ROOT / "avatars"

# asyncpg needs the plain postgresql:// URL, not postgresql+asyncpg://
_raw_url = os.environ.get(
    "BATCHRITE_DATABASE_URL",
    "postgresql+asyncpg://postgres:postgres@localhost:5432/batchrite",
)
DB_URL = _raw_url.replace("postgresql+asyncpg://", "postgresql://")


def _is_already_migrated(file_path: str) -> bool:
    """Check if a file_path already starts with a UUID (org_id)."""
    if not file_path or file_path.startswith("./") or file_path.startswith("/"):
        return False
    try:
        UUID(Path(file_path).parts[0])
        return True
    except (ValueError, IndexError):
        return False


async def migrate_documents(conn, dry_run: bool) -> tuple[int, int]:
    """Migrate document files to org-scoped directories."""
    rows = await conn.fetch("SELECT id, org_id, file_path FROM documents")

    migrated = 0
    skipped = 0

    for row in rows:
        doc_id, org_id, file_path = row["id"], row["org_id"], row["file_path"]
        if not file_path:
            skipped += 1
            continue

        if _is_already_migrated(file_path):
            logger.debug("Already migrated: %s", file_path)
            skipped += 1
            continue

        # Resolve old path to actual file
        src = Path(file_path)
        if not src.exists():
            logger.warning("File not found, skipping: %s", src)
            skipped += 1
            continue

        # Build new relative path: {org_id}/documents/{filename}
        filename = src.name
        new_relative = str(Path(str(org_id)) / "documents" / filename)
        new_full = UPLOADS_ROOT / new_relative

        logger.info("Document %s: %s → %s", doc_id, src, new_full)

        if not dry_run:
            new_full.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(src), str(new_full))
            await conn.execute(
                "UPDATE documents SET file_path = $1 WHERE id = $2",
                new_relative, doc_id,
            )
        migrated += 1

    return migrated, skipped


async def migrate_run_images(conn, dry_run: bool) -> tuple[int, int]:
    """Migrate run image files to org-scoped directories."""
    rows = await conn.fetch("""
        SELECT ri.id, ri.file_path, ri.run_id, ri.step_id, p.organization_id
        FROM run_images ri
        JOIN runs r ON r.id = ri.run_id
        JOIN projects p ON p.id = r.project_id
    """)

    migrated = 0
    skipped = 0

    for row in rows:
        img_id = row["id"]
        file_path = row["file_path"]
        run_id = row["run_id"]
        step_id = row["step_id"]
        org_id = row["organization_id"]

        if not file_path:
            skipped += 1
            continue

        if _is_already_migrated(file_path):
            if str(org_id) in file_path and "/images/" in file_path:
                logger.debug("Already migrated: %s", file_path)
                skipped += 1
                continue

        # Try to find the file on disk
        src = None

        # Try relative to ./uploads/images/ (sync.py pattern)
        candidate = LEGACY_IMAGES_DIR / file_path
        if candidate.exists():
            src = candidate
        else:
            # Try relative to ./uploads/ (ai.py pattern with wrong root)
            candidate = UPLOADS_ROOT / file_path
            if candidate.exists():
                src = candidate

        if src is None:
            logger.warning("Run image file not found, skipping: %s", file_path)
            skipped += 1
            continue

        # Build new relative path: {org_id}/images/{run_id}/{step_id}/{filename}
        filename = src.name
        new_relative = str(
            Path(str(org_id)) / "images" / str(run_id)
            / str(step_id) / filename
        )
        new_full = UPLOADS_ROOT / new_relative

        logger.info("RunImage %s: %s → %s", img_id, src, new_full)

        if not dry_run:
            new_full.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(src), str(new_full))
            await conn.execute(
                "UPDATE run_images SET file_path = $1 WHERE id = $2",
                new_relative, img_id,
            )
        migrated += 1

    return migrated, skipped


async def migrate_avatars(conn, dry_run: bool) -> tuple[int, int]:
    """Migrate avatar files to org-scoped directories."""
    rows = await conn.fetch("""
        SELECT u.id, u.avatar_path, om.organization_id
        FROM users u
        JOIN organization_members om ON om.user_id = u.id
        WHERE u.avatar_path IS NOT NULL
    """)

    migrated = 0
    skipped = 0

    for row in rows:
        user_id = row["id"]
        avatar_path = row["avatar_path"]
        org_id = row["organization_id"]

        if not avatar_path:
            skipped += 1
            continue

        if _is_already_migrated(avatar_path):
            logger.debug("Already migrated: %s", avatar_path)
            skipped += 1
            continue

        # Old layout: just "{user_id}.{ext}" in ./uploads/avatars/
        src = LEGACY_AVATARS_DIR / avatar_path
        if not src.exists():
            logger.warning("Avatar not found, skipping: %s", src)
            skipped += 1
            continue

        # New layout: {org_id}/avatars/{user_id}.{ext}
        ext = src.suffix
        new_filename = f"{user_id}{ext}"
        new_relative = str(Path(str(org_id)) / "avatars" / new_filename)
        new_full = UPLOADS_ROOT / new_relative

        logger.info("Avatar %s: %s → %s", user_id, src, new_full)

        if not dry_run:
            new_full.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(src), str(new_full))
            await conn.execute(
                "UPDATE users SET avatar_path = $1 WHERE id = $2",
                new_relative, user_id,
            )
        migrated += 1

    return migrated, skipped


async def main():
    parser = argparse.ArgumentParser(
        description="Migrate uploaded files to org-scoped directory layout."
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be done without making changes.",
    )
    args = parser.parse_args()

    if args.dry_run:
        logger.info("=== DRY RUN — no changes will be made ===")

    conn = await asyncpg.connect(DB_URL)

    try:
        logger.info("--- Migrating documents ---")
        doc_m, doc_s = await migrate_documents(conn, args.dry_run)
        logger.info("Documents: %d migrated, %d skipped", doc_m, doc_s)

        logger.info("--- Migrating run images ---")
        img_m, img_s = await migrate_run_images(conn, args.dry_run)
        logger.info("Run images: %d migrated, %d skipped", img_m, img_s)

        logger.info("--- Migrating avatars ---")
        av_m, av_s = await migrate_avatars(conn, args.dry_run)
        logger.info("Avatars: %d migrated, %d skipped", av_m, av_s)

        total = doc_m + img_m + av_m
        logger.info("=== Total: %d files migrated ===", total)

        if not args.dry_run and total > 0:
            logger.info(
                "Old directories (uploads/documents, uploads/images, "
                "uploads/avatars) may now be empty. "
                "Verify and remove manually if desired."
            )
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
