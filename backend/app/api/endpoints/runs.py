import logging
from datetime import datetime, timezone
from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from fastapi.responses import Response
from sqlalchemy import func, select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user, require_permission
from app.db.session import get_db
from app.models.iam import User, ObjectType, PermissionLevel
from app.models.science import (
    Protocol,
    Run,
    Project,
    RunRoleAssignment,
)
from app.models.ai import RunImage, ImageConversation
from app.schemas.science import (
    RunCreate,
    RunUpdate,
    RunResponse,
    RunRoleAssignmentCreate,
    RunRoleAssignmentResponse,
    RunRoleAssignmentListResponse,
)
from app.services.audit import log_audit
from app.services.graph_processing import _parse_graph_roles_and_steps
from app.services.notifications import send_notification
from app.services.pdf import generate_sop_pdf, generate_batch_record_pdf
from app.services.permissions import check_permission
from app.api.endpoints.protocol_pdfs import (
    _get_pdf_format,
    _build_format_overrides,
    _merge_format,
)

logger = logging.getLogger(__name__)

router = APIRouter()


# --- Runs ---

@router.post(
    "/runs", response_model=RunResponse, status_code=201,
)
async def create_run(
    run_in: RunCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    allowed = await check_permission(
        db, user.id, ObjectType.PROJECT,
        run_in.project_id, PermissionLevel.EDIT,
    )
    if not allowed:
        raise HTTPException(
            status_code=403,
            detail="EDIT permission required on project",
        )

    result = await db.execute(
        select(Project).where(Project.id == run_in.project_id)
    )
    if result.scalar_one_or_none() is None:
        raise HTTPException(status_code=404, detail="Project not found")

    initial_graph = {}
    if run_in.protocol_id:
        result = await db.execute(
            select(Protocol).where(Protocol.id == run_in.protocol_id)
        )
        protocol = result.scalar_one_or_none()
        if protocol is None:
            raise HTTPException(
                status_code=404, detail="Protocol not found"
            )
        if protocol.status == "ARCHIVED":
            raise HTTPException(
                status_code=400,
                detail="Cannot create run from archived protocol",
            )
        initial_graph = protocol.graph.copy() if protocol.graph else {}

    run_obj = Run(
        name=run_in.name,
        project_id=run_in.project_id,
        protocol_id=run_in.protocol_id,
        graph=initial_graph,
        execution_data={},
    )
    db.add(run_obj)
    await db.flush()

    await log_audit(
        db, user.id, "CREATE", "Run",
        run_obj.id, {"name": run_in.name},
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
        db, user.id, ObjectType.RUN,
        run_id, PermissionLevel.VIEW,
    )
    if not allowed:
        raise HTTPException(status_code=403, detail="Insufficient permissions")

    result = await db.execute(
        select(Run).where(Run.id == run_id)
    )
    run_obj = result.scalar_one_or_none()
    if not run_obj:
        raise HTTPException(status_code=404, detail="Run not found")
    return run_obj


@router.get(
    "/projects/{project_id}/runs",
    response_model=List[RunResponse],
    dependencies=[
        Depends(
            require_permission(
                ObjectType.PROJECT, "project_id", PermissionLevel.VIEW
            )
        )
    ],
)
async def list_project_runs(
    project_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Run).where(Run.project_id == project_id)
    )
    return result.scalars().all()


