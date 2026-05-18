"""Internal endpoints — only called by trusted in-process subprocesses
(the ext/docling-extractor heartbeat thread today; future cloud-gpu
workers tomorrow). These routes are NOT for clients and are excluded
from the OpenAPI schema.

Auth model: per-job random token written to the Document row when
the job starts, passed back by the worker in X-Heartbeat-Token, and
cleared on any terminal state. There is no JWT here — the token IS
the credential, scoped to one document for one extraction attempt.
"""

from __future__ import annotations

import hmac
from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_db
from app.models.library import Document

router = APIRouter(prefix="/internal", tags=["internal"], include_in_schema=False)


class HeartbeatPayload(BaseModel):
    ts: str  # ISO-8601 from the worker; we use server time for the column


@router.post("/extraction/{document_id}/heartbeat")
async def extraction_heartbeat(
    document_id: UUID,
    payload: HeartbeatPayload,
    x_heartbeat_token: str = Header(...),
    db: AsyncSession = Depends(get_db),
):
    doc = await db.get(Document, document_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="document not found")
    stored = doc.heartbeat_token or ""
    if not hmac.compare_digest(stored, x_heartbeat_token):
        raise HTTPException(status_code=403, detail="invalid heartbeat token")
    doc.last_heartbeat_at = datetime.now(timezone.utc)
    await db.commit()
    return {"ok": True}
