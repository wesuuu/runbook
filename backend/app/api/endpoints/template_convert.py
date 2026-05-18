"""Template conversion endpoints — upload → convert → refine → save.

Dedicated endpoints for converting filled SOPs/batch records into
reusable Jinja2 DOCX templates via an AI agent. Progress is streamed
to the frontend via Server-Sent Events (SSE).
"""

import asyncio
import json
import logging
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, Response
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool
from starlette.responses import StreamingResponse
from ulid import ULID

from app.core.config import settings
from app.core.deps import get_current_user, require_active_subscription
from app.db.session import get_db
from app.models.iam import User
from app.schemas.template_convert import (
    ConvertResponse,
    ConvertStartResponse,
    RefineRequest,
    SaveRequest,
)
from app.services.protocols.template_converter import (
    ConversionState,
    _active_streams,
    convert_document,
    refine_template,
    reupload_template,
    save_to_library,
)

logger = logging.getLogger(__name__)
router = APIRouter()

ALLOWED_INPUT_TYPES = {
    "application/vnd.openxmlformats-officedocument" ".wordprocessingml.document",
}
MAX_INPUT_SIZE = 20 * 1024 * 1024  # 20 MB


def _require_org(user: User) -> UUID:
    """Extract org_id from user, raise 400 if missing."""
    if not user.selected_org_id:
        raise HTTPException(status_code=400, detail="No organization selected")
    return user.selected_org_id


async def _preflight_ai_check(db: AsyncSession, org_id: UUID) -> None:
    """Validate the template_convert AI capability is configured."""
    from app.services.ai.ai_config import get_model

    try:
        await get_model("template_convert", db, org_id=org_id)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))


async def _run_conversion_background(
    org_id: UUID,
    file_bytes: bytes,
    filename: str,
    template_type: str,
    conversion_id: str,
) -> None:
    """Run the conversion in a background task with its own DB session."""
    engine = create_async_engine(settings.database_url, poolclass=NullPool)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    try:
        async with session_factory() as db:
            await convert_document(
                db,
                org_id,
                file_bytes,
                filename,
                template_type,
                conversion_id=conversion_id,
            )
    except Exception:
        logger.exception("Background template conversion failed")
    finally:
        await engine.dispose()


@router.post(
    "/templates/convert",
    response_model=ConvertStartResponse,
    status_code=202,
)
async def convert_template(
    file: UploadFile,
    template_type: str = Form(...),
    background_tasks: BackgroundTasks = BackgroundTasks(),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
    _: User = Depends(require_active_subscription()),
):
    """Upload a filled document and start async conversion.

    Returns immediately with a conversion_id. Connect to the
    /events SSE endpoint for real-time progress.
    """
    org_id = _require_org(user)

    if template_type not in ("SOP", "BATCH_RECORD"):
        raise HTTPException(
            status_code=422,
            detail="template_type must be SOP or BATCH_RECORD",
        )

    content_type = file.content_type or ""
    if content_type not in ALLOWED_INPUT_TYPES:
        raise HTTPException(
            status_code=422,
            detail=f"Unsupported file type: {content_type}",
        )

    file_bytes = await file.read()
    if len(file_bytes) > MAX_INPUT_SIZE:
        raise HTTPException(status_code=413, detail="File exceeds 20MB limit")

    await _preflight_ai_check(db, org_id)

    conversion_id = str(ULID())

    background_tasks.add_task(
        _run_conversion_background,
        org_id,
        file_bytes,
        file.filename or "document",
        template_type,
        conversion_id,
    )

    return ConvertStartResponse(
        conversion_id=conversion_id,
        status="processing",
    )


@router.get("/templates/conversions/{conversion_id}/events")
async def conversion_events(
    conversion_id: str,
    user: User = Depends(get_current_user),
):
    """SSE stream of conversion progress events.

    Streams tool_call, tool_result, complete, and error events
    as the AI agent works through the conversion.
    """
    _require_org(user)

    stream_key = str(conversion_id)

    async def event_generator():
        # Wait for stream to appear (background task may not have
        # started yet)
        for _ in range(50):  # 5 seconds max wait
            if stream_key in _active_streams:
                break
            await asyncio.sleep(0.1)

        stream = _active_streams.get(stream_key)
        if stream is None:
            yield ("event: error\n" 'data: {"message": "Conversion not found"}\n\n')
            return

        async for event_type, data_json in stream.iter_events():
            yield f"event: {event_type}\ndata: {data_json}\n\n"

        # Cleanup after stream ends
        _active_streams.pop(stream_key, None)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.post(
    "/templates/conversions/{conversion_id}/refine",
    response_model=ConvertResponse,
)
async def refine_conversion(
    conversion_id: str,
    body: RefineRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
    _: User = Depends(require_active_subscription()),
):
    """Refine an existing conversion via natural language instruction."""
    org_id = _require_org(user)
    state = ConversionState(org_id, conversion_id)
    if not state.exists("template.docx"):
        raise HTTPException(status_code=404, detail="Conversion not found")

    try:
        result = await refine_template(db, org_id, state, body.instruction)
    except Exception:
        logger.exception("Template refinement failed")
        raise HTTPException(status_code=500, detail="Template refinement failed")

    return result


