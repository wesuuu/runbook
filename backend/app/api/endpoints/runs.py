import asyncio
import logging
import uuid as uuid_mod
from datetime import datetime, timezone
from typing import List, Optional
from uuid import UUID

from fastapi import (APIRouter, BackgroundTasks, Depends, Form, HTTPException,
                     Query, Request, UploadFile)
from fastapi.responses import FileResponse, Response
from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from app.api.endpoints.protocol_pdfs import (_load_template,
                                             _resolve_template_path)
from app.core.deps import (get_current_user, get_or_404,
                           get_org_id_from_request,
                           require_active_subscription, require_permission)
from app.db.session import get_db
from app.models.ai import ImageConversation, RunImage
from app.models.execution import AuditLog
from app.models.iam import ObjectType, PermissionLevel, User
from app.models.science import Project, Protocol, Run, RunRoleAssignment, UnitOpDefinition
from app.schemas.science import (RunAttachment, RunAttachmentListResponse,
                                 RunCreate, RunNote, RunNoteCreate,
                                 RunNoteListResponse, RunResponse,
                                 RunRoleAssignmentCreate,
                                 RunRoleAssignmentListResponse,
                                 RunRoleAssignmentResponse, RunUpdate)
from app.services.core.audit import log_audit
from app.services.core.file_storage import IMAGE_MIME_TYPES, FileStorageService
from app.services.core.notifications import send_notification
from app.services.core.permissions import check_permission
from app.services.data.graph_processing import _parse_graph_roles_and_steps
from app.services.protocols.template_engine import build_context, render_to_pdf
from app.services.protocols.validation import assert_no_branch_errors

logger = logging.getLogger(__name__)

router = APIRouter()


def _run_status_str(run_obj: Run) -> str:
    """Extract run status as a plain string."""
    s = run_obj.status
    return s if isinstance(s, str) else s.value


# --- Runs ---


@router.post(
    "/runs",
    response_model=RunResponse,
    status_code=201,
)
async def create_run(
    run_in: RunCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_active_subscription()),
):
    allowed = await check_permission(
        db,
        user.id,
        ObjectType.PROJECT,
        run_in.project_id,
        PermissionLevel.EDIT,
    )
    if not allowed:
        raise HTTPException(
            status_code=403,
            detail="EDIT permission required on project",
        )

    result = await db.execute(select(Project).where(Project.id == run_in.project_id))
    if result.scalar_one_or_none() is None:
        raise HTTPException(status_code=404, detail="Project not found")

    initial_graph = {}
    if run_in.protocol_id:
        result = await db.execute(
            select(Protocol).where(Protocol.id == run_in.protocol_id)
        )
        protocol = result.scalar_one_or_none()
        if protocol is None:
            raise HTTPException(status_code=404, detail="Protocol not found")
        if protocol.status == "ARCHIVED":
            raise HTTPException(
                status_code=400,
                detail="Cannot create run from archived protocol",
            )
        initial_graph = protocol.graph.copy() if protocol.graph else {}
        unit_ops_result = await db.execute(
            select(UnitOpDefinition).where(
                UnitOpDefinition.organization_id == user.selected_org_id
            )
        )
        unit_ops = list(unit_ops_result.scalars().all())
        assert_no_branch_errors(initial_graph, unit_ops)

    run_obj = Run(
        name=run_in.name,
        project_id=run_in.project_id,
        protocol_id=run_in.protocol_id,
        experiment_id=run_in.experiment_id,
        graph=initial_graph,
        execution_data={},
    )
    db.add(run_obj)
    await db.flush()

    await log_audit(
        db,
        user.id,
        "CREATE",
        "Run",
        run_obj.id,
        {"name": run_in.name},
    )

    await db.commit()
    await db.refresh(run_obj)
    return run_obj


@router.get("/runs/{run_id}", response_model=RunResponse)
async def get_run(
    run_id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    allowed = await check_permission(
        db,
        user.id,
        ObjectType.RUN,
        run_id,
        PermissionLevel.VIEW,
    )
    if not allowed:
        raise HTTPException(status_code=403, detail="Insufficient permissions")

    return await get_or_404(db, Run, run_id)


@router.get(
    "/projects/{project_id}/runs",
    response_model=List[RunResponse],
    dependencies=[
        Depends(
            require_permission(ObjectType.PROJECT, "project_id", PermissionLevel.VIEW)
        )
    ],
)
async def list_project_runs(
    project_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Run).where(Run.project_id == project_id))
    return result.scalars().all()