@router.put(
    "/runs/{run_id}", response_model=RunResponse,
)
async def update_run(
    run_id: UUID,
    update_data: RunUpdate,
    background_tasks: BackgroundTasks,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    allowed = await check_permission(
        db, user.id, ObjectType.RUN,
        run_id, PermissionLevel.EDIT,
    )
    if not allowed:
        raise HTTPException(status_code=403, detail="Insufficient permissions")

    result = await db.execute(
        select(Run).where(Run.id == run_id)
    )
    run_obj = result.scalar_one_or_none()
    if not run_obj:
        raise HTTPException(status_code=404, detail="Run not found")

    # Validate status transitions
    new_status = update_data.status.value if update_data.status else None
    current_status = run_obj.status if isinstance(run_obj.status, str) else run_obj.status.value

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
                select(RunRoleAssignment)
                .where(RunRoleAssignment.run_id == run_id)
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
                sid for sid in unit_op_ids
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
                param_schema_props = (
                    (node_data.get("paramSchema") or {})
                    .get("properties", {})
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
                    new_step["edited_at"] = (
                        datetime.now(timezone.utc).isoformat()
                    )

                # Audit each individual field change
                if old_results and new_results:
                    for field_key in set(old_results) | set(new_results):
                        old_val = old_results.get(field_key)
                        new_val = new_results.get(field_key)
                        if old_val != new_val:
                            prop = param_schema_props.get(field_key, {})
                            field_label = (
                                prop.get("title")
                                or field_key.replace("_", " ").title()
                            )
                            await log_audit(
                                db, user.id, "STEP_EDIT", "Run",
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
                    new_step["edited_at"] = (
                        datetime.now(timezone.utc).isoformat()
                    )
                    await log_audit(
                        db, user.id, "STEP_EDIT", "Run",
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

    # Audit log step completions by diffing execution_data
    if update_data.execution_data is not None:
        old_exec = run_obj.execution_data or {}
        new_exec = update_data.execution_data
        for step_id, step_data in new_exec.items():
            old_step = old_exec.get(step_id, {})
            old_status = old_step.get("status")
            new_step_status = step_data.get("status") if isinstance(step_data, dict) else None
            if new_step_status == "completed" and old_status != "completed":
                await log_audit(
                    db, user.id, "STEP_COMPLETE", "Run", run_obj.id,
                    {"step_id": step_id, "results": step_data.get("results", {})}
                )
            elif old_status == "completed" and new_step_status != "completed":
                await log_audit(
                    db, user.id, "STEP_UNCOMPLETE", "Run", run_obj.id,
                    {"step_id": step_id}
                )

    changes = update_data.model_dump(exclude_unset=True)
    for key, value in changes.items():
        setattr(run_obj, key, value)

    # Also track started_by_id in changes for audit log if it was set
    if new_status == "ACTIVE" and current_status != "ACTIVE":
        changes["started_by_id"] = str(user.id)

    await log_audit(
        db, user.id, "UPDATE", "Run", run_obj.id, changes,
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
            select(RunRoleAssignment.user_id)
            .where(RunRoleAssignment.run_id == run_id)
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
                select(ImageConversation.image_id)
                .distinct()
                .scalar_subquery()
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
                recipients = list(
                    set(assigned_user_ids) | {user.id}
                )
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
    font_size: Optional[str] = Query(None),
    font_family: Optional[str] = Query(None),
    header_color: Optional[str] = Query(None),
    row_spacing: Optional[str] = Query(None),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Generate an SOP PDF from a run's snapshot graph."""
    allowed = await check_permission(
        db, user.id, ObjectType.RUN,
        run_id, PermissionLevel.VIEW,
    )
    if not allowed:
        raise HTTPException(status_code=403, detail="Insufficient permissions")

    result = await db.execute(
        select(Run).where(Run.id == run_id)
    )
    run_obj = result.scalar_one_or_none()
    if not run_obj:
        raise HTTPException(status_code=404, detail="Run not found")

    # Get protocol name, description, and project settings
    protocol_name = "Unknown Protocol"
    protocol_description = ""
    pdf_format = None
    proto_version: int | None = None
    proto_modified: str | None = None
    if run_obj.protocol_id:
        result = await db.execute(
            select(Protocol).where(Protocol.id == run_obj.protocol_id)
        )
        proto = result.scalar_one_or_none()
        if proto:
            protocol_name = proto.name
            protocol_description = proto.description or ""
            pdf_format = await _get_pdf_format(db, proto.project_id)
            proto_version = proto.version_number
            if proto.updated_at:
                proto_modified = proto.updated_at.strftime("%B %d, %Y")

    overrides = _build_format_overrides(
        font_size, font_family, header_color, row_spacing,
    )
    pdf_format = _merge_format(pdf_format, overrides)

    graph = run_obj.graph or {}
    roles_with_steps, _, _ = _parse_graph_roles_and_steps(graph)

    pdf_bytes = generate_sop_pdf(
        protocol_name=protocol_name,
        protocol_description=protocol_description,
        run_name=run_obj.name,
        roles_with_steps=roles_with_steps,
        format_options=pdf_format,
        version_number=proto_version,
        last_modified=proto_modified,
    )

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
    disposition: Optional[str] = Query(None),
    font_size: Optional[str] = Query(None),
    font_family: Optional[str] = Query(None),
    header_color: Optional[str] = Query(None),
    row_spacing: Optional[str] = Query(None),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Generate a batch record PDF from a run's snapshot graph."""
    allowed = await check_permission(
        db, user.id, ObjectType.RUN,
        run_id, PermissionLevel.VIEW,
    )
    if not allowed:
        raise HTTPException(status_code=403, detail="Insufficient permissions")

    result = await db.execute(
        select(Run).where(Run.id == run_id)
    )
    run_obj = result.scalar_one_or_none()
    if not run_obj:
        raise HTTPException(status_code=404, detail="Run not found")

    # Get protocol name and project settings
    protocol_name = "Unknown Protocol"
    pdf_format = None
    protocol_version = None
    protocol_modified = None
    if run_obj.protocol_id:
        result = await db.execute(
            select(Protocol).where(Protocol.id == run_obj.protocol_id)
        )
        proto = result.scalar_one_or_none()
        if proto:
            protocol_name = proto.name
            protocol_version = proto.version_number
            protocol_modified = (
                proto.updated_at.strftime("%B %d, %Y") if proto.updated_at else None
            )
            pdf_format = await _get_pdf_format(db, proto.project_id)

    overrides = _build_format_overrides(
        font_size, font_family, header_color, row_spacing,
    )
    pdf_format = _merge_format(pdf_format, overrides)

    graph = run_obj.graph or {}
    roles_with_steps, flat_steps, is_role_based = _parse_graph_roles_and_steps(graph)

    # Build roles list for sign-off (only for swimlane-based protocols)
    if is_role_based:
        roles = [
            {"id": r["role_name"], "name": r["role_name"]}
            for r in roles_with_steps
            if r["role_name"]
        ]
    else:
        roles = []

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
                # Also collect editor user IDs for GMP edited records
                editor_uid = step_data.get("edited_by_user_id")
                if editor_uid:
                    user_ids.add(editor_uid)
        # Fallback: include started_by_id for legacy runs without
        # per-step completed_by_user_id
        if run_obj.started_by_id:
            started_by_id_str = str(run_obj.started_by_id)
            user_ids.add(started_by_id_str)
        if user_ids:
            result = await db.execute(
                select(User).where(User.id.in_(user_ids))
            )
            for u in result.scalars().all():
                user_map[str(u.id)] = u.full_name or u.email

    run_status = (
        run_obj.status if isinstance(run_obj.status, str)
        else run_obj.status.value
    )
    pdf_bytes = generate_batch_record_pdf(
        protocol_name=protocol_name,
        run_name=run_obj.name,
        roles=roles,
        steps=flat_steps,
        filled=filled,
        execution_data=run_obj.execution_data if filled else None,
        format_options=pdf_format,
        roles_with_steps=roles_with_steps,
        is_role_based=is_role_based,
        version_number=protocol_version,
        last_modified=protocol_modified,
        user_map=user_map if filled else None,
        started_by_id=started_by_id_str,
        run_status=run_status,
    )

    disp = disposition or "attachment"
    suffix = "COMPLETED" if filled else "BLANK"
    filename = f"BatchRecord_{run_obj.name}_{suffix}.pdf".replace(" ", "_")
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
        db, user.id, ObjectType.RUN,
        run_id, PermissionLevel.VIEW,
    )
    if not allowed:
        raise HTTPException(status_code=403, detail="Insufficient permissions")

    result = await db.execute(
        select(RunRoleAssignment)
        .where(RunRoleAssignment.run_id == run_id)
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
):
    """Assign a user to a role in a run."""
    allowed = await check_permission(
        db, user.id, ObjectType.RUN,
        run_id, PermissionLevel.EDIT,
    )
    if not allowed:
        raise HTTPException(status_code=403, detail="Insufficient permissions")

    result = await db.execute(
        select(Run).where(Run.id == run_id)
    )
    run_obj = result.scalar_one_or_none()
    if not run_obj:
        raise HTTPException(status_code=404, detail="Run not found")

    # Verify user exists
    result = await db.execute(
        select(User).where(User.id == assignment.user_id)
    )
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="User not found")

    # Check if assignment already exists for this lane
    result = await db.execute(
        select(RunRoleAssignment)
        .where(and_(
            RunRoleAssignment.run_id == run_id,
            RunRoleAssignment.lane_node_id == assignment.lane_node_id,
        ))
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
            db, user.id, "UPDATE", "RunRoleAssignment", existing.id,
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
        db, user.id, "CREATE", "RunRoleAssignment", new_assignment.id,
        {
            "run_id": str(run_id),
            "user_id": str(assignment.user_id),
            "lane_node_id": assignment.lane_node_id,
            "role_name": assignment.role_name,
        },
    )

    # Notify new role assignment
    proj = await db.execute(
        select(Project).where(Project.id == run_obj.project_id)
    )
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
):
    """Remove a user's role assignment."""
    allowed = await check_permission(
        db, user.id, ObjectType.RUN,
        run_id, PermissionLevel.EDIT,
    )
    if not allowed:
        raise HTTPException(status_code=403, detail="Insufficient permissions")

    result = await db.execute(
        select(RunRoleAssignment)
        .where(and_(
            RunRoleAssignment.id == assignment_id,
            RunRoleAssignment.run_id == run_id,
        ))
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
        db, user.id, "DELETE", "RunRoleAssignment", assignment_id,
        assignment_data,
    )
    return {"ok": True}
