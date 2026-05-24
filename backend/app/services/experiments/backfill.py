"""F-0093 §2.2 — backfill Experiment.objective from the legacy `content` doc.

Idempotent: only touches rows where `objective IS NULL`. Run once after the
migration deploys; safe to re-run. Batches via a keyset cursor on `id` so
skipped (over-cap / unparseable) rows can never cause an infinite loop, and
commits after each batch so a crash mid-run leaves completed batches
persisted — a re-run resumes cleanly from the first still-NULL row.
"""

import json
import logging

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.runs import Experiment

logger = logging.getLogger("backfill_experiment_objectives")

SIZE_CAP_BYTES = 256 * 1024
OBJECTIVE_MAX_CHARS = 280


def _extract_text(content: dict) -> str | None:
    """Concatenate text nodes from a Tiptap/Edra doc, iteratively."""
    if not isinstance(content, dict) or not content:
        return None
    if len(json.dumps(content)) > SIZE_CAP_BYTES:
        raise ValueError("content exceeds size cap")
    parts: list[str] = []
    stack = [content]
    while stack:
        node = stack.pop()
        if isinstance(node, dict):
            if node.get("type") == "text" and isinstance(node.get("text"), str):
                parts.append(node["text"])
            children = node.get("content")
            if isinstance(children, list):
                stack.extend(reversed(children))
        elif isinstance(node, list):
            stack.extend(reversed(node))
    text = " ".join(p.strip() for p in parts if p.strip())
    return text or None


async def backfill_objectives(
    db: AsyncSession, *, batch_size: int = 500
) -> dict[str, int]:
    """Backfill objectives in keyset-paginated batches.

    Commits after each batch — the operation is restartable: a crash leaves
    every completed batch persisted, and a re-run skips them (their
    `objective` is no longer NULL). Returns count stats.
    """
    stats = {
        "total": 0,
        "already_set": 0,
        "backfilled": 0,
        "skipped_over_cap": 0,
        "skipped_unparseable": 0,
    }
    cursor = None
    while True:
        # Never touch a locked experiment — its conclusion is signed and
        # backfilling metadata after the fact would mutate the inspector
        # snapshot. Locked rows with NULL objective are skipped silently;
        # operators unlock + re-run if they need backfill on those.
        stmt = select(Experiment).where(
            Experiment.objective.is_(None),
            Experiment.conclusion_locked_at.is_(None),
        )
        if cursor is not None:
            stmt = stmt.where(Experiment.id > cursor)
        stmt = stmt.order_by(Experiment.id).limit(batch_size)
        batch = list((await db.execute(stmt)).scalars().all())
        if not batch:
            break
        for exp in batch:
            stats["total"] += 1
            cursor = exp.id
            try:
                text = _extract_text(exp.content or {})
            except ValueError:
                stats["skipped_over_cap"] += 1
                continue
            if not text:
                stats["skipped_unparseable"] += 1
                continue
            exp.objective = text[:OBJECTIVE_MAX_CHARS]
            stats["backfilled"] += 1
        # Commit each batch so a crash never re-does completed work. The
        # keyset cursor is a plain UUID captured before commit, so the next
        # iteration's `id > cursor` query is unaffected by the expire.
        await db.commit()

    # `already_set` is everything else — count rows that already had an objective.
    not_null = (
        await db.execute(
            select(func.count(Experiment.id)).where(
                Experiment.objective.is_not(None)
            )
        )
    ).scalar() or 0
    stats["already_set"] = max(0, not_null - stats["backfilled"])
    return stats