@router.put(
    "/runs/{run_id}",
    response_model=RunResponse,
)
async def update_run(
    run_id: UUID,
    update_data: RunUpdate,
    background_tasks: BackgroundTasks,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_active_subscription()),
):
    allowed = await check_permission(
        db,
        user.id,
        ObjectType.RUN,
        run_id,
        PermissionLevel.EDIT,
    )
    if not allowed:
        raise HTTPException(status_code=403, detail="Insufficient permissions")

    run_obj = await get_or_404(db, Run, run_id)

    # Validate status transitions
    new_status = update_data.status.value if update_data.status else None
    current_status = (
        run_obj.status if isinstance(run_obj.status, str) else run_obj.status.value
    )

    if new_status and new_status != current_status:
        valid_transitions = {
            "PLANNED": {"ACTIVE"},
            "ACTIVE": {"COMPLETED"},
            "COMPLETED": {"EDITED"},
            "EDITED": {"EDITED"},
        }
        allowed_next = valid_transitions.get(current_status, set())
        if new_status not in allowed_next:
            raise HTTPException(
                status_code=422,
                detail=f"Cannot transition from {current_status} to {new_status}",
            )

        if new_status == "ACTIVE":
            # Check that at least one person is assigned to the run
            result = await db.execute(
                select(RunRoleAssignment).where(RunRoleAssignment.run_id == run_id)
            )
            assignments = result.scalars().all()

            if not assignments:
                raise HTTPException(
                    status_code=422,
                    detail="Cannot start run: at least one person must be assigned",
                )

            # Check that all swimlane roles in the graph have assignments
            graph = run_obj.graph or {}
            nodes = graph.get("nodes", [])
            swimlane_nodes = [n for n in nodes if n.get("type") == "swimLane"]

            if swimlane_nodes:
                assigned_lanes = {a.lane_node_id for a in assignments}
                required_lanes = {n["id"] for n in swimlane_nodes}

                if assigned_lanes != required_lanes:
                    raise HTTPException(
                        status_code=422,
                        detail="Cannot start run: not all roles have assigned users",
                    )

            # Set started_by_id when run transitions to ACTIVE
            run_obj.started_by_id = user.id

        elif new_status == "COMPLETED":
            # Validate all unit op steps are completed
            exec_data = update_data.execution_data or run_obj.execution_data or {}
            graph = run_obj.graph or {}
            nodes = graph.get("nodes", [])
            unit_op_ids = [n["id"] for n in nodes if n.get("type") == "unitOp"]

            incomplete = [
                sid
                for sid in unit_op_ids
                if exec_data.get(sid, {}).get("status") != "completed"
            ]
            if incomplete:
                raise HTTPException(
                    status_code=422,
                    detail="Cannot complete run: not all steps are completed",
                )

    # Preserve original_results when transitioning to EDITED or saving
    # while already in EDITED status (GMP audit trail)
    if update_data.execution_data is not None:
        target_status = new_status or current_status
        if target_status == "EDITED":
            old_exec = run_obj.execution_data or {}
            new_exec = update_data.execution_data

            # Build step name + param schema lookup from graph
            graph = run_obj.graph or {}
            _node_map: dict[str, dict] = {}
            for n in graph.get("nodes", []):
                if n.get("type") == "unitOp":
                    _node_map[n["id"]] = n.get("data", {})

            for step_id, new_step in new_exec.items():
                if not isinstance(new_step, dict):
                    continue
                old_step = old_exec.get(step_id, {})
                if not isinstance(old_step, dict):
                    continue

                node_data = _node_map.get(step_id, {})
                step_name = node_data.get("label", step_id)
                param_schema_props = (node_data.get("paramSchema") or {}).get(
                    "properties", {}
                )

                old_results = old_step.get("results", {})
                new_results = new_step.get("results", {})
                # Only set original_results if not already set (preserve
                # the very first completion data) and results differ
                if (
                    old_results
                    and new_results != old_results
                    and "original_results" not in new_step
                ):
                    new_step["original_results"] = old_results
                    new_step["edited_by_user_id"] = str(user.id)
                    new_step["edited_at"] = datetime.now(timezone.utc).isoformat()

                # Audit each individual field change
                if old_results and new_results:
                    for field_key in set(old_results) | set(new_results):
                        old_val = old_results.get(field_key)
                        new_val = new_results.get(field_key)
                        if old_val != new_val:
                            prop = param_schema_props.get(field_key, {})
                            field_label = (
                                prop.get("title") or field_key.replace("_", " ").title()
                            )
                            await log_audit(
                                db,
                                user.id,
                                "STEP_EDIT",
                                "Run",
                                run_obj.id,
                                {
                                    "step_id": step_id,
                                    "step_name": step_name,
                                    "field": field_key,
                                    "field_label": field_label,
                                    "old_value": old_val,
                                    "new_value": new_val,
                                },
                            )

                # Also handle legacy value field
                old_value = old_step.get("value")
                new_value = new_step.get("value")
                if (
                    old_value
                    and new_value != old_value
                    and "original_value" not in new_step
                ):
                    new_step["original_value"] = old_value
                    new_step["edited_by_user_id"] = str(user.id)
                    new_step["edited_at"] = datetime.now(timezone.utc).isoformat()
                    await log_audit(
                        db,
                        user.id,
                        "STEP_EDIT",
                        "Run",
                        run_obj.id,
                        {
                            "step_id": step_id,
                            "step_name": step_name,
                            "field": "value",
                            "field_label": "Value",
                            "old_value": old_value,
                            "new_value": new_value,
                        },
                    )

                # Track step-level notes changes
                old_notes = old_step.get("notes", "")
                new_notes = new_step.get("notes", "")
                if old_notes != new_notes:
                    await log_audit(
                        db,
                        user.id,
                        "STEP_EDIT",
                        "Run",
                        run_obj.id,
                        {
                            "step_id": step_id,
                            "step_name": step_name,
                            "field": "notes",
                            "field_label": "Notes",
                            "old_value": old_notes,
                            "new_value": new_notes,
                        },
                    )

    # Audit log step completions and note changes by diffing execution_data
    # (note changes for EDITED status are handled in the block above)
    if update_data.execution_data is not None:
        old_exec = run_obj.execution_data or {}
        new_exec = update_data.execution_data
        target_status = new_status or current_status

        # Build step name lookup from graph
        _graph = run_obj.graph or {}
        _name_map: dict[str, str] = {}
        for _n in _graph.get("nodes", []):
            if _n.get("type") == "unitOp":
                _name_map[_n["id"]] = _n.get("data", {}).get("label", _n["id"])

        for step_id, step_data in new_exec.items():
            old_step = old_exec.get(step_id, {})
            if not isinstance(step_data, dict):
                continue
            old_status = old_step.get("status")
            new_step_status = step_data.get("status")
            if new_step_status == "completed" and old_status != "completed":
                await log_audit(
                    db,
                    user.id,
                    "STEP_COMPLETE",
                    "Run",
                    run_obj.id,
                    {
                        "step_id": step_id,
                        "step_name": _name_map.get(step_id, step_id),
                        "results": step_data.get("results", {}),
                    },
                )
            elif old_status == "completed" and new_step_status != "completed":
                await log_audit(
                    db,
                    user.id,
                    "STEP_UNCOMPLETE",
                    "Run",
                    run_obj.id,
                    {"step_id": step_id, "step_name": _name_map.get(step_id, step_id)},
                )

            # Track step-level note changes (skip EDITED — handled above)
            if target_status != "EDITED":
                old_notes = (
                    old_step.get("notes", "") if isinstance(old_step, dict) else ""
                )
                new_notes = step_data.get("notes", "")
                if old_notes != new_notes:
                    await log_audit(
                        db,
                        user.id,
                        "STEP_EDIT",
                        "Run",
                        run_obj.id,
                        {
                            "step_id": step_id,
                            "step_name": _name_map.get(step_id, step_id),
                            "field": "notes",
                            "field_label": "Notes",
                            "old_value": old_notes,
                            "new_value": new_notes,
                        },
                    )

    changes = update_data.model_dump(exclude_unset=True)
    for key, value in changes.items():
        setattr(run_obj, key, value)

    # Also track started_by_id in changes for audit log if it was set
    if new_status == "ACTIVE" and current_status != "ACTIVE":
        changes["started_by_id"] = str(user.id)

    await log_audit(
        db,
        user.id,
        "UPDATE",
        "Run",
        run_obj.id,
        changes,
    )

    await db.commit()
    await db.refresh(run_obj)

    # --- Notification hooks for status transitions ---
    if new_status and new_status != current_status:
        # Get org_id from the project
        proj_result = await db.execute(
            select(Project).where(Project.id == run_obj.project_id)
        )
        project = proj_result.scalar_one()

        # Get all assigned user IDs for this run
        assign_result = await db.execute(
            select(RunRoleAssignment.user_id).where(RunRoleAssignment.run_id == run_id)
        )
        assigned_user_ids = [row[0] for row in assign_result.all()]

        if new_status == "ACTIVE" and assigned_user_ids:
            background_tasks.add_task(
                send_notification,
                db=db,
                event_type="RUN_STARTED",
                org_id=project.organization_id,
                entity_type="run",
                entity_id=run_obj.id,
                recipients=assigned_user_ids,
                context={
                    "run_name": run_obj.name,
                    "started_by": user.full_name or user.email,
                },
            )
        elif new_status == "COMPLETED":
            if assigned_user_ids:
                background_tasks.add_task(
                    send_notification,
                    db=db,
                    event_type="RUN_COMPLETED",
                    org_id=project.organization_id,
                    entity_type="run",
                    entity_id=run_obj.id,
                    recipients=assigned_user_ids,
                    context={
                        "run_name": run_obj.name,
                        "completed_by": user.full_name or user.email,
                    },
                )

            # Check for unanalyzed images and create notification
            analyzed_ids = (
                select(ImageConversation.image_id).distinct().scalar_subquery()
            )
            unanalyzed_result = await db.execute(
                select(func.count(RunImage.id)).where(
                    RunImage.run_id == run_obj.id,
                    RunImage.id.notin_(analyzed_ids),
                )
            )
            unanalyzed_count = unanalyzed_result.scalar() or 0
            if unanalyzed_count > 0:
                # Notify assigned users + the completing user
                recipients = list(set(assigned_user_ids) | {user.id})
                await send_notification(
                    db=db,
                    event_type="PENDING_IMAGE_ANALYSIS",
                    org_id=project.organization_id,
                    entity_type="run",
                    entity_id=run_obj.id,
                    recipients=recipients,
                    context={
                        "run_name": run_obj.name,
                        "completed_by": user.full_name or user.email,
                        "unanalyzed_count": unanalyzed_count,
                    },
                )

    return run_obj


