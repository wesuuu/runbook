from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(
    title="Runbook AI Co-Pilot",
    description="Backend for the AI-Powered Co-Pilot for Process Development",
    version="0.1.0",
)

# CORS Configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
async def health_check():
    return {"status": "ok", "service": "runbook-backend"}


from app.api.endpoints import auth, projects, iam, science

app.include_router(auth.router, prefix="/auth", tags=["auth"])
app.include_router(projects.router, prefix="/projects", tags=["projects"])
app.include_router(iam.router, prefix="/iam", tags=["iam"])
app.include_router(science.router, prefix="/science", tags=["science"])
