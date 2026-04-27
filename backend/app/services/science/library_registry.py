"""Unit operation library registry (F-0075).

Loads versioned JSON catalogs of unit operations and serves them to the
rest of the app. Designed so that adding new sources (e.g. a remote
catalog for on-prem deployments) is plumbing rather than architecture.
"""
from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import TYPE_CHECKING, Any, Optional, Protocol

from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

# Stable namespace for synthetic UUIDs. Pinned in code so that
# `synthetic_uuid("core", "mixing")` returns the same value across
# every deployment, every source, every process.
_NAMESPACE: uuid.UUID = uuid.UUID("4e6b6c9a-1f8c-4f4e-8a16-bbcd0750f000")


class UnitOp(BaseModel):
    slug: str
    name: str
    category: str
    description: str = ""
    param_schema: dict[str, Any] = Field(default_factory=dict)
    result_schema: dict[str, Any] = Field(default_factory=dict)


class Library(BaseModel):
    slug: str
    name: str
    domain: str
    description: str = ""
    is_default: bool = False
    version: str
    unit_ops: list[UnitOp]


class LibrarySource(Protocol):
    async def load(self) -> list[Library]:  # pragma: no cover - protocol
        ...


class BundledJSONSource:
    """Loads every *.json file under a directory."""

    def __init__(self, directory: Path) -> None:
        self.directory = directory

    async def load(self) -> list[Library]:
        libs: list[Library] = []
        if not self.directory.exists():
            return libs
        for path in sorted(self.directory.glob("*.json")):
            with path.open("r", encoding="utf-8") as fh:
                raw = json.load(fh)
            libs.append(Library.model_validate(raw))
        return libs


# --- Module-level state ---

_sources: list[LibrarySource] = []
_cache: dict[str, Library] = {}


def register_source(source: LibrarySource) -> None:
    """Register a LibrarySource. Call before reload_libraries()."""
    _sources.append(source)


async def reload_libraries() -> None:
    """Re-read every registered source and atomically replace the cache.

    Two phases:
    1. Gather: call each source's load(). Any exception aborts here.
    2. Commit: assign _cache. Reached only if every source succeeded.

    Last-source-wins on slug collisions.
    """
    # ---- Phase 1: gather ----
    new_cache: dict[str, Library] = {}
    for source in _sources:
        libs = await source.load()
        for lib in libs:
            new_cache[lib.slug] = lib
    # ---- Phase 2: commit (only reached if every source succeeded) ----
    global _cache
    _cache = new_cache


def list_libraries() -> list[Library]:
    return list(_cache.values())


def get_library(slug: str) -> Optional[Library]:
    return _cache.get(slug)


def get_op(library_slug: str, op_slug: str) -> Optional[UnitOp]:
    lib = _cache.get(library_slug)
    if lib is None:
        return None
    for op in lib.unit_ops:
        if op.slug == op_slug:
            return op
    return None


def synthetic_uuid(library_slug: str, op_slug: str) -> uuid.UUID:
    return uuid.uuid5(_NAMESPACE, f"{library_slug}/{op_slug}")


def default_library_slugs() -> list[str]:
    return [lib.slug for lib in _cache.values() if lib.is_default]


async def subscribe_default_libraries(
    db: "AsyncSession", org_id: uuid.UUID,
) -> None:
    """Insert subscription rows for every default library. Idempotent."""
    from sqlalchemy import select
    from app.models.science import UnitOpLibrarySubscription  # noqa: WPS433

    existing_q = await db.execute(
        select(UnitOpLibrarySubscription.library_slug).where(
            UnitOpLibrarySubscription.organization_id == org_id,
        )
    )
    existing = {row[0] for row in existing_q.all()}
    for slug in default_library_slugs():
        if slug in existing:
            continue
        db.add(UnitOpLibrarySubscription(
            organization_id=org_id, library_slug=slug,
        ))
    await db.flush()


# --- Test helpers ---

def _reset_for_tests() -> None:
    """Clear sources and cache. Tests only."""
    _sources.clear()
    _cache.clear()


def _reset_sources_for_tests() -> None:
    """Clear sources but keep cache. Tests only."""
    _sources.clear()
