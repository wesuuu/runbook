"""Document template management endpoints.

CRUD for user-uploaded .docx templates + preview rendering.
"""

import asyncio
import json
import logging
import re
import tempfile
from pathlib import Path
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, Form, HTTPException, Query, UploadFile
from fastapi.responses import Response
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user, require_active_subscription
from app.db.session import get_db
from app.models.iam import (ObjectType, Organization, OrganizationMember,
                            OrgRole, PermissionLevel, User)
from app.models.science import Project
from app.models.templates import DocumentTemplate
from app.schemas.templates import (DocumentTemplateResponse,
                                   DocumentTemplateUpdate)
from app.services.core.file_storage import FileStorageService
from app.services.core.permissions import check_permission
from app.services.protocols.template_engine import (get_mock_context,
                                                    parse_template,
                                                    render_to_pdf)

logger = logging.getLogger(__name__)

router = APIRouter()

MAX_TEMPLATE_SIZE = 10 * 1024 * 1024  # 10 MB
ALLOWED_TEMPLATE_MIME = {
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}
TEMPLATE_BASE_DIR = "document_templates"


# ── Helpers ──


async def _require_org_admin(
    db: AsyncSession,
    user_id: UUID,
    org_id: UUID,
) -> None:
    """Raise 403 if user is not ADMIN in the given org."""
    result = await db.execute(
        select(OrganizationMember).where(
            OrganizationMember.user_id == user_id,
            OrganizationMember.organization_id == org_id,
            OrganizationMember.roles.contains([OrgRole.ADMIN.value]),
        )
    )
    if result.scalar_one_or_none() is None:
        raise HTTPException(status_code=403, detail="Org admin role required")


async def _require_template_admin(
    db: AsyncSession,
    user_id: UUID,
    org_id: UUID,
    project_id: UUID | None,
) -> None:
    """Require org admin (org-scoped) or project admin (project-scoped)."""
    if project_id:
        allowed = await check_permission(
            db,
            user_id,
            ObjectType.PROJECT,
            project_id,
            PermissionLevel.ADMIN,
        )
        if not allowed:
            raise HTTPException(status_code=403, detail="Project admin role required")
    else:
        await _require_org_admin(db, user_id, org_id)


def _sanitize_filename(name: str) -> str:
    """Sanitize a filename for safe filesystem storage."""
    name = Path(name).name  # strip directory components
    name = re.sub(r"[^\w\s\-.]", "_", name)  # replace unsafe chars
    name = re.sub(r"\s+", "_", name)  # collapse whitespace
    return name or "template.docx"


def _validate_template_type(template_type: str) -> None:
    if template_type not in ("SOP", "BATCH_RECORD"):
        raise HTTPException(
            status_code=422,
            detail="template_type must be SOP or BATCH_RECORD",
        )


async def _validate_upload(file: UploadFile) -> bytes:
    """Validate and read an uploaded .docx file. Returns file content."""
    if file.content_type not in ALLOWED_TEMPLATE_MIME:
        raise HTTPException(status_code=422, detail="Only .docx files are allowed")
    content = await file.read()
    if len(content) > MAX_TEMPLATE_SIZE:
        raise HTTPException(status_code=413, detail="File exceeds 10MB limit")
    return content


def _store_template_bytes(
    storage: FileStorageService,
    content: bytes,
    org_id: UUID,
    filename: str,
) -> str:
    """Write template bytes to storage, return relative path."""
    parts = [str(org_id), TEMPLATE_BASE_DIR, filename]
    relative_path = str(Path(*parts))
    full_path = storage.storage_root / relative_path
    full_path.parent.mkdir(parents=True, exist_ok=True)
    full_path.write_bytes(content)
    return relative_path