# --- Run PDFs ---


@router.get("/runs/{run_id}/pdf/sop")
async def get_run_sop_pdf(
    run_id: UUID,
    disposition: Optional[str] = Query(None),
    template_id: Optional[UUID] = Query(None),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Generate an SOP PDF from a run's snapshot graph."""
    allowed = await check_permission(
        db,
        user.id,
        ObjectType.RUN,
        run_id,
        PermissionLevel.VIEW,
    )
    if not allowed:
        raise HTTPException(status_code=403, detail="Insufficient permissions")

    run_obj = await get_or_404(db, Run, run_id)

    # Get protocol metadata and template
    protocol_name = "Unknown Protocol"
    protocol_description = ""
    proto_version: int | None = None
    proto_modified: str | None = None
    sop_template_id: UUID | None = None
    if run_obj.protocol_id:
        result = await db.execute(
            select(Protocol).where(Protocol.id == run_obj.protocol_id)
        )
        proto = result.scalar_one_or_none()
        if proto:
            protocol_name = proto.name
            protocol_description = proto.description or ""
            proto_version = proto.version_number
            sop_template_id = proto.sop_template_id
            if proto.updated_at:
                proto_modified = proto.updated_at.strftime("%B %d, %Y")

    template = await _load_template(db, template_id or sop_template_id)
    if not template:
        raise HTTPException(status_code=404, detail="SOP template not found")

    template_path = _resolve_template_path(template)
    graph = run_obj.graph or {}
    roles_with_steps, flat_steps, is_role_based = _parse_graph_roles_and_steps(graph)

    context = build_context(
        protocol_name=protocol_name,
        protocol_description=protocol_description,
        run_name=run_obj.name,
        version_number=proto_version,
        created_at=proto_modified or "",
        roles_with_steps=roles_with_steps,
        flat_steps=flat_steps,
        is_role_based=is_role_based,
    )
    pdf_bytes = await asyncio.to_thread(render_to_pdf, template_path, context)

    disp = disposition or "attachment"
    filename = f"SOP_{run_obj.name}.pdf".replace(" ", "_")
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'{disp}; filename="{filename}"'},
    )


