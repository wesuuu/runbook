"""Public endpoints for the versioned legal documents (Terms of Service,
Privacy Policy). All endpoints in this router are unauthenticated — they
are intended to be reachable by prospective users from marketing pages,
the login/register footer, and the in-app /legal/accept gate.
"""

from fastapi import APIRouter, HTTPException

from app.legal import service as legal_service

router = APIRouter()


@router.get("/current")
async def get_current() -> dict:
    version = legal_service.get_current_version()
    return {"version": version, "effective_date": version}


@router.get("/versions/{version}/{doc}")
async def get_version(version: str, doc: str) -> dict:
    try:
        return legal_service.get_document(version, doc)
    except (KeyError, ValueError, FileNotFoundError):
        raise HTTPException(status_code=404, detail="Document not found")