async def _set_template_as_default(
    db: AsyncSession,
    template: DocumentTemplate,
    org_id: UUID,
    project_id: UUID | None,
) -> None:
    """Set a template as the default for its type on the given scope.

    Also clears is_default on the previous default template of the same
    type/scope so the DB column stays in sync.
    """
    col_name = (
        "default_sop_template_id"
        if template.template_type == "SOP"
        else "default_batch_record_template_id"
    )

    # Clear is_default on the previous default
    prev_id = None
    if project_id:
        result = await db.execute(select(Project).where(Project.id == project_id))
        proj = result.scalar_one()
        prev_id = getattr(proj, col_name, None)
        setattr(proj, col_name, template.id)
    else:
        result = await db.execute(select(Organization).where(Organization.id == org_id))
        org = result.scalar_one()
        prev_id = getattr(org, col_name, None)
        setattr(org, col_name, template.id)

    if prev_id and prev_id != template.id:
        prev_result = await db.execute(
            select(DocumentTemplate).where(DocumentTemplate.id == prev_id)
        )
        prev_template = prev_result.scalar_one_or_none()
        if prev_template:
            prev_template.is_default = False

    template.is_default = True


def _get_default_ids(org, project=None) -> set[UUID]:
    """Collect all current default template IDs for the org + optional project."""
    ids = set()
    for attr in ("default_sop_template_id", "default_batch_record_template_id"):
        val = getattr(org, attr, None)
        if val:
            ids.add(val)
        if project:
            val = getattr(project, attr, None)
            if val:
                ids.add(val)
    return ids


# ── Endpoints ──


@router.post("/templates/preview")
async def preview_template(
    file: UploadFile,
    template_type: str = Form(...),
    project_id: Optional[UUID] = Form(None),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_active_subscription()),
):
    """Upload a .docx, render against mock data, return PDF + variable report."""
    org_id = user.selected_org_id
    if not org_id:
        raise HTTPException(status_code=400, detail="No organization selected")

    _validate_template_type(template_type)
    await _require_template_admin(db, user.id, org_id, project_id)
    content = await _validate_upload(file)

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir) / "template.docx"
        tmp_path.write_bytes(content)

        try:
            recognized, unrecognized = parse_template(tmp_path)
        except Exception:
            raise HTTPException(status_code=422, detail="Invalid .docx template")

        mock_ctx = get_mock_context()
        pdf_bytes = await asyncio.to_thread(render_to_pdf, tmp_path, mock_ctx)

    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={
            "X-Recognized-Variables": json.dumps(recognized),
            "X-Unrecognized-Variables": json.dumps(unrecognized),
        },
    )


@router.post("/templates", response_model=DocumentTemplateResponse)
async def create_template(
    file: UploadFile,
    name: str = Form(...),
    template_type: str = Form(...),
    description: Optional[str] = Form(None),
    project_id: Optional[UUID] = Form(None),
    set_as_default: bool = Form(False),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_active_subscription()),
):
    """Upload and store a .docx template."""
    org_id = user.selected_org_id
    if not org_id:
        raise HTTPException(status_code=400, detail="No organization selected")

    _validate_template_type(template_type)
    await _require_template_admin(db, user.id, org_id, project_id)
    content = await _validate_upload(file)

    # Filename uniqueness within org
    sanitized = _sanitize_filename(file.filename or "template.docx")
    existing = await db.execute(
        select(DocumentTemplate).where(
            DocumentTemplate.org_id == org_id,
            DocumentTemplate.original_filename == sanitized,
            DocumentTemplate.status == "ACTIVE",
        )
    )
    if existing.scalar_one_or_none():
        raise HTTPException(
            status_code=409,
            detail=f"A template named '{sanitized}' already exists. Rename the file.",
        )

    # Parse variables from the .docx
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir) / sanitized
        tmp_path.write_bytes(content)
        try:
            recognized, unrecognized = parse_template(tmp_path)
        except Exception:
            raise HTTPException(status_code=422, detail="Invalid .docx template")

    # Store file
    storage = FileStorageService()
    file_path = _store_template_bytes(storage, content, org_id, sanitized)

    # Create DB record
    template = DocumentTemplate(
        org_id=org_id,
        project_id=project_id,
        uploaded_by_id=user.id,
        name=name,
        description=description,
        template_type=template_type,
        file_path=file_path,
        original_filename=sanitized,
        mime_type=file.content_type or "",
        file_size_bytes=len(content),
        variables={"recognized": recognized, "unrecognized": unrecognized},
    )
    db.add(template)

    if set_as_default:
        await db.flush()  # ensure template.id is assigned
        await _set_template_as_default(db, template, org_id, project_id)

    await db.commit()
    await db.refresh(template)

    # Compute is_current_default for response
    resp = DocumentTemplateResponse.model_validate(template)
    resp.is_current_default = set_as_default
    return resp