@router.get("/runs/{run_id}/pdf/batch-record")
async def get_run_batch_record_pdf(
    run_id: UUID,
    filled: bool = Query(False),
    embed_images: bool = Query(False),
    include_attachments: bool = Query(False),
    disposition: Optional[str] = Query(None),
    template_id: Optional[UUID] = Query(None),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Generate a batch record PDF from a run's snapshot graph."""
    allowed = await check_permission(
        db,
        user.id,
        ObjectType.RUN,
        run_id,
        PermissionLevel.VIEW,
    )
    if not allowed:
        raise HTTPException(status_code=403, detail="Insufficient permissions")

    run_obj = await get_or_404(db, Run, run_id)

    # Get protocol metadata and template
    protocol_name = "Unknown Protocol"
    protocol_version = None
    protocol_modified = None
    br_template_id: UUID | None = None
    if run_obj.protocol_id:
        result = await db.execute(
            select(Protocol).where(Protocol.id == run_obj.protocol_id)
        )
        proto = result.scalar_one_or_none()
        if proto:
            protocol_name = proto.name
            protocol_version = proto.version_number
            br_template_id = proto.batch_record_template_id
            protocol_modified = (
                proto.updated_at.strftime("%B %d, %Y") if proto.updated_at else None
            )

    template = await _load_template(db, template_id or br_template_id)
    if not template:
        raise HTTPException(status_code=404, detail="Batch record template not found")

    template_path = _resolve_template_path(template)
    graph = run_obj.graph or {}
    roles_with_steps, flat_steps, is_role_based = _parse_graph_roles_and_steps(graph)

    # Build user_map for electronic initials on filled records
    user_map: dict[str, str] = {}
    started_by_id_str: str | None = None
    if filled and run_obj.execution_data:
        user_ids = set()
        for step_data in run_obj.execution_data.values():
            if isinstance(step_data, dict):
                uid = step_data.get("completed_by_user_id")
                if uid:
                    user_ids.add(uid)
                editor_uid = step_data.get("edited_by_user_id")
                if editor_uid:
                    user_ids.add(editor_uid)
        if run_obj.started_by_id:
            started_by_id_str = str(run_obj.started_by_id)
            user_ids.add(started_by_id_str)
        if user_ids:
            result = await db.execute(select(User).where(User.id.in_(user_ids)))
            for u in result.scalars().all():
                user_map[str(u.id)] = u.full_name or u.email

    run_status = _run_status_str(run_obj)

    context = build_context(
        protocol_name=protocol_name,
        run_name=run_obj.name,
        run_status=run_status,
        version_number=protocol_version,
        created_at=protocol_modified or "",
        roles_with_steps=roles_with_steps,
        flat_steps=flat_steps,
        is_role_based=is_role_based,
        execution_data=run_obj.execution_data if filled else None,
        user_map=user_map if filled else None,
        started_by_id=started_by_id_str,
        notes=run_obj.notes if filled else None,
        attachments=run_obj.attachments if filled else None,
        storage=FileStorageService() if filled and embed_images else None,
    )
    pdf_bytes = await asyncio.to_thread(render_to_pdf, template_path, context)

    disp = disposition or "attachment"
    suffix = "COMPLETED" if filled else "BLANK"
    safe_name = run_obj.name.replace(" ", "_")

    # ZIP export: PDF + non-embedded attachment files
    if filled and include_attachments:
        import zipfile
        from io import BytesIO

        storage = FileStorageService()

        zip_buf = BytesIO()
        with zipfile.ZipFile(zip_buf, "w", zipfile.ZIP_DEFLATED) as zf:
            pdf_name = f"BatchRecord_{safe_name}_{suffix}.pdf"
            zf.writestr(pdf_name, pdf_bytes)

            for att in run_obj.attachments or []:
                if att.get("deleted"):
                    continue
                # Skip images already embedded in the PDF
                if embed_images and att.get("content_type", "") in IMAGE_MIME_TYPES:
                    continue
                fpath = storage.resolve_path(att["file_path"])
                if fpath.exists():
                    zf.write(
                        str(fpath),
                        f"attachments/{att.get('filename', 'file')}",
                    )

        zip_buf.seek(0)
        zip_name = f"BatchRecord_{safe_name}.zip"
        return Response(
            content=zip_buf.getvalue(),
            media_type="application/zip",
            headers={
                "Content-Disposition": f'attachment; filename="{zip_name}"',
            },
        )

    filename = f"BatchRecord_{safe_name}_{suffix}.pdf"
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'{disp}; filename="{filename}"'},
    )


