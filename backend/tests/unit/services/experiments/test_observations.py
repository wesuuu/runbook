"""F-0043 — observations aggregation."""

import pytest
from uuid import uuid4
from datetime import datetime, timezone

from app.services.experiments.observations import aggregate_observations


@pytest.mark.asyncio
async def test_returns_experiment_and_run_notes_desc(db_session, experiment_with_notes):
    res = await aggregate_observations(db_session, experiment_with_notes.id)
    assert res.truncated is False
    assert len(res.items) >= 2
    for a, b in zip(res.items, res.items[1:]):
        assert a.created_at >= b.created_at


@pytest.mark.asyncio
async def test_only_anomaly_from_runs(db_session, experiment_with_run_observation_note):
    # Run notes only allow `anomaly` per ALLOWED_NOTE_FLAGS; anything else must not surface.
    res = await aggregate_observations(db_session, experiment_with_run_observation_note.id)
    run_items = [i for i in res.items if i.source == "run"]
    assert all(i.flag == "anomaly" for i in run_items)


@pytest.mark.asyncio
async def test_malformed_notes_filtered(db_session, experiment_with_malformed_notes):
    # Notes missing `flag` or `created_at` must be silently dropped, not raise.
    res = await aggregate_observations(db_session, experiment_with_malformed_notes.id)
    assert all(i.flag and i.created_at for i in res.items)


@pytest.mark.asyncio
async def test_empty_experiment(db_session, empty_experiment):
    res = await aggregate_observations(db_session, empty_experiment.id)
    assert res.items == []
    assert res.truncated is False


@pytest.mark.asyncio
async def test_truncated_flag(db_session, experiment_with_600_notes):
    res = await aggregate_observations(db_session, experiment_with_600_notes.id, limit=500)
    assert len(res.items) == 500
    assert res.truncated is True


@pytest.mark.asyncio
async def test_stable_composite_id(db_session, experiment_with_notes):
    res = await aggregate_observations(db_session, experiment_with_notes.id)
    ids = {item.id for item in res.items}
    assert len(ids) == len(res.items)
    for item in res.items:
        assert item.id.startswith(f"{item.source}:")