@router.get("/templates", response_model=list[DocumentTemplateResponse])
async def list_templates(
    template_type: Optional[str] = Query(None),
    status: str = Query("ACTIVE"),
    project_id: Optional[UUID] = Query(None),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List templates visible to the current user's org."""
    org_id = user.selected_org_id
    if not org_id:
        raise HTTPException(status_code=400, detail="No organization selected")

    # Org templates + system templates
    query = select(DocumentTemplate).where(
        or_(
            DocumentTemplate.org_id == org_id,
            DocumentTemplate.is_system == True,
        )
    )
    query = query.where(DocumentTemplate.status == status)

    if template_type:
        _validate_template_type(template_type)
        query = query.where(DocumentTemplate.template_type == template_type)

    if project_id:
        # Include project-scoped + org-scoped (project_id is None)
        query = query.where(
            or_(
                DocumentTemplate.project_id == project_id,
                DocumentTemplate.project_id == None,
            )
        )

    result = await db.execute(query.order_by(DocumentTemplate.created_at.desc()))
    templates = result.scalars().all()

    # Fetch current defaults
    org_result = await db.execute(select(Organization).where(Organization.id == org_id))
    org = org_result.scalar_one()
    default_ids = _get_default_ids(org)

    if project_id:
        proj_result = await db.execute(select(Project).where(Project.id == project_id))
        proj = proj_result.scalar_one_or_none()
        if proj:
            default_ids = _get_default_ids(org, proj)

    responses = []
    for t in templates:
        resp = DocumentTemplateResponse.model_validate(t)
        resp.is_current_default = t.id in default_ids
        responses.append(resp)

    return responses


@router.get("/templates/variables")
async def get_template_variables(
    user: User = Depends(get_current_user),
):
    """Return the full variable reference for template authors."""
    return {
        "protocol": [
            {
                "name": "protocol_name",
                "description": "Protocol name",
                "example": "Buffer Preparation",
            },
            {
                "name": "protocol_description",
                "description": "Protocol description",
                "example": "Prepare PBS buffer...",
            },
            {"name": "version_number", "description": "Version number", "example": 3},
            {
                "name": "created_at",
                "description": "Last modified date",
                "example": "January 15, 2026",
            },
        ],
        "run": [
            {"name": "run_name", "description": "Run name", "example": "Run-2026-001"},
            {"name": "run_status", "description": "Run status", "example": "COMPLETED"},
            {
                "name": "started_at",
                "description": "Run start time",
                "example": "2026-01-20 08:00",
            },
            {
                "name": "completed_at",
                "description": "Run completion time",
                "example": "2026-01-20 14:30",
            },
        ],
        "project": [
            {
                "name": "project_name",
                "description": "Project name",
                "example": "AAV Campaign Q1",
            },
            {
                "name": "organization_name",
                "description": "Organization name",
                "example": "Acme Therapeutics",
            },
        ],
        "loops": [
            {
                "name": "roles",
                "description": "List of roles with .name, .steps, .sop_header, .br_header",
                "type": "loop",
            },
            {
                "name": "steps",
                "description": "Steps within a role (batch record)",
                "type": "loop",
            },
            {
                "name": "role.sop_steps",
                "description": "Steps within a role (SOP)",
                "type": "loop",
            },
            {
                "name": "notes",
                "description": "Run-level notes with .meta, .content",
                "type": "loop",
            },
            {
                "name": "figures",
                "description": "Image attachments with .image, .number, .filename",
                "type": "loop",
            },
            {
                "name": "non_image_attachments",
                "description": "Non-image attachments with .filename, .type, .scope",
                "type": "loop",
            },
        ],
        "step_fields": [
            {"name": "step.name", "description": "Step name"},
            {
                "name": "step.description",
                "description": "Step description with params filled in",
            },
            {"name": "step.duration_min", "description": "Duration in minutes"},
            {
                "name": "step.value_display",
                "description": "Parameter values (RichText, use {{r }})",
                "syntax": "{{r step.value_display }}",
            },
            {"name": "step.initials", "description": "Completer initials"},
            {
                "name": "step.notes_display",
                "description": "Step-level notes + figure cross-references",
            },
            {"name": "step.role_name", "description": "Role name for this step"},
        ],
        "special": [
            {
                "name": "page_break",
                "description": "Insert a page break",
                "syntax": "{{r page_break }}",
            },
            {
                "name": "is_role_based",
                "description": "Boolean — true if protocol uses swimlane roles",
            },
            {
                "name": "protocol_subtitle",
                "description": "Run name + description (RichText)",
                "syntax": "{{r protocol_subtitle }}",
            },
        ],
    }


@router.get("/templates/{template_id}", response_model=DocumentTemplateResponse)
async def get_template(
    template_id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get a single template by ID."""
    org_id = user.selected_org_id
    result = await db.execute(
        select(DocumentTemplate).where(DocumentTemplate.id == template_id)
    )
    template = result.scalar_one_or_none()
    if not template:
        raise HTTPException(status_code=404, detail="Template not found")

    # Verify access: must be system or belong to user's org
    if not template.is_system and template.org_id != org_id:
        raise HTTPException(status_code=404, detail="Template not found")

    # Compute is_current_default
    org_result = await db.execute(select(Organization).where(Organization.id == org_id))
    org = org_result.scalar_one()
    default_ids = _get_default_ids(org)

    resp = DocumentTemplateResponse.model_validate(template)
    resp.is_current_default = template.id in default_ids
    return resp


@router.put("/templates/{template_id}", response_model=DocumentTemplateResponse)
async def update_template(
    template_id: UUID,
    body: DocumentTemplateUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_active_subscription()),
):
    """Update template metadata, archive/unarchive, or set as default."""
    org_id = user.selected_org_id
    result = await db.execute(
        select(DocumentTemplate).where(DocumentTemplate.id == template_id)
    )
    template = result.scalar_one_or_none()
    if not template:
        raise HTTPException(status_code=404, detail="Template not found")

    # System templates are immutable
    if template.is_system:
        raise HTTPException(
            status_code=403, detail="System templates cannot be modified"
        )

    # Verify ownership + admin permission
    if template.org_id != org_id:
        raise HTTPException(status_code=404, detail="Template not found")
    await _require_template_admin(db, user.id, org_id, template.project_id)

    # Apply updates
    if body.name is not None:
        template.name = body.name
    if body.description is not None:
        template.description = body.description

    if body.status is not None:
        if body.status not in ("ACTIVE", "ARCHIVED"):
            raise HTTPException(
                status_code=422, detail="status must be ACTIVE or ARCHIVED"
            )
        template.status = body.status
        if body.status == "ARCHIVED":
            from datetime import datetime, timezone

            template.archived_at = datetime.now(timezone.utc)
            template.archived_by_id = user.id
        elif body.status == "ACTIVE":
            template.archived_at = None
            template.archived_by_id = None

    if body.set_as_default is True:
        await _set_template_as_default(db, template, org_id, template.project_id)

    await db.commit()
    await db.refresh(template)

    # Compute is_current_default
    org_result = await db.execute(select(Organization).where(Organization.id == org_id))
    org = org_result.scalar_one()
    default_ids = _get_default_ids(org)

    resp = DocumentTemplateResponse.model_validate(template)
    resp.is_current_default = template.id in default_ids
    return resp