# --- Run Role Assignments ---


@router.get(
    "/runs/{run_id}/role-assignments",
    response_model=RunRoleAssignmentListResponse,
)
async def get_run_role_assignments(
    run_id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get all role assignments for a run."""
    allowed = await check_permission(
        db,
        user.id,
        ObjectType.RUN,
        run_id,
        PermissionLevel.VIEW,
    )
    if not allowed:
        raise HTTPException(status_code=403, detail="Insufficient permissions")

    result = await db.execute(
        select(RunRoleAssignment).where(RunRoleAssignment.run_id == run_id)
    )
    assignments = result.scalars().all()
    return RunRoleAssignmentListResponse(items=assignments)


@router.post(
    "/runs/{run_id}/role-assignments",
    response_model=RunRoleAssignmentResponse,
    status_code=201,
)
async def create_run_role_assignment(
    run_id: UUID,
    assignment: RunRoleAssignmentCreate,
    background_tasks: BackgroundTasks,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_active_subscription()),
):
    """Assign a user to a role in a run."""
    allowed = await check_permission(
        db,
        user.id,
        ObjectType.RUN,
        run_id,
        PermissionLevel.EDIT,
    )
    if not allowed:
        raise HTTPException(status_code=403, detail="Insufficient permissions")

    run_obj = await get_or_404(db, Run, run_id)

    # Verify user exists
    await get_or_404(db, User, assignment.user_id)

    # Check if assignment already exists for this lane
    result = await db.execute(
        select(RunRoleAssignment).where(
            and_(
                RunRoleAssignment.run_id == run_id,
                RunRoleAssignment.lane_node_id == assignment.lane_node_id,
            )
        )
    )
    existing = result.scalar_one_or_none()
    if existing:
        # Update existing assignment
        old_user_id = existing.user_id
        existing.user_id = assignment.user_id
        existing.role_name = assignment.role_name
        await db.commit()
        await db.refresh(existing)
        await log_audit(
            db,
            user.id,
            "UPDATE",
            "RunRoleAssignment",
            existing.id,
            {
                "old_user_id": str(old_user_id),
                "new_user_id": str(assignment.user_id),
                "lane_node_id": assignment.lane_node_id,
                "role_name": assignment.role_name,
            },
        )

        # Notify reassignment
        if old_user_id != assignment.user_id:
            proj = await db.execute(
                select(Project).where(Project.id == run_obj.project_id)
            )
            project = proj.scalar_one()
            old_user_result = await db.execute(
                select(User).where(User.id == old_user_id)
            )
            old_user_obj = old_user_result.scalar_one()
            new_user_result = await db.execute(
                select(User).where(User.id == assignment.user_id)
            )
            new_user_obj = new_user_result.scalar_one()

            background_tasks.add_task(
                send_notification,
                db=db,
                event_type="ROLE_REASSIGNED",
                org_id=project.organization_id,
                entity_type="run",
                entity_id=run_obj.id,
                recipients=[old_user_id, assignment.user_id],
                context={
                    "run_name": run_obj.name,
                    "role_name": assignment.role_name,
                    "old_user_name": old_user_obj.full_name or old_user_obj.email,
                    "new_user_name": new_user_obj.full_name or new_user_obj.email,
                    "reassigned_by": user.full_name or user.email,
                },
            )

        return existing

    # Create new assignment
    new_assignment = RunRoleAssignment(
        run_id=run_id,
        lane_node_id=assignment.lane_node_id,
        role_name=assignment.role_name,
        user_id=assignment.user_id,
    )
    db.add(new_assignment)
    await db.commit()
    await db.refresh(new_assignment)
    await log_audit(
        db,
        user.id,
        "CREATE",
        "RunRoleAssignment",
        new_assignment.id,
        {
            "run_id": str(run_id),
            "user_id": str(assignment.user_id),
            "lane_node_id": assignment.lane_node_id,
            "role_name": assignment.role_name,
        },
    )

    # Notify new role assignment
    proj = await db.execute(select(Project).where(Project.id == run_obj.project_id))
    project = proj.scalar_one()
    background_tasks.add_task(
        send_notification,
        db=db,
        event_type="ROLE_ASSIGNED",
        org_id=project.organization_id,
        entity_type="run",
        entity_id=run_obj.id,
        recipients=[assignment.user_id],
        context={
            "run_name": run_obj.name,
            "role_name": assignment.role_name,
            "assigned_by": user.full_name or user.email,
        },
    )

    return new_assignment


@router.delete("/runs/{run_id}/role-assignments/{assignment_id}")
async def delete_run_role_assignment(
    run_id: UUID,
    assignment_id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_active_subscription()),
):
    """Remove a user's role assignment."""
    allowed = await check_permission(
        db,
        user.id,
        ObjectType.RUN,
        run_id,
        PermissionLevel.EDIT,
    )
    if not allowed:
        raise HTTPException(status_code=403, detail="Insufficient permissions")

    result = await db.execute(
        select(RunRoleAssignment).where(
            and_(
                RunRoleAssignment.id == assignment_id,
                RunRoleAssignment.run_id == run_id,
            )
        )
    )
    assignment = result.scalar_one_or_none()
    if not assignment:
        raise HTTPException(status_code=404, detail="Assignment not found")

    assignment_data = {
        "run_id": str(assignment.run_id),
        "user_id": str(assignment.user_id),
        "lane_node_id": assignment.lane_node_id,
        "role_name": assignment.role_name,
    }

    await db.delete(assignment)
    await db.commit()
    await log_audit(
        db,
        user.id,
        "DELETE",
        "RunRoleAssignment",
        assignment_id,
        assignment_data,
    )
    return {"ok": True}


# --- Helpers for notes & attachments ---

ALLOWED_ATTACHMENT_TYPES = {
    "image/jpeg",
    "image/png",
    "image/tiff",
    "image/webp",
    "application/pdf",
    "text/csv",
    "text/plain",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
}
MAX_ATTACHMENT_SIZE = 25 * 1024 * 1024  # 25 MB


# --- Run Notes ---


@router.post(
    "/runs/{run_id}/notes",
    response_model=RunNote,
    status_code=201,
)
async def add_run_note(
    run_id: UUID,
    body: RunNoteCreate,
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_active_subscription()),
):
    """Add an append-only note to a run."""
    allowed = await check_permission(
        db,
        user.id,
        ObjectType.RUN,
        run_id,
        PermissionLevel.EDIT,
    )
    if not allowed:
        raise HTTPException(status_code=403, detail="Insufficient permissions")

    run_obj = await get_or_404(db, Run, run_id)

    run_status = _run_status_str(run_obj)

    note = RunNote(
        id=uuid_mod.uuid4(),
        content=body.content,
        author_id=user.id,
        author_name=user.full_name or user.email,
        created_at=datetime.now(timezone.utc),
        run_status=run_status,
        flags=body.flags,
    )

    run_obj.notes = [*(run_obj.notes or []), note.model_dump(mode="json")]
    flag_modified(run_obj, "notes")

    await log_audit(
        db,
        user.id,
        "NOTE_ADDED",
        "Run",
        run_obj.id,
        {
            "note_id": str(note.id),
            "content": note.content,
            "run_status": run_status,
            "flags": body.flags,
        },
    )

    await db.commit()
    await db.refresh(run_obj)
    return note


