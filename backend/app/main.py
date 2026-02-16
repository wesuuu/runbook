from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(
    title="Runbook AI Co-Pilot",
    description="Backend for the AI-Powered Co-Pilot for Process Development",
    version="0.1.0",
)

# CORS Configuration
origins = [
    "http://localhost:5173",
    "http://localhost:5174",
    "http://localhost:5175",
    "http://localhost:5176",
    "http://localhost:5177", # Subagent often uses this port
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],  # SvelteKit default port
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/health")
async def health_check():
    return {"status": "ok", "service": "runbook-backend"}

from app.api.endpoints import projects, iam, science

app.include_router(projects.router, prefix="/projects", tags=["projects"])
app.include_router(iam.router, prefix="/iam", tags=["iam"])
app.include_router(science.router, prefix="/science", tags=["science"])
async def root():
    return {"message": "Welcome to Runbook AI Co-Pilot API"}
