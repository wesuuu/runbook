import re
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.equipment import Equipment

_DISALLOWED = re.compile(r"[^a-z0-9-]+")
_MULTI_HYPHEN = re.compile(r"-+")
MAX_TAG_LEN = 40
MAX_TAGS_PER_EQUIPMENT = 20


def normalize_tag(raw: str) -> str:
    s = (raw or "").strip().lower()
    s = re.sub(r"\s+", "-", s)
    s = _DISALLOWED.sub("-", s)
    s = _MULTI_HYPHEN.sub("-", s).strip("-")
    return s[:MAX_TAG_LEN]


def normalize_tags(raw: list[str]) -> list[str]:
    seen: list[str] = []
    for t in raw:
        n = normalize_tag(t)
        if n and n not in seen:
            seen.append(n)
        if len(seen) >= MAX_TAGS_PER_EQUIPMENT:
            break
    return seen


async def list_distinct_tags(db: AsyncSession, org_id: UUID) -> list[str]:
    stmt = (
        select(func.unnest(Equipment.tags))
        .where(Equipment.organization_id == org_id, Equipment.archived_at.is_(None))
        .distinct()
    )
    rows = (await db.execute(stmt)).scalars().all()
    return sorted([r for r in rows if r])