@router.get(
    "/runs/{run_id}/notes",
    response_model=RunNoteListResponse,
)
async def list_run_notes(
    run_id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List all run-level notes."""
    allowed = await check_permission(
        db,
        user.id,
        ObjectType.RUN,
        run_id,
        PermissionLevel.VIEW,
    )
    if not allowed:
        raise HTTPException(status_code=403, detail="Insufficient permissions")

    run_obj = await get_or_404(db, Run, run_id)
    return RunNoteListResponse(items=[RunNote(**n) for n in (run_obj.notes or [])])


# --- Run Attachments ---


@router.post(
    "/runs/{run_id}/attachments",
    response_model=RunAttachment,
    status_code=201,
)
async def upload_attachment(
    run_id: UUID,
    file: UploadFile,
    request: Request,
    step_id: Optional[str] = Form(None),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_active_subscription()),
):
    """Upload a file attachment to a run."""
    allowed = await check_permission(
        db,
        user.id,
        ObjectType.RUN,
        run_id,
        PermissionLevel.EDIT,
    )
    if not allowed:
        raise HTTPException(status_code=403, detail="Insufficient permissions")

    run_obj = await get_or_404(db, Run, run_id)

    org_id = get_org_id_from_request(request)
    storage = FileStorageService()
    stored = await storage.store_file(
        file,
        base_dir="attachments",
        org_id=org_id or run_id,
        path_segments=[str(run_id)],
        allowed_types=ALLOWED_ATTACHMENT_TYPES,
        max_size_bytes=MAX_ATTACHMENT_SIZE,
    )

    run_status = _run_status_str(run_obj)

    attachment = RunAttachment(
        id=uuid_mod.uuid4(),
        file_path=stored.relative_path,
        filename=stored.original_filename,
        content_type=stored.mime_type,
        size_bytes=stored.size_bytes,
        uploaded_by_id=user.id,
        uploaded_at=datetime.now(timezone.utc),
        step_id=step_id,
        run_status=run_status,
        deleted=False,
    )

    run_obj.attachments = [
        *(run_obj.attachments or []),
        attachment.model_dump(mode="json"),
    ]
    flag_modified(run_obj, "attachments")

    await log_audit(
        db,
        user.id,
        "ATTACHMENT_UPLOADED",
        "Run",
        run_obj.id,
        {
            "attachment_id": str(attachment.id),
            "filename": attachment.filename,
            "content_type": attachment.content_type,
            "size_bytes": attachment.size_bytes,
            "step_id": step_id,
            "run_status": run_status,
        },
    )

    await db.commit()
    await db.refresh(run_obj)
    return attachment


@router.get(
    "/runs/{run_id}/attachments",
    response_model=RunAttachmentListResponse,
)
async def list_attachments(
    run_id: UUID,
    step_id: Optional[str] = Query(None),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List attachments for a run, optionally filtered by step."""
    allowed = await check_permission(
        db,
        user.id,
        ObjectType.RUN,
        run_id,
        PermissionLevel.VIEW,
    )
    if not allowed:
        raise HTTPException(status_code=403, detail="Insufficient permissions")

    run_obj = await get_or_404(db, Run, run_id)
    items = [a for a in (run_obj.attachments or []) if not a.get("deleted")]
    if step_id is not None:
        items = [a for a in items if a.get("step_id") == step_id]
    return RunAttachmentListResponse(items=[RunAttachment(**a) for a in items])


@router.delete(
    "/runs/{run_id}/attachments/{attachment_id}",
    status_code=204,
)
async def soft_delete_attachment(
    run_id: UUID,
    attachment_id: str,
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_active_subscription()),
):
    """Soft-delete an attachment (EDIT permission)."""
    allowed = await check_permission(
        db,
        user.id,
        ObjectType.RUN,
        run_id,
        PermissionLevel.EDIT,
    )
    if not allowed:
        raise HTTPException(status_code=403, detail="Insufficient permissions")

    run_obj = await get_or_404(db, Run, run_id)

    run_status = _run_status_str(run_obj)

    updated = []
    found = None
    for att in run_obj.attachments or []:
        if att["id"] == attachment_id:
            if att.get("deleted"):
                raise HTTPException(404, "Attachment already deleted")
            found = att
            updated.append({**att, "deleted": True})
        else:
            updated.append(att)

    if not found:
        raise HTTPException(404, "Attachment not found")

    run_obj.attachments = updated
    flag_modified(run_obj, "attachments")

    await log_audit(
        db,
        user.id,
        "ATTACHMENT_DELETED",
        "Run",
        run_obj.id,
        {
            "attachment_id": attachment_id,
            "filename": found["filename"],
            "run_status": run_status,
        },
    )

    await db.commit()


