"""F-0043 — aggregate observations from experiment + run notes."""

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Literal, Optional
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

ObservationSource = Literal["experiment", "run"]
ObservationFlag = Literal["observation", "anomaly"]


@dataclass
class ObservationItem:
    id: str
    source: ObservationSource
    source_id: UUID
    run_label: Optional[str]
    flag: ObservationFlag
    body: str
    author_name: str
    created_at: datetime


@dataclass
class ObservationsResponse:
    items: list[ObservationItem]
    truncated: bool


async def aggregate_observations(
    db: AsyncSession, experiment_id: UUID, limit: int = 500
) -> ObservationsResponse:
    """UNION ALL over experiment.notes + run.notes, filtered + sorted desc.

    Experiment notes: surfaces entries where the `flags` array contains
    'observation' OR 'anomaly'.  The first matching flag from the array is
    reported as `flag` in the response.

    Run notes: only surfaces entries where `flags` contains 'anomaly'
    (ALLOWED_NOTE_FLAGS for runs is anomaly-only).

    Notes missing a parseable `created_at` ISO timestamp are silently dropped
    (the SQL regex guard handles this).
    """
    ts_regex = r"^\d{4}-\d{2}-\d{2}T"
    sql = text(
        """
        SELECT * FROM (
            (
                SELECT
                    'experiment'::text AS source,
                    e.id AS source_id,
                    NULL::text AS run_label,
                    (note->>'id') AS note_id,
                    CASE
                        WHEN note->'flags' ? 'anomaly' THEN 'anomaly'
                        ELSE 'observation'
                    END AS flag,
                    (note->>'content') AS body,
                    COALESCE(note->>'author_name', 'Unknown') AS author_name,
                    (note->>'created_at')::timestamptz AS created_at
                FROM experiments e
                CROSS JOIN LATERAL jsonb_array_elements(e.notes) AS note
                WHERE e.id = :exp_id
                  AND (note->'flags' ? 'observation' OR note->'flags' ? 'anomaly')
                  AND note->>'created_at' ~ :ts_regex
                ORDER BY created_at DESC
                LIMIT :limit_plus_one
            )
            UNION ALL
            (
                SELECT
                    'run'::text AS source,
                    r.id AS source_id,
                    r.name AS run_label,
                    (note->>'id') AS note_id,
                    'anomaly'::text AS flag,
                    (note->>'content') AS body,
                    COALESCE(note->>'author_name', 'Unknown') AS author_name,
                    (note->>'created_at')::timestamptz AS created_at
                FROM runs r
                CROSS JOIN LATERAL jsonb_array_elements(r.notes) AS note
                WHERE r.experiment_id = :exp_id
                  AND r.status != 'ARCHIVED'
                  AND note->'flags' ? 'anomaly'
                  AND note->>'created_at' ~ :ts_regex
                ORDER BY created_at DESC
                LIMIT :limit_plus_one
            )
        ) merged
        ORDER BY created_at DESC
        LIMIT :limit_plus_one
        """
    )
    rows = (
        await db.execute(
            sql,
            {
                "exp_id": experiment_id,
                "limit_plus_one": limit + 1,
                "ts_regex": ts_regex,
            },
        )
    ).mappings().all()
    truncated = len(rows) > limit
    if truncated:
        logger.warning(
            "observations_truncated experiment_id=%s limit=%d",
            experiment_id,
            limit,
        )
    items = [
        ObservationItem(
            id=f"{r['source']}:{r['source_id']}:{r['note_id'] or 'noid'}",
            source=r["source"],
            source_id=r["source_id"],
            run_label=r["run_label"],
            flag=r["flag"],
            body=r["body"] or "",
            author_name=r["author_name"],
            created_at=r["created_at"],
        )
        for r in rows[:limit]
    ]
    return ObservationsResponse(items=items, truncated=truncated)
