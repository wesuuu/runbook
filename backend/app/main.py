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
from app.services.core.background_handler import get_background_handler

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
    - ``document_extract``: mark FAILED, reset Document → UPLOADED.
      The subsequent ``_recover_stalled_documents`` will re-fire it.
    - Legacy ``document_process`` / ``document_enrich`` rows (pre-TD-0085):
      mark FAILED, reset doc → UPLOADED so the new extractor picks it up.
    """
    from app.models.jobs import BackgroundJob, JobStatus
    from app.models.library import Document, DocumentStatus

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

                # All document job types (new document_extract and legacy
                # document_process / document_enrich): reset doc → UPLOADED
                # so _recover_stalled_documents will re-fire the new extractor.
                if job.job_type in (
                    "document_extract",
                    "document_index",
                    "document_process",
                    "document_enrich",
                ):
                    doc_result = await session.execute(
                        select(Document).where(Document.id == job.entity_id)
                    )
                    doc = doc_result.scalar_one_or_none()
                    if doc and doc.status not in (
                        DocumentStatus.FAILED.value,
                        DocumentStatus.READY.value,
                        DocumentStatus.AWAITING_REFINEMENT.value,
                        DocumentStatus.INDEXING.value,
                    ):
                        doc.status = DocumentStatus.UPLOADED.value
                        doc.processing_started_at = None
                        doc.heartbeat_token = None

            await session.commit()

    finally:
        await engine.dispose()


async def _recover_stalled_documents() -> None:
    """Find documents stuck in UPLOADED or stale EXTRACTING and re-enqueue.

    Called once on startup, AFTER ``_recover_stalled_jobs`` has marked
    abandoned jobs as FAILED and reset their documents to UPLOADED.

    Uses SELECT … FOR UPDATE SKIP LOCKED so multiple pods starting
    simultaneously won't double-process.
    """
    from app.models.library import STALE_PROCESSING_SECONDS, Document, DocumentStatus

    engine = create_async_engine(settings.database_url)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    try:
        async with session_factory() as session:
            stale_cutoff = datetime.now(timezone.utc) - timedelta(
                seconds=STALE_PROCESSING_SECONDS
            )

            # Find documents that need recovery:
            # 1. UPLOADED — background task never ran (pod died before it fired)
            # 2. EXTRACTING / PROCESSING with stale timestamp — pod died mid-run
            result = await session.execute(
                select(Document)
                .where(
                    or_(
                        Document.status == DocumentStatus.UPLOADED.value,
                        (
                            Document.status.in_(
                                [
                                    DocumentStatus.EXTRACTING.value,
                                    DocumentStatus.PROCESSING.value,
                                ]
                            )
                            & (
                                (Document.processing_started_at == None)  # noqa: E711
                                | (Document.processing_started_at < stale_cutoff)
                            )
                        ),
                        (
                            (Document.status == DocumentStatus.INDEXING.value)
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

            # Categorize before re-firing — INDEXING docs go back through
            # document_index, everything else through document_extract.
            extracting_docs: list[Document] = []
            indexing_docs: list[Document] = []
            for doc in stalled_docs:
                if doc.status == DocumentStatus.INDEXING.value:
                    # Release the claim; keep status=INDEXING so the
                    # job picks up where the previous attempt left off
                    # (indexer is idempotent — drops prior chunks first).
                    doc.processing_started_at = None
                    doc.heartbeat_token = None
                    indexing_docs.append(doc)
                else:
                    # UPLOADED / EXTRACTING / PROCESSING all re-enter the
                    # extraction pipeline. Reset to UPLOADED for a fresh fire.
                    if doc.status in (
                        DocumentStatus.EXTRACTING.value,
                        DocumentStatus.PROCESSING.value,
                    ):
                        doc.status = DocumentStatus.UPLOADED.value
                        doc.processing_started_at = None
                        doc.heartbeat_token = None
                    extracting_docs.append(doc)
            await session.commit()

            handler = get_background_handler()
            for doc in extracting_docs:
                await handler.launch("document_extract", document_id=doc.id)
                logger.info("Re-fired extraction for document %s", doc.id)
            for doc in indexing_docs:
                await handler.launch("document_index", document_id=doc.id)
                logger.info("Re-fired indexing for document %s", doc.id)
    finally:
        await engine.dispose()


async def _retry_pending_deliveries() -> None:
    """Retry due notification deliveries (transient external-delivery failures).

    Runs as a sweep inside the recovery loop. Uses the shared session pool;
    the ``async with`` block rolls back automatically if a SQLAlchemy-level
    error escapes, so no partial state is committed.
    """
    from app.db.session import AsyncSessionLocal
    from app.services.core.notifications.dispatcher import retry_pending

    async with AsyncSessionLocal() as session:
        count = await retry_pending(session)
        await session.commit()
    if count:
        logger.info("Delivery retry sweep: retried %d deliveries", count)
    else:
        logger.debug("Delivery retry sweep: no deliveries due")


async def _recovery_loop() -> None:
    """Periodically re-run the stalled-jobs/stalled-docs sweeps and retry
    due notification deliveries.

    The startup sweep covers cold boots for job/document recovery; this loop
    covers steady-state autoscaled deployments where new pods don't boot for
    hours. The delivery-retry sweep is loop-only (no startup sweep — it does
    outbound network I/O and must not block boot). Each sweep is independent
    — exceptions inside one don't kill the others, and don't kill the loop.

    Set BATCHRITE_RECOVERY_INTERVAL_SECONDS=0 to disable — this also
    disables notification delivery retries.
    """
    interval = settings.recovery_interval_seconds
    if not interval or interval <= 0:
        logger.warning(
            "Recovery loop disabled (interval <= 0) — notification "
            "delivery retries are also OFF"
        )
        return

    while True:
        try:
            await _recover_stalled_jobs()
        except Exception:
            logger.exception("Recovery loop: job sweep failed")
        try:
            await _recover_stalled_documents()
        except Exception:
            logger.exception("Recovery loop: doc sweep failed")
        try:
            await _retry_pending_deliveries()
        except Exception:
            logger.exception("Recovery loop: delivery retry sweep failed")
        await asyncio.sleep(interval)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan: recover stalled work and start heartbeat."""
    # F-0075: load unit op libraries
    from app.services.protocols import library_registry

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

    # Seed system document templates: copies bundled .docx files and
    # ensures system-wide DocumentTemplate rows exist (idempotent).
    try:
        from app.db.seed import seed_document_templates
        from app.db.session import AsyncSessionLocal

        async with AsyncSessionLocal() as session:
            await seed_document_templates(session)
            await session.commit()
    except Exception:
        logger.exception("System document template seeding failed on startup")

    # Make the cursive fallback font visible to LibreOffice for PDF
    # rendering (F-0080)
    from app.services.documents.font_setup import ensure_cursive_font_registered

    ensure_cursive_font_registered()

    from app.services.lifecycle import loops_client

    if loops_client.is_configured():
        logger.info("Loops CRM integration: ENABLED")
    else:
        logger.info("Loops CRM integration: DISABLED (BATCHRITE_LOOPS_API_KEY unset)")

    # Start the heartbeat background task
    heartbeat_task = asyncio.create_task(_heartbeat_loop())
    recovery_task = asyncio.create_task(_recovery_loop())

    yield

    # Shutdown: cancel heartbeat
    heartbeat_task.cancel()
    try:
        await heartbeat_task
    except asyncio.CancelledError:
        pass
    recovery_task.cancel()
    try:
        await recovery_task
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
        "http://localhost:5203",  # Worktree 3 dev (F-0083)
        "http://100.120.2.59:5174",
        "http://localhost:5176",  # Playwright E2E tests
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Translate a raced slug-uniqueness violation into the standard HTTP 422.
# assign_slug does a pre-check, but a concurrent insert can still slip past
# it; the DB unique constraints are the real guard. Without this handler the
# IntegrityError would surface as an unhandled 500. Non-slug IntegrityErrors
# are re-raised so their existing 500 behaviour is unchanged.
from fastapi import Request
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError

from app.services.slugs import is_slug_conflict


@app.exception_handler(IntegrityError)
async def _integrity_error_handler(request: Request, exc: IntegrityError):
    if is_slug_conflict(exc):
        return JSONResponse(
            status_code=422,
            content={
                "detail": {
                    "code": "SLUG_CONFLICT",
                    "message": (
                        "An item with that name already exists. "
                        "Please choose a different name."
                    ),
                }
            },
        )
    raise exc


@app.get("/health")
async def health_check():
    return {"status": "ok", "service": "batchrite-backend"}


from app.api.endpoints import (
    admin,
    ai,
    auth,
    batch_record_import,
    billing,
    chat,
    dashboard,
    equipment,
    experiments,
    export_data,
    iam,
    internal,
    legal,
    library,
    notifications,
    offline,
    onboarding,
    project_members,
    projects,
    protocol_pdfs,
    protocol_versions,
    protocols,
    runs,
    sites,
    sync,
    template_convert,
    templates,
    unit_ops,
)

app.include_router(internal.router)  # no prefix — router already has /internal
app.include_router(admin.router, prefix="/admin", tags=["admin"])
app.include_router(auth.router, prefix="/auth", tags=["auth"])
app.include_router(projects.router, prefix="/projects", tags=["projects"])
app.include_router(iam.router, prefix="/iam", tags=["iam"])
app.include_router(unit_ops.router, tags=["unit-ops"])
# protocol_versions registered first so its literal-path routes (e.g.
# /protocols/awaiting-my-approval) win over /protocols/{protocol_id} in
# protocols.router. (F-0066)
app.include_router(protocol_versions.router, tags=["protocol-versions"])
app.include_router(protocols.router, tags=["protocols"])
app.include_router(protocol_pdfs.router, tags=["protocol-pdfs"])
app.include_router(runs.router, tags=["runs"])
app.include_router(experiments.router, tags=["experiments"])
app.include_router(batch_record_import.router, tags=["batch-record-import"])
app.include_router(export_data.router, tags=["export"])
app.include_router(project_members.router, tags=["project-members"])
app.include_router(sites.router, tags=["sites"])
app.include_router(equipment.router)  # prefix="/equipment" defined on the router
app.include_router(ai.router, prefix="/ai", tags=["ai"])
app.include_router(dashboard.router, prefix="/dashboard", tags=["dashboard"])
app.include_router(
    notifications.router, prefix="/notifications", tags=["notifications"]
)
app.include_router(library.router, prefix="/library", tags=["library"])
app.include_router(templates.router, tags=["templates"])
app.include_router(
    template_convert.router, tags=["template-convert"]
)
app.include_router(chat.router, prefix="/chat", tags=["chat"])


def _register_offline_routers(target_app, current_settings):
    """Register offline/PWA routers iff the feature flag is on (TD-0082)."""
    if current_settings.features.offline_mode.enabled:
        target_app.include_router(offline.router, tags=["offline"])
        target_app.include_router(sync.router, tags=["sync"])


_register_offline_routers(app, settings)
app.include_router(onboarding.router, prefix="/onboarding", tags=["onboarding"])
app.include_router(billing.router, prefix="/billing", tags=["billing"])
app.include_router(legal.router, prefix="/legal", tags=["legal"])

# Dev-only endpoints (webhook echo, etc.)
if settings.debug:
    from app.api.endpoints import dev

    app.include_router(dev.router, prefix="/dev", tags=["dev"])

# Ensure uploads root directory exists
Path("./uploads").mkdir(parents=True, exist_ok=True)