@router.post(
    "/runs/{run_id}/attachments/{attachment_id}/restore",
    response_model=RunAttachment,
)
async def restore_attachment(
    run_id: UUID,
    attachment_id: str,
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_active_subscription()),
):
    """Restore a soft-deleted attachment (ADMIN permission)."""
    allowed = await check_permission(
        db,
        user.id,
        ObjectType.RUN,
        run_id,
        PermissionLevel.ADMIN,
    )
    if not allowed:
        raise HTTPException(status_code=403, detail="ADMIN permission required")

    run_obj = await get_or_404(db, Run, run_id)

    run_status = _run_status_str(run_obj)

    updated = []
    found = None
    for att in run_obj.attachments or []:
        if att["id"] == attachment_id:
            if not att.get("deleted"):
                raise HTTPException(409, "Attachment is not deleted")
            found = att
            updated.append({**att, "deleted": False})
        else:
            updated.append(att)

    if not found:
        raise HTTPException(404, "Attachment not found")

    run_obj.attachments = updated
    flag_modified(run_obj, "attachments")

    await log_audit(
        db,
        user.id,
        "ATTACHMENT_RESTORED",
        "Run",
        run_obj.id,
        {
            "attachment_id": attachment_id,
            "filename": found["filename"],
            "run_status": run_status,
        },
    )

    await db.commit()
    await db.refresh(run_obj)
    restored = next(a for a in run_obj.attachments if a["id"] == attachment_id)
    return RunAttachment(**restored)


