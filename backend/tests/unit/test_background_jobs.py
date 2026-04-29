"""Unit tests for BackgroundJobService."""

import uuid

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.jobs import BackgroundJob, JobStatus
from app.schemas.jobs import ProcessingProgress
from app.services.core.background_jobs import BackgroundJobService

ENTITY_ID = uuid.uuid4()


class TestCreate:
    async def test_creates_running_job(self, db_session: AsyncSession):
        job = await BackgroundJobService.create(
            db_session,
            "test_job",
            "test_entity",
            ENTITY_ID,
        )
        await db_session.commit()

        assert job.id is not None
        assert job.status == JobStatus.RUNNING.value
        assert job.job_type == "test_job"
        assert job.entity_type == "test_entity"
        assert job.entity_id == ENTITY_ID
        assert job.started_at is not None
        assert job.heartbeat_at is not None
        assert job.worker_id is not None

    async def test_stores_input_data(self, db_session: AsyncSession):
        job = await BackgroundJobService.create(
            db_session,
            "test_job",
            "test_entity",
            ENTITY_ID,
            input_data={"mime_type": "application/pdf"},
        )
        await db_session.commit()

        assert job.input_data == {"mime_type": "application/pdf"}

    async def test_defaults_empty_input_data(self, db_session: AsyncSession):
        job = await BackgroundJobService.create(
            db_session,
            "test_job",
            "test_entity",
            ENTITY_ID,
        )
        await db_session.commit()

        assert job.input_data == {}


class TestUpdateProgress:
    async def test_updates_output_data(self, db_session: AsyncSession):
        job = await BackgroundJobService.create(
            db_session,
            "test_job",
            "test_entity",
            ENTITY_ID,
        )
        await db_session.commit()

        await BackgroundJobService.update_progress(
            db_session,
            job,
            "extracting",
            "Extracting text",
            3,
            12,
        )

        assert job.output_data["stage"] == "extracting"
        assert job.output_data["stage_label"] == "Extracting text"
        assert job.output_data["current"] == 3
        assert job.output_data["total"] == 12
        assert job.output_data["percent"] == 25

    async def test_refreshes_heartbeat(self, db_session: AsyncSession):
        job = await BackgroundJobService.create(
            db_session,
            "test_job",
            "test_entity",
            ENTITY_ID,
        )
        await db_session.commit()
        old_heartbeat = job.heartbeat_at

        await BackgroundJobService.update_progress(
            db_session,
            job,
            "chunking",
            "Chunking",
            1,
            10,
        )

        assert job.heartbeat_at >= old_heartbeat

    async def test_percent_zero_when_total_zero(self, db_session: AsyncSession):
        job = await BackgroundJobService.create(
            db_session,
            "test_job",
            "test_entity",
            ENTITY_ID,
        )
        await db_session.commit()

        await BackgroundJobService.update_progress(
            db_session,
            job,
            "init",
            "Starting",
            0,
            0,
        )

        assert job.output_data["percent"] == 0


class TestComplete:
    async def test_marks_completed(self, db_session: AsyncSession):
        job = await BackgroundJobService.create(
            db_session,
            "test_job",
            "test_entity",
            ENTITY_ID,
        )
        await db_session.commit()

        await BackgroundJobService.complete(
            db_session,
            job,
            output_data={"page_count": 5},
        )
        await db_session.commit()

        assert job.status == JobStatus.COMPLETED.value
        assert job.completed_at is not None
        assert job.output_data == {"page_count": 5}

    async def test_complete_without_output_data(self, db_session: AsyncSession):
        job = await BackgroundJobService.create(
            db_session,
            "test_job",
            "test_entity",
            ENTITY_ID,
        )
        await db_session.commit()

        # Set some progress first
        await BackgroundJobService.update_progress(
            db_session,
            job,
            "working",
            "Working",
            5,
            10,
        )

        await BackgroundJobService.complete(db_session, job)
        await db_session.commit()

        assert job.status == JobStatus.COMPLETED.value
        # output_data should retain the progress data
        assert job.output_data["stage"] == "working"