@router.post(
    "/templates/conversions/{conversion_id}/reupload",
    response_model=ConvertResponse,
)
async def reupload_template_file(
    conversion_id: str,
    file: UploadFile,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
    _: User = Depends(require_active_subscription()),
):
    """Re-upload a manually edited template."""
    org_id = _require_org(user)
    state = ConversionState(org_id, conversion_id)
    if not state.exists("template.docx"):
        raise HTTPException(status_code=404, detail="Conversion not found")

    file_bytes = await file.read()

    try:
        result = await reupload_template(db, org_id, state, file_bytes)
    except Exception:
        logger.exception("Template reupload failed")
        raise HTTPException(status_code=500, detail="Template reupload failed")

    return result


@router.post("/templates/conversions/{conversion_id}/save")
async def save_conversion(
    conversion_id: str,
    body: SaveRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
    _: User = Depends(require_active_subscription()),
):
    """Save the converted template to the document template library."""
    org_id = _require_org(user)
    state = ConversionState(org_id, conversion_id)
    if not state.exists("template.docx"):
        raise HTTPException(status_code=404, detail="Conversion not found")

    if body.template_type not in ("SOP", "BATCH_RECORD"):
        raise HTTPException(
            status_code=422,
            detail="template_type must be SOP or BATCH_RECORD",
        )

    try:
        result = await save_to_library(
            db,
            org_id,
            user.id,
            state,
            body.name,
            body.template_type,
            body.description,
            body.project_id,
            body.set_as_default,
        )
        await db.commit()
    except Exception:
        logger.exception("Failed to save template to library")
        raise HTTPException(
            status_code=500,
            detail="Failed to save template to library",
        )

    return result


@router.get("/templates/conversions/{conversion_id}/original.pdf")
async def get_original_pdf(
    conversion_id: str,
    user: User = Depends(get_current_user),
):
    """Serve the original uploaded document as PDF."""
    org_id = _require_org(user)
    state = ConversionState(org_id, conversion_id)
    if not state.exists("original.pdf"):
        raise HTTPException(status_code=404, detail="Original not found")
    return FileResponse(
        state._resolve("original.pdf"),
        media_type="application/pdf",
    )


@router.get("/templates/conversions/{conversion_id}/preview.pdf")
async def get_preview(
    conversion_id: str,
    user: User = Depends(get_current_user),
):
    """Serve the rendered PDF preview."""
    org_id = _require_org(user)
    state = ConversionState(org_id, conversion_id)
    if not state.exists("preview.pdf"):
        raise HTTPException(status_code=404, detail="Preview not found")
    return FileResponse(
        state._resolve("preview.pdf"),
        media_type="application/pdf",
    )


@router.get("/templates/conversions/{conversion_id}/template.pdf")
async def get_template_pdf(
    conversion_id: str,
    user: User = Depends(get_current_user),
):
    """Serve the template as PDF (with Jinja2 syntax visible)."""
    org_id = _require_org(user)
    state = ConversionState(org_id, conversion_id)
    if not state.exists("template.docx"):
        raise HTTPException(status_code=404, detail="Template not found")

    from app.services.protocols.template_converter import _to_pdf

    docx_bytes = state.read("template.docx")
    pdf_bytes = await _to_pdf(docx_bytes, "template.docx")

    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
    )


@router.get("/templates/conversions/{conversion_id}/template.docx")
async def get_template_file(
    conversion_id: str,
    user: User = Depends(get_current_user),
):
    """Serve the generated template DOCX for download."""
    org_id = _require_org(user)
    state = ConversionState(org_id, conversion_id)
    if not state.exists("template.docx"):
        raise HTTPException(status_code=404, detail="Template not found")
    return FileResponse(
        state._resolve("template.docx"),
        media_type=(
            "application/vnd.openxmlformats-officedocument" ".wordprocessingml.document"
        ),
        filename="template.docx",
    )
