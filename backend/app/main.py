import asyncio
import logging
import platform
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import func, or_, select, update
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.config import settings

logger = logging.getLogger(__name__)

# A job whose heartbeat_at hasn't been refreshed for this long is
# considered abandoned (worker died without reporting failure).
# The heartbeat loop runs every 15 s, so 60 s = 4 missed beats.
STALE_HEARTBEAT_SECONDS = 60

# How many times we'll automatically retry a job for the same entity
# before giving up and marking the document FAILED.
MAX_RECOVERY_ATTEMPTS = 3

# Heartbeat interval — how often the background loop touches
# heartbeat_at for all RUNNING jobs owned by this worker.
_HEARTBEAT_INTERVAL_SECONDS = 15


# ── Heartbeat loop ──────────────────────────────────────────────────


async def _heartbeat_loop() -> None:
    """Periodically update heartbeat_at for all RUNNING jobs on this worker.

    Runs every 15 s as a background asyncio task. If this worker dies,
    the heartbeat stops, and other workers can detect the stale jobs.
    """
    from app.models.jobs import BackgroundJob, JobStatus

    engine = create_async_engine(settings.database_url)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    worker_id = platform.node()

    try:
        while True:
            await asyncio.sleep(_HEARTBEAT_INTERVAL_SECONDS)
            try:
                async with session_factory() as session:
                    await session.execute(
                        update(BackgroundJob)
                        .where(
                            BackgroundJob.status == JobStatus.RUNNING.value,
                            BackgroundJob.worker_id == worker_id,
                        )
                        .values(heartbeat_at=datetime.now(timezone.utc))
                    )
                    await session.commit()
            except Exception:
                logger.debug("Heartbeat update failed, will retry")
    except asyncio.CancelledError:
        pass
    finally:
        await engine.dispose()


# ── Job recovery ────────────────────────────────────────────────────


async def _recover_stalled_jobs() -> None:
    """Find BackgroundJobs stuck in RUNNING (stale heartbeat) and recover.

    A job is stale if its ``heartbeat_at`` is older than
    ``STALE_HEARTBEAT_SECONDS`` or NULL (pre-heartbeat jobs / worker
    never set it).

    Uses SELECT … FOR UPDATE SKIP LOCKED so multiple pods starting
    simultaneously won't claim the same stale jobs.

    Recovery per job type:
    - ``document_process``: mark FAILED, reset Document → UPLOADED.
      The subsequent ``_recover_stalled_documents`` will re-fire it.
    - ``document_enrich``: mark FAILED, re-fire directly if Document
      is still INDEXED and retry budget remains.
    """
    from app.models.jobs import BackgroundJob, JobStatus
    from app.models.library import Document, DocumentStatus
    from app.services.documents.document_processor import enrich_document

    engine = create_async_engine(settings.database_url)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    try:
        async with session_factory() as session:
            stale_cutoff = datetime.now(timezone.utc) - timedelta(
                seconds=STALE_HEARTBEAT_SECONDS
            )

            result = await session.execute(
                select(BackgroundJob)
                .where(
                    BackgroundJob.status == JobStatus.RUNNING.value,
                    or_(
                        BackgroundJob.heartbeat_at == None,  # noqa: E711
                        BackgroundJob.heartbeat_at < stale_cutoff,
                    ),
                )
                .with_for_update(skip_locked=True)
            )
            stalled_jobs = list(result.scalars().all())

            if not stalled_jobs:
                logger.info("No stalled jobs found on startup")
                return

            logger.info(
                "Found %d stalled job(s) to recover: %s",
                len(stalled_jobs),
                [f"{j.job_type}:{j.entity_id}" for j in stalled_jobs],
            )

            enrich_tasks: list[tuple] = []  # (doc_id, db_url)

            for job in stalled_jobs:
                job.status = JobStatus.FAILED.value
                job.completed_at = datetime.now(timezone.utc)
                job.error_message = "Recovered: worker went away (no heartbeat)"

                if job.entity_type != "document":
                    continue

                # Count total FAILED jobs for this entity+type
                # (including the one we just marked)
                count_result = await session.execute(
                    select(func.count(BackgroundJob.id)).where(
                        BackgroundJob.entity_id == job.entity_id,
                        BackgroundJob.job_type == job.job_type,
                        BackgroundJob.status == JobStatus.FAILED.value,
                    )
                )
                failed_count = count_result.scalar() or 0

                if failed_count >= MAX_RECOVERY_ATTEMPTS:
                    logger.warning(
                        "Max recovery attempts (%d) reached for "
                        "%s on document %s — marking FAILED",
                        MAX_RECOVERY_ATTEMPTS,
                        job.job_type,
                        job.entity_id,
                    )
                    doc_result = await session.execute(
                        select(Document).where(Document.id == job.entity_id)
                    )
                    doc = doc_result.scalar_one_or_none()
                    if doc and doc.status not in (DocumentStatus.FAILED.value,):
                        doc.status = DocumentStatus.FAILED.value
                        doc.error_message = (
                            f"Failed after {failed_count} " "recovery attempts"
                        )
                    continue

                # Route by job type
                if job.job_type == "document_process":
                    # Reset doc → UPLOADED; _recover_stalled_documents
                    # (which runs next) will re-fire process_document.
                    doc_result = await session.execute(
                        select(Document).where(Document.id == job.entity_id)
                    )
                    doc = doc_result.scalar_one_or_none()
                    if doc and doc.status in (
                        DocumentStatus.UPLOADED.value,
                        DocumentStatus.PROCESSING.value,
                    ):
                        doc.status = DocumentStatus.UPLOADED.value
                        doc.processing_started_at = None

                elif job.job_type == "document_enrich":
                    # Re-fire enrichment directly (no doc-status
                    # mechanism exists for enrichment recovery).
                    doc_result = await session.execute(
                        select(Document).where(Document.id == job.entity_id)
                    )
                    doc = doc_result.scalar_one_or_none()
                    if doc and doc.status == DocumentStatus.INDEXED.value:
                        enrich_tasks.append((doc.id, settings.database_url))

            await session.commit()

            # Fire enrichment tasks after commit
            for doc_id, db_url in enrich_tasks:
                asyncio.create_task(enrich_document(doc_id, db_url))
                logger.info("Re-fired enrichment for document %s", doc_id)

    finally:
        await engine.dispose()


