import asyncio
import logging
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import (
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import settings

logger = logging.getLogger(__name__)


async def _recover_stalled_documents() -> None:
    """Find documents stuck in UPLOADED or stale PROCESSING and re-enqueue.

    Called once on startup. Uses SELECT ... FOR UPDATE SKIP LOCKED so
    multiple pods starting simultaneously won't double-process.
    """
    from app.models.library import (
        Document,
        DocumentStatus,
        STALE_PROCESSING_SECONDS,
    )
    from app.services.document_processor import process_document

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
                asyncio.create_task(
                    process_document(doc.id, settings.database_url)
                )
    finally:
        await engine.dispose()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan: recover stalled documents on startup."""
    try:
        await _recover_stalled_documents()
    except Exception:
        logger.exception("Document recovery sweep failed on startup")
    yield


app = FastAPI(
    title="Runbook AI Co-Pilot",
    description="Backend for the AI-Powered Co-Pilot for Process Development",
    version="0.1.0",
    lifespan=lifespan,
)

# CORS Configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://100.120.2.59:5174",
        "http://localhost:5176",  # Playwright E2E tests
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
async def health_check():
    return {"status": "ok", "service": "runbook-backend"}


from app.api.endpoints import (
    auth,
    projects,
    iam,
    unit_ops,
    protocols,
    protocol_versions,
    protocol_pdfs,
    runs,
    export_data,
    project_members,
    ai,
    dashboard,
    notifications,
    offline,
    sync,
    library,
)

app.include_router(auth.router, prefix="/auth", tags=["auth"])
app.include_router(projects.router, prefix="/projects", tags=["projects"])
app.include_router(iam.router, prefix="/iam", tags=["iam"])
app.include_router(unit_ops.router, prefix="/science", tags=["science"])
app.include_router(protocols.router, prefix="/science", tags=["science"])
app.include_router(protocol_versions.router, prefix="/science", tags=["science"])
app.include_router(protocol_pdfs.router, prefix="/science", tags=["science"])
app.include_router(runs.router, prefix="/science", tags=["science"])
app.include_router(export_data.router, prefix="/science", tags=["science"])
app.include_router(project_members.router, prefix="/science", tags=["science"])
app.include_router(ai.router, prefix="/ai", tags=["ai"])
app.include_router(dashboard.router, prefix="/dashboard", tags=["dashboard"])
app.include_router(notifications.router, prefix="/notifications", tags=["notifications"])
app.include_router(library.router, prefix="/library", tags=["library"])
app.include_router(offline.router, tags=["offline"])
app.include_router(sync.router, tags=["sync"])

# Dev-only endpoints (webhook echo, etc.)
if settings.debug:
    from app.api.endpoints import dev
    app.include_router(dev.router, prefix="/dev", tags=["dev"])

# Static file serving for uploaded images
_uploads_dir = Path(settings.image_storage_path)
_uploads_dir.mkdir(parents=True, exist_ok=True)
app.mount("/uploads/images", StaticFiles(directory=str(_uploads_dir)), name="uploads")

# Static file serving for avatars
_avatars_dir = Path("./uploads/avatars")
_avatars_dir.mkdir(parents=True, exist_ok=True)
app.mount("/uploads/avatars", StaticFiles(directory=str(_avatars_dir)), name="avatars")

# Static file serving for documents
_docs_dir = Path(settings.document_storage_path)
_docs_dir.mkdir(parents=True, exist_ok=True)
app.mount(
    "/uploads/documents",
    StaticFiles(directory=str(_docs_dir)),
    name="documents",
)
