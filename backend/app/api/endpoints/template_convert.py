"""Template conversion endpoints — upload → convert → refine → save.

Dedicated endpoints for converting filled SOPs/batch records into
reusable Jinja2 DOCX templates via an AI agent.
"""

import logging
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user
from app.db.session import get_db
from app.models.iam import User
from app.schemas.template_convert import ConvertResponse, RefineRequest, SaveRequest
from app.schemas.templates import DocumentTemplateResponse
from app.services.template_converter import (
    ConversionState,
    convert_document,
    refine_template,
    reupload_template,
    save_to_library,
)

logger = logging.getLogger(__name__)
router = APIRouter()

ALLOWED_INPUT_TYPES = {
    "application/pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "image/png",
    "image/jpeg",
    "image/jpg",
}
MAX_INPUT_SIZE = 20 * 1024 * 1024  # 20 MB


def _require_org(user: User) -> UUID:
    """Extract org_id from user, raise 400 if missing."""
    if not user.selected_org_id:
        raise HTTPException(status_code=400, detail="No organization selected")
    return user.selected_org_id


@router.post("/templates/convert", response_model=ConvertResponse)
async def convert_template(
    file: UploadFile,
    template_type: str = Form(...),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Upload a filled document and convert it to a Jinja2 DOCX template."""
    org_id = _require_org(user)

    if template_type not in ("SOP", "BATCH_RECORD"):
        raise HTTPException(
            status_code=422, detail="template_type must be SOP or BATCH_RECORD"
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

    try:
        result = await convert_document(
            db,
            org_id,
            file_bytes,
            file.filename or "document",
            template_type,
        )
    except Exception:
        logger.exception("Template conversion failed")
        raise HTTPException(
            status_code=500, detail="Template conversion failed"
        )

    return result


@router.post(
    "/templates/conversions/{conversion_id}/refine",
    response_model=ConvertResponse,
)
async def refine_conversion(
    conversion_id: UUID,
    body: RefineRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
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
        raise HTTPException(
            status_code=500, detail="Template refinement failed"
        )

    return result


@router.post(
    "/templates/conversions/{conversion_id}/reupload",
    response_model=ConvertResponse,
)
async def reupload_template_file(
    conversion_id: UUID,
    file: UploadFile,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Re-upload a manually edited template, re-render and re-validate."""
    org_id = _require_org(user)
    state = ConversionState(org_id, conversion_id)
    if not state.exists("template.docx"):
        raise HTTPException(status_code=404, detail="Conversion not found")

    file_bytes = await file.read()

    try:
        result = await reupload_template(db, org_id, state, file_bytes)
    except Exception:
        logger.exception("Template reupload failed")
        raise HTTPException(
            status_code=500, detail="Template reupload failed"
        )

    return result


@router.post("/templates/conversions/{conversion_id}/save")
async def save_conversion(
    conversion_id: UUID,
    body: SaveRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Save the converted template to the document template library."""
    org_id = _require_org(user)
    state = ConversionState(org_id, conversion_id)
    if not state.exists("template.docx"):
        raise HTTPException(status_code=404, detail="Conversion not found")

    if body.template_type not in ("SOP", "BATCH_RECORD"):
        raise HTTPException(
            status_code=422, detail="template_type must be SOP or BATCH_RECORD"
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
            status_code=500, detail="Failed to save template to library"
        )

    return result


@router.get("/templates/conversions/{conversion_id}/preview.pdf")
async def get_preview(
    conversion_id: UUID,
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


@router.get("/templates/conversions/{conversion_id}/template.docx")
async def get_template_file(
    conversion_id: UUID,
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
            "application/vnd.openxmlformats-officedocument"
            ".wordprocessingml.document"
        ),
        filename="template.docx",
    )