async def _recover_stalled_documents() -> None:
    """Find documents stuck in UPLOADED or stale PROCESSING and re-enqueue.

    Called once on startup, AFTER ``_recover_stalled_jobs`` has marked
    abandoned jobs as FAILED and reset their documents to UPLOADED.

    Uses SELECT … FOR UPDATE SKIP LOCKED so multiple pods starting
    simultaneously won't double-process.
    """
    from app.models.library import (STALE_PROCESSING_SECONDS, Document,
                                    DocumentStatus)
    from app.services.documents.document_processor import process_document

    engine = create_async_engine(settings.database_url)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    try:
        async with session_factory() as session:
            stale_cutoff = datetime.now(timezone.utc) - timedelta(
                seconds=STALE_PROCESSING_SECONDS
            )

            # Find documents that need recovery:
            # 1. UPLOADED — background task never ran (pod died before it fired)
            # 2. PROCESSING with stale timestamp — pod died mid-processing
            result = await session.execute(
                select(Document)
                .where(
                    or_(
                        Document.status == DocumentStatus.UPLOADED.value,
                        (
                            (Document.status == DocumentStatus.PROCESSING.value)
                            & (
                                (Document.processing_started_at == None)  # noqa: E711
                                | (Document.processing_started_at < stale_cutoff)
                            )
                        ),
                    )
                )
                .with_for_update(skip_locked=True)
            )
            stalled_docs = list(result.scalars().all())

            if not stalled_docs:
                logger.info("No stalled documents found on startup")
                return

            logger.info(
                "Found %d stalled document(s) to recover: %s",
                len(stalled_docs),
                [str(d.id) for d in stalled_docs],
            )

            # Reset stale PROCESSING docs back to UPLOADED so
            # process_document treats them as fresh
            for doc in stalled_docs:
                if doc.status == DocumentStatus.PROCESSING.value:
                    doc.status = DocumentStatus.UPLOADED.value
                    doc.processing_started_at = None
            await session.commit()

            # Fire off processing tasks for each
            for doc in stalled_docs:
                asyncio.create_task(process_document(doc.id, settings.database_url))
    finally:
        await engine.dispose()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan: recover stalled work and start heartbeat."""
    # F-0075: load unit op libraries
    from app.services.science import library_registry

    library_registry.register_source(
        library_registry.BundledJSONSource(
            Path(__file__).resolve().parent / "data/unit_op_libraries"
        )
    )
    try:
        await library_registry.reload_libraries()
    except Exception:
        logger.exception("Library registry initial load failed")
        raise

    # Phase 1: mark abandoned RUNNING jobs as FAILED, reset doc statuses
    try:
        await _recover_stalled_jobs()
    except Exception:
        logger.exception("Job recovery sweep failed on startup")

    # Phase 2: re-fire tasks for UPLOADED / stale PROCESSING documents
    try:
        await _recover_stalled_documents()
    except Exception:
        logger.exception("Document recovery sweep failed on startup")

    # Seed system document templates into file storage
    from app.services.protocols.template_seeder import seed_system_templates

    seed_system_templates()

    from app.services.lifecycle import loops_client

    if loops_client.is_configured():
        logger.info("Loops CRM integration: ENABLED")
    else:
        logger.info("Loops CRM integration: DISABLED (BATCHRITE_LOOPS_API_KEY unset)")

    # Start the heartbeat background task
    heartbeat_task = asyncio.create_task(_heartbeat_loop())

    yield

    # Shutdown: cancel heartbeat
    heartbeat_task.cancel()
    try:
        await heartbeat_task
    except asyncio.CancelledError:
        pass


app = FastAPI(
    title="Batchrite — Laboratory Execution System",
    description="Backend for the Batchrite Laboratory Execution System",
    version="0.1.0",
    lifespan=lifespan,
)

# Auth middleware — decodes JWT and stashes on request.state
from app.core.middleware import AuthMiddleware

app.add_middleware(AuthMiddleware)

# CORS Configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://localhost:5174",  # Worktree dev
        "http://localhost:5183",  # Parallel worktree dev
        "http://localhost:5193",  # Worktree 2 dev
        "http://100.120.2.59:5174",
        "http://localhost:5176",  # Playwright E2E tests
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
async def health_check():
    return {"status": "ok", "service": "batchrite-backend"}


from app.api.endpoints import (admin, ai, auth, batch_record_import, billing,
                               chat, dashboard, experiments, export_data, iam,
                               library, notifications, offline, onboarding,
                               project_members, projects, protocol_pdfs,
                               protocol_versions, protocols, runs, sync,
                               template_convert, templates, unit_ops)

app.include_router(admin.router, prefix="/admin", tags=["admin"])
app.include_router(auth.router, prefix="/auth", tags=["auth"])
app.include_router(projects.router, prefix="/projects", tags=["projects"])
app.include_router(iam.router, prefix="/iam", tags=["iam"])
app.include_router(unit_ops.router, prefix="/science", tags=["science"])
app.include_router(protocols.router, prefix="/science", tags=["science"])
app.include_router(protocol_versions.router, prefix="/science", tags=["science"])
app.include_router(protocol_pdfs.router, prefix="/science", tags=["science"])
app.include_router(runs.router, prefix="/science", tags=["science"])
app.include_router(experiments.router, prefix="/science", tags=["science"])
app.include_router(batch_record_import.router, prefix="/science", tags=["science"])
app.include_router(export_data.router, prefix="/science", tags=["science"])
app.include_router(project_members.router, prefix="/science", tags=["science"])
app.include_router(ai.router, prefix="/ai", tags=["ai"])
app.include_router(dashboard.router, prefix="/dashboard", tags=["dashboard"])
app.include_router(
    notifications.router, prefix="/notifications", tags=["notifications"]
)
app.include_router(library.router, prefix="/library", tags=["library"])
app.include_router(templates.router, tags=["templates"])
app.include_router(
    template_convert.router, prefix="/science", tags=["template-convert"]
)
app.include_router(chat.router, prefix="/chat", tags=["chat"])
app.include_router(offline.router, tags=["offline"])
app.include_router(sync.router, tags=["sync"])
app.include_router(onboarding.router, prefix="/onboarding", tags=["onboarding"])
app.include_router(billing.router, prefix="/billing", tags=["billing"])

# Dev-only endpoints (webhook echo, etc.)
if settings.debug:
    from app.api.endpoints import dev

    app.include_router(dev.router, prefix="/dev", tags=["dev"])

# Ensure uploads root directory exists
Path("./uploads").mkdir(parents=True, exist_ok=True)
