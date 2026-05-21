"""F-0093 §2.2 — objective backfill from Experiment.content."""

import pytest

from app.models.runs import Experiment
from app.services.experiments.backfill import backfill_objectives


def _doc(text: str) -> dict:
    return {
        "type": "doc",
        "content": [
            {"type": "paragraph", "content": [{"type": "text", "text": text}]}
        ],
    }


@pytest.mark.asyncio
async def test_backfill_populates_truncates_and_is_idempotent(
    db_session, test_project,
):
    long_text = "Q " * 400  # > 280 chars
    with_content = Experiment(
        name="Has content", slug="has-content", project_id=test_project.id,
        content=_doc(long_text),
    )
    already = Experiment(
        name="Already set", slug="already", project_id=test_project.id,
        objective="kept", content=_doc("ignored"),
    )
    empty = Experiment(
        name="No content", slug="no-content", project_id=test_project.id,
        content={},
    )
    db_session.add_all([with_content, already, empty])
    await db_session.commit()

    # NOTE: db.commit() inside backfill_objectives is a no-op at the DB level
    # here — the db_session fixture's SAVEPOINT runs in rollback_only mode.
    # This test verifies extraction logic, truncation, and skip handling via
    # the session identity map; it does not (cannot) verify per-batch
    # durability across a real crash. backfill_objectives commits per batch
    # internally, so the test needs no trailing commit.
    stats = await backfill_objectives(db_session, batch_size=2)

    await db_session.refresh(with_content)
    await db_session.refresh(already)
    assert with_content.objective is not None
    assert len(with_content.objective) == 280
    assert already.objective == "kept"
    assert stats["backfilled"] == 1
    assert stats["already_set"] == 1
    assert stats["total"] == 2  # with_content + empty (already-set is not NULL)
    assert stats["skipped_unparseable"] == 1

    # Second run is a no-op.
    stats2 = await backfill_objectives(db_session, batch_size=2)
    assert stats2["backfilled"] == 0
