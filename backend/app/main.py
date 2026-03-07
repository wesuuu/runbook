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
    allow_origins=["http://localhost:5173", "http://100.120.2.59:5174"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
async def health_check():
    return {"status": "ok", "service": "runbook-backend"}


from app.api.endpoints import auth, projects, iam, science, ai

app.include_router(auth.router, prefix="/auth", tags=["auth"])
app.include_router(projects.router, prefix="/projects", tags=["projects"])
app.include_router(iam.router, prefix="/iam", tags=["iam"])
app.include_router(science.router, prefix="/science", tags=["science"])
app.include_router(ai.router, prefix="/ai", tags=["ai"])

# Static file serving for uploaded images
_uploads_dir = Path(settings.image_storage_path)
_uploads_dir.mkdir(parents=True, exist_ok=True)
app.mount("/uploads/images", StaticFiles(directory=str(_uploads_dir)), name="uploads")
