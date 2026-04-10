"""Centralized service for background job lifecycle management.

Wraps the BackgroundJob model with a clean API for creating, tracking
progress, completing, failing, and querying jobs.  Any feature that
runs async work (document processing, batch-record import, etc.)
should use this service instead of manipulating BackgroundJob directly.
"""

import platform
from datetime import datetime, timezone
from typing import Any, Optional
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.jobs import BackgroundJob, JobStatus
from app.schemas.jobs import ProcessingProgress


class BackgroundJobService:
    """Manages background job lifecycle: create, track progress, query."""

    @staticmethod
    async def create(
        db: AsyncSession,
        job_type: str,
        entity_type: str,
        entity_id: UUID,
        input_data: Optional[dict[str, Any]] = None,
    ) -> BackgroundJob:
        """Create a new background job and add it to the session.

        The job starts in RUNNING status with the current worker ID.
        Caller is responsible for committing the transaction.
        """
        now = datetime.now(timezone.utc)
        job = BackgroundJob(
            job_type=job_type,
            status=JobStatus.RUNNING.value,
            entity_type=entity_type,
            entity_id=entity_id,
            input_data=input_data or {},
            started_at=now,
            heartbeat_at=now,
            worker_id=platform.node(),
        )
        db.add(job)
        return job

    @staticmethod
    async def update_progress(
        db: AsyncSession,
        job: BackgroundJob,
        stage: str,
        stage_label: str,
        current: int,
        total: int,
    ) -> None:
        """Update the job's progress and refresh heartbeat.

        Commits immediately so polling clients see updates.
        """
        percent = int(current / total * 100) if total > 0 else 0
        job.output_data = {
            "stage": stage,
            "stage_label": stage_label,
            "current": current,
            "total": total,
            "percent": percent,
        }
        job.heartbeat_at = datetime.now(timezone.utc)
        await db.commit()

    @staticmethod
    async def complete(
        db: AsyncSession,
        job: BackgroundJob,
        output_data: Optional[dict[str, Any]] = None,
    ) -> None:
        """Mark a job as completed.

        Caller is responsible for committing the transaction.
        """
        job.status = JobStatus.COMPLETED.value
        job.completed_at = datetime.now(timezone.utc)
        if output_data is not None:
            job.output_data = output_data

    @staticmethod
    async def fail(
        db: AsyncSession,
        job: BackgroundJob,
        error_message: str,
    ) -> None:
        """Mark a job as failed.

        Caller is responsible for committing the transaction.
        """
        job.status = JobStatus.FAILED.value
        job.completed_at = datetime.now(timezone.utc)
        job.error_message = error_message[:500]

    @staticmethod
    async def get_progress(
        db: AsyncSession,
        entity_type: str,
        entity_id: UUID,
    ) -> Optional[ProcessingProgress]:
        """Fetch progress from the latest running job for an entity.

        Returns None if no running job exists or if the job has no
        progress data yet.
        """
        result = await db.execute(
            select(BackgroundJob)
            .where(
                BackgroundJob.entity_type == entity_type,
                BackgroundJob.entity_id == entity_id,
                BackgroundJob.status == JobStatus.RUNNING.value,
            )
            .order_by(
                BackgroundJob.created_at.desc(),
                BackgroundJob.started_at.desc(),
            )
            .limit(1)
        )
        job = result.scalar_one_or_none()
        if not job or not job.output_data:
            return None

        od = job.output_data
        return ProcessingProgress(
            stage=od.get("stage", ""),
            stage_label=od.get("stage_label", ""),
            current=od.get("current", 0),
            total=od.get("total", 0),
            percent=od.get("percent", 0),
            status=job.status,
        )

    @staticmethod
    async def get_latest_job(
        db: AsyncSession,
        entity_type: str,
        entity_id: UUID,
    ) -> Optional[BackgroundJob]:
        """Fetch the most recent job for an entity (any status)."""
        result = await db.execute(
            select(BackgroundJob)
            .where(
                BackgroundJob.entity_type == entity_type,
                BackgroundJob.entity_id == entity_id,
            )
            .order_by(
                BackgroundJob.created_at.desc(),
                BackgroundJob.started_at.desc(),
            )
            .limit(1)
        )
        return result.scalar_one_or_none()