class TestFail:
    async def test_marks_failed(self, db_session: AsyncSession):
        job = await BackgroundJobService.create(
            db_session,
            "test_job",
            "test_entity",
            ENTITY_ID,
        )
        await db_session.commit()

        await BackgroundJobService.fail(
            db_session,
            job,
            "Something went wrong",
        )
        await db_session.commit()

        assert job.status == JobStatus.FAILED.value
        assert job.completed_at is not None
        assert job.error_message == "Something went wrong"

    async def test_truncates_long_error_message(self, db_session: AsyncSession):
        job = await BackgroundJobService.create(
            db_session,
            "test_job",
            "test_entity",
            ENTITY_ID,
        )
        await db_session.commit()

        long_msg = "x" * 1000
        await BackgroundJobService.fail(db_session, job, long_msg)
        await db_session.commit()

        assert len(job.error_message) == 500


class TestGetProgress:
    async def test_returns_progress_for_running_job(
        self,
        db_session: AsyncSession,
    ):
        entity_id = uuid.uuid4()
        job = await BackgroundJobService.create(
            db_session,
            "test_job",
            "test_entity",
            entity_id,
        )
        await db_session.commit()
        await BackgroundJobService.update_progress(
            db_session,
            job,
            "extracting",
            "Extracting text",
            5,
            10,
        )

        progress = await BackgroundJobService.get_progress(
            db_session,
            "test_entity",
            entity_id,
        )

        assert progress is not None
        assert isinstance(progress, ProcessingProgress)
        assert progress.stage == "extracting"
        assert progress.current == 5
        assert progress.total == 10
        assert progress.percent == 50
        assert progress.status == JobStatus.RUNNING.value

    async def test_returns_none_when_no_running_job(
        self,
        db_session: AsyncSession,
    ):
        progress = await BackgroundJobService.get_progress(
            db_session,
            "test_entity",
            uuid.uuid4(),
        )
        assert progress is None

    async def test_returns_none_when_job_has_no_output(
        self,
        db_session: AsyncSession,
    ):
        entity_id = uuid.uuid4()
        await BackgroundJobService.create(
            db_session,
            "test_job",
            "test_entity",
            entity_id,
        )
        await db_session.commit()

        progress = await BackgroundJobService.get_progress(
            db_session,
            "test_entity",
            entity_id,
        )
        assert progress is None

    async def test_ignores_completed_jobs(self, db_session: AsyncSession):
        entity_id = uuid.uuid4()
        job = await BackgroundJobService.create(
            db_session,
            "test_job",
            "test_entity",
            entity_id,
        )
        await db_session.commit()
        await BackgroundJobService.update_progress(
            db_session,
            job,
            "done",
            "Done",
            10,
            10,
        )
        await BackgroundJobService.complete(
            db_session,
            job,
            output_data={"result": "ok"},
        )
        await db_session.commit()

        progress = await BackgroundJobService.get_progress(
            db_session,
            "test_entity",
            entity_id,
        )
        assert progress is None


class TestGetLatestJob:
    async def test_returns_latest_job(self, db_session: AsyncSession):
        entity_id = uuid.uuid4()
        job1 = await BackgroundJobService.create(
            db_session,
            "test_job",
            "test_entity",
            entity_id,
        )
        await db_session.commit()
        await BackgroundJobService.complete(db_session, job1)
        await db_session.commit()

        job2 = await BackgroundJobService.create(
            db_session,
            "test_job",
            "test_entity",
            entity_id,
        )
        await db_session.commit()

        latest = await BackgroundJobService.get_latest_job(
            db_session,
            "test_entity",
            entity_id,
        )

        assert latest is not None
        assert latest.id == job2.id

    async def test_returns_none_when_no_jobs(self, db_session: AsyncSession):
        latest = await BackgroundJobService.get_latest_job(
            db_session,
            "test_entity",
            uuid.uuid4(),
        )
        assert latest is None