@router.get("/runs/{run_id}/attachments/{attachment_id}/download")
async def download_attachment(
    run_id: UUID,
    attachment_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Download an attachment file (authenticated)."""
    allowed = await check_permission(
        db,
        user.id,
        ObjectType.RUN,
        run_id,
        PermissionLevel.VIEW,
    )
    if not allowed:
        raise HTTPException(status_code=403, detail="Insufficient permissions")

    run_obj = await get_or_404(db, Run, run_id)

    att = next(
        (
            a
            for a in (run_obj.attachments or [])
            if a["id"] == attachment_id and not a.get("deleted")
        ),
        None,
    )
    if not att:
        raise HTTPException(404, "Attachment not found")

    storage = FileStorageService()
    full_path = storage.resolve_path(att["file_path"])
    if not full_path.exists():
        raise HTTPException(404, "Attachment file not found on disk")

    return FileResponse(
        path=str(full_path),
        filename=att["filename"],
        media_type=att["content_type"],
    )


# --- Run Audit Log ---


@router.get("/runs/{run_id}/audit-log")
async def get_run_audit_log(
    run_id: UUID,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get the audit trail for a run with pagination (History tab)."""
    allowed = await check_permission(
        db,
        user.id,
        ObjectType.RUN,
        run_id,
        PermissionLevel.VIEW,
    )
    if not allowed:
        raise HTTPException(status_code=403, detail="Insufficient permissions")

    await get_or_404(db, Run, run_id)

    base_query = select(AuditLog).where(
        AuditLog.entity_type == "Run",
        AuditLog.entity_id == run_id,
    )

    # Total count
    count_result = await db.execute(
        select(func.count()).select_from(base_query.subquery())
    )
    total = count_result.scalar() or 0

    # Paginated results
    result = await db.execute(
        base_query.order_by(AuditLog.created_at.desc()).offset(offset).limit(limit)
    )
    entries = result.scalars().all()

    # Resolve actor names in bulk
    actor_ids = {e.actor_id for e in entries}
    user_map: dict[UUID, str] = {}
    if actor_ids:
        user_result = await db.execute(select(User).where(User.id.in_(actor_ids)))
        for u in user_result.scalars().all():
            user_map[u.id] = u.full_name or u.email

    return {
        "items": [
            {
                "id": str(e.id),
                "action": e.action,
                "actor_id": str(e.actor_id),
                "actor_name": user_map.get(e.actor_id, "Unknown"),
                "changes": e.changes,
                "created_at": e.created_at.isoformat(),
            }
            for e in entries
        ],
        "total": total,
        "offset": offset,
        "limit": limit,
    }
