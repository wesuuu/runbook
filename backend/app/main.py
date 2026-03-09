from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.core.config import settings

app = FastAPI(
    title="Runbook AI Co-Pilot",
    description="Backend for the AI-Powered Co-Pilot for Process Development",
    version="0.1.0",
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
