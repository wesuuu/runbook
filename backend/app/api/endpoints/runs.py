import asyncio
import copy
import logging
import uuid as uuid_mod
from datetime import datetime, timezone
from typing import List, Optional
from uuid import UUID

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    Form,
    HTTPException,
    Query,
    Request,
    UploadFile,
)
from fastapi.responses import FileResponse, Response
from sqlalchemy import and_, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from app.api.endpoints.protocol_pdfs import (
    _build_approval_context,
    _load_protocol_project,
    _load_template,
    _pdf_response,
    _resolve_template_path,
)
from app.core.deps import (
    get_current_user,
    get_or_404,
    get_org_id_from_request,
    require_active_subscription,
    require_permission,
)
from app.db.session import get_db
from app.models.ai import ImageConversation, RunImage
from app.models.execution import AuditLog
from app.models.iam import ObjectType, PermissionLevel, User
from app.models.projects import Project
from app.models.protocols import Protocol, ProtocolVersion, UnitOpDefinition
from app.models.runs import Run, RunRoleAssignment
from app.models.signoffs import GlpSignoff
from app.schemas.runs import (
    CheckLotNumberResponse,
    RunAttachment,
    RunAttachmentListResponse,
    RunCompleteRequest,
    RunCreate,
    RunNote,
    RunNoteCreate,
    RunNoteListResponse,
    RunOverrides,
    RunReopenRequest,
    RunResponse,
    RunRoleAssignmentCreate,
    RunRoleAssignmentListResponse,
    RunRoleAssignmentResponse,
    RunStateUpdate,
    RunStepStateUpdate,
    RunUpdate,
    SuggestLotNumberRequest,
    SuggestLotNumberResponse,
)
from app.schemas.signoffs import GlpSignoffCreate, GlpSignoffResponse
from app.services.core.audit import log_audit
from app.services.core.file_storage import IMAGE_MIME_TYPES, FileStorageService
from app.services.core.notifications import send_notification
from app.services.core.permissions import check_permission
from app.services.data.graph_processing import _parse_graph_roles_and_steps
from app.services.protocols.equipment_context import build_equipment_context
from app.services.protocols.template_engine import (
    assemble_signoff_context_args,
    build_context,
    render_to_pdf,
)
from app.services.protocols.validation import assert_no_branch_errors
from app.services.runs.graph import derive_field_label, iter_unit_op_nodes
from app.services.runs.overrides import (
    apply_node_overrides,
    diff_unit_op_node,
    snapshot_unit_op_node,
)
from app.services.runs.validation import (
    assert_can_edit_completed_run,
    assert_no_unjustified_edit_errors,
    assert_run_can_close,
    lane_assignment_gap,
)
from app.services.signoffs.queries import (
    invalidate_active_signoffs,
    list_active_signoffs,
)
from app.services.signoffs.service import create_signoff
from app.services.slugs import assign_slug_or_422

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

    # F-0086: a run designated as producing a lot must carry a lot number.
    if run_in.produces_lot and not (run_in.lot_number and run_in.lot_number.strip()):
        raise HTTPException(
            status_code=422,
            detail="lot_number is required when produces_lot is true",
        )

    result = await db.execute(select(Project).where(Project.id == run_in.project_id))
    project = result.scalar_one_or_none()
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")

    initial_graph: dict = {}
    is_strict = False
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

        # F-0066: gate run creation on approval status when both the project
        # opts in and the protocol is designated for the approval workflow.
        require_approval = bool(
            (project.settings or {}).get("require_protocol_approval", False)
        )
        if (
            require_approval
            and protocol.requires_approval
            and protocol.status != "APPROVED"
        ):
            raise HTTPException(
                status_code=400,
                detail={
                    "code": "PROTOCOL_NOT_APPROVED",
                    "message": (
                        "This protocol requires approval before runs can be " "created."
                    ),
                },
            )

        # F-0066: snapshot strictness from the protocol itself — once a
        # protocol opts into the workflow, every run is strict regardless of
        # the project setting at run-creation time.
        is_strict = bool(protocol.requires_approval)

        # F-0066: block ad-hoc overrides on strict runs. Doing this before
        # the Run row is added keeps the rejection cheap and side-effect-free.
        if is_strict and run_in.overrides is not None:
            raise HTTPException(
                status_code=403,
                detail={
                    "code": "RUN_IS_STRICT",
                    "message": (
                        "Overrides are disabled for runs of approved " "protocols."
                    ),
                },
            )

        # Resolve which graph to snapshot: a specific version, else current.
        if run_in.protocol_version_number is not None:
            v_result = await db.execute(
                select(ProtocolVersion).where(
                    (ProtocolVersion.protocol_id == protocol.id)
                    & (ProtocolVersion.version_number == run_in.protocol_version_number)
                    & (ProtocolVersion.is_draft == False)  # noqa: E712
                )
            )
            version = v_result.scalar_one_or_none()
            if version is None:
                raise HTTPException(
                    status_code=404,
                    detail=(
                        f"Protocol version {run_in.protocol_version_number} "
                        f"not found for this protocol"
                    ),
                )
            initial_graph = copy.deepcopy(version.graph or {})
        else:
            initial_graph = copy.deepcopy(protocol.graph or {})

        unit_ops_result = await db.execute(
            select(UnitOpDefinition).where(
                UnitOpDefinition.organization_id == user.selected_org_id
            )
        )
        unit_ops = list(unit_ops_result.scalars().all())
        assert_no_branch_errors(initial_graph, unit_ops)

        # Snapshot protocol_* mirror fields on every unit-op node.
        for node in iter_unit_op_nodes(initial_graph):
            snapshot_unit_op_node(node)

    run_obj = Run(
        name=run_in.name,
        project_id=run_in.project_id,
        protocol_id=run_in.protocol_id,
        experiment_id=run_in.experiment_id,
        graph=initial_graph,
        execution_data={},
        created_by_id=user.id,
        is_strict=is_strict,
        # F-0086
        produces_lot=run_in.produces_lot,
        # QA-0008: GxP execution metadata
        lot_number=run_in.lot_number,
        batch_number=run_in.batch_number,
    )
    run_obj.slug = await assign_slug_or_422(
        db, Run, Run.project_id, run_obj.project_id, run_obj.name, "run"
    )
    db.add(run_obj)
    await db.flush()

    # Apply overrides if provided.
    override_diffs = []
    if run_in.overrides is not None:
        node_index = {n["id"]: n for n in iter_unit_op_nodes(run_obj.graph)}
        for node_id, ov in run_in.overrides.nodes.items():
            node = node_index.get(node_id)
            if node is None:
                # Unknown node id: ignore (sparse override addressing a missing
                # node is a frontend bug, but we don't want to 500 on it).
                continue
            override_diffs.extend(apply_node_overrides(node, ov))
        # Notify SQLAlchemy that we mutated the JSONB column in place.
        flag_modified(run_obj, "graph")

    await log_audit(
        db,
        user.id,
        "CREATE",
        "Run",
        run_obj.id,
        {"name": run_in.name},
    )
    for d in override_diffs:
        await log_audit(
            db,
            user.id,
            "OVERRIDE_SET",
            "Run",
            run_obj.id,
            d,
        )

    await db.commit()
    await db.refresh(run_obj)
    return run_obj


@router.post(
    "/runs/suggest-lot-number",
    response_model=SuggestLotNumberResponse,
)
async def suggest_lot_number(
    body: SuggestLotNumberRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Suggest the next monotonic lot number for the project's organization.

    Pattern: LOT-{seq:06}. Sequence is org-scoped and computed over runs whose
    lot_number matches the canonical pattern. Manually entered values that do
    not match are ignored (they don't anchor or break the sequence).
    """
    allowed = await check_permission(
        db, user.id, ObjectType.PROJECT, body.project_id, PermissionLevel.VIEW
    )
    if not allowed:
        raise HTTPException(status_code=403, detail="Insufficient permissions")

    project = await get_or_404(db, Project, body.project_id)

    # Pull all canonical-pattern lot_numbers for runs in this org. Cheap given
    # the index on lot_number; the JOIN scopes to the org without denormalizing.
    stmt = (
        select(Run.lot_number)
        .join(Project, Run.project_id == Project.id)
        .where(
            Project.organization_id == project.organization_id,
            Run.lot_number.regexp_match(r"^LOT-[0-9]{6}$"),
        )
    )
    rows = (await db.execute(stmt)).scalars().all()

    max_seq = 0
    for value in rows:
        try:
            n = int(value.split("-", 1)[1])
            if n > max_seq:
                max_seq = n
        except (ValueError, IndexError):
            continue
    next_seq = max_seq + 1
    return SuggestLotNumberResponse(lot_number=f"LOT-{next_seq:06d}")


@router.get(
    "/runs/check-lot-number",
    response_model=CheckLotNumberResponse,
)
async def check_lot_number(
    project_id: UUID = Query(...),
    lot_number: str = Query(..., min_length=1),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Org-scoped duplicate-existence check for soft warnings in the UI."""
    allowed = await check_permission(
        db, user.id, ObjectType.PROJECT, project_id, PermissionLevel.VIEW
    )
    if not allowed:
        raise HTTPException(status_code=403, detail="Insufficient permissions")

    project = await get_or_404(db, Project, project_id)

    stmt = (
        select(func.count(Run.id))
        .join(Project, Run.project_id == Project.id)
        .where(
            Project.organization_id == project.organization_id,
            Run.lot_number == lot_number,
        )
    )
    count = int((await db.execute(stmt)).scalar() or 0)
    return CheckLotNumberResponse(exists=count > 0, count=count)


@router.get("/runs/by-slug/{project_slug}/{slug}", response_model=RunResponse)
async def get_run_by_slug(
    project_slug: str,
    slug: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Look up a run by project slug + run slug within the current org."""
    result = await db.execute(
        select(Run)
        .join(Project, Run.project_id == Project.id)
        .where(
            Project.organization_id == user.selected_org_id,
            Project.slug == project_slug,
            Run.slug == slug,
        )
    )
    run = result.scalar_one_or_none()
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")
    allowed = await check_permission(
        db, user.id, ObjectType.RUN, run.id, PermissionLevel.VIEW
    )
    if not allowed:
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    return run


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


@router.get("/runs/{run_id}/permissions")
async def get_run_permissions(
    run_id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Compute the current user's edit permissions for a run.

    `can_edit_planned` is true iff the run is in PLANNED status and the user
    can edit its setup (overrides, name, assignees). The rules mirror PUT
    `/runs/{run_id}`: any user with EDIT on the run (org admins, project
    admins, explicit grantees, or any org member when the parent project
    has permissions_enabled=false), plus the run creator on
    permissions_enabled=true projects.
    """
    can_view = await check_permission(
        db,
        user.id,
        ObjectType.RUN,
        run_id,
        PermissionLevel.VIEW,
    )
    if not can_view:
        raise HTTPException(status_code=403, detail="Insufficient permissions")

    run_obj = await get_or_404(db, Run, run_id)
    status_str = (
        run_obj.status if isinstance(run_obj.status, str) else run_obj.status.value
    )

    has_edit = await check_permission(
        db,
        user.id,
        ObjectType.RUN,
        run_id,
        PermissionLevel.EDIT,
    )
    is_creator = run_obj.created_by_id == user.id

    can_edit_planned = status_str == "PLANNED" and (has_edit or is_creator)

    return {
        "can_edit_planned": can_edit_planned,
        "is_creator": is_creator,
    }


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
    produces_lot: Optional[bool] = Query(
        None,
        description="Filter by lot-producer designation. Omit to return all.",
    ),
    db: AsyncSession = Depends(get_db),
):
    stmt = select(Run).where(Run.project_id == project_id)
    if produces_lot is not None:
        stmt = stmt.where(Run.produces_lot == produces_lot)
    result = await db.execute(stmt)
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
    run_obj = await get_or_404(db, Run, run_id)
    current_status_str = (
        run_obj.status if isinstance(run_obj.status, str) else run_obj.status.value
    )

    allowed = await check_permission(
        db,
        user.id,
        ObjectType.RUN,
        run_id,
        PermissionLevel.EDIT,
    )
    # Run creator may always edit their own PLANNED run, even on projects
    # with permissions_enabled=true where they don't have an explicit EDIT
    # grant. Once the run leaves PLANNED, normal permission rules apply.
    if (
        not allowed
        and current_status_str == "PLANNED"
        and run_obj.created_by_id == user.id
    ):
        allowed = True
    if not allowed:
        raise HTTPException(status_code=403, detail="Insufficient permissions")

    # F-0086: when toggling produces_lot=true, ensure a lot_number is set
    # either in this payload or already on the run.
    update_dict = update_data.model_dump(exclude_unset=True)
    if update_dict.get("produces_lot") is True:
        next_lot = update_dict.get("lot_number")
        if next_lot is None:
            next_lot = run_obj.lot_number
        if not (next_lot and next_lot.strip()):
            raise HTTPException(
                status_code=422,
                detail="lot_number is required when produces_lot is true",
            )

    # Validate status transitions
    new_status = update_data.status.value if update_data.status else None
    current_status = current_status_str

    # F-0066: strict runs (snapshotted from designated protocols) reject any
    # graph diff that mutates a unit-op field. We reuse diff_unit_op_node so
    # the rule stays consistent with the OVERRIDE_EDIT audit emitter below.
    if run_obj.is_strict and update_data.graph is not None:
        old_nodes = {n["id"]: n for n in iter_unit_op_nodes(run_obj.graph)}
        new_nodes = {n["id"]: n for n in iter_unit_op_nodes(update_data.graph)}
        has_override_edit = any(
            diff_unit_op_node(old_nodes[nid], new_nodes[nid])
            for nid in old_nodes.keys() & new_nodes.keys()
        )
        if has_override_edit:
            raise HTTPException(
                status_code=403,
                detail={
                    "code": "RUN_IS_STRICT",
                    "message": (
                        "Overrides are disabled for runs of approved " "protocols."
                    ),
                },
            )

    # Block graph edits when the run has left PLANNED — overrides are GMP-locked
    # at that point. (F-0081)
    if update_data.graph is not None and current_status != "PLANNED":
        raise HTTPException(
            status_code=422,
            detail="Cannot edit run graph: run must be in PLANNED status to apply overrides",
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
            result = await db.execute(
                select(RunRoleAssignment).where(
                    RunRoleAssignment.run_id == run_id
                )
            )
            assignments = list(result.scalars().all())

            gap = lane_assignment_gap(run_obj.graph, assignments)
            if not gap.has_assignee:
                raise HTTPException(
                    status_code=422,
                    detail="Cannot start run: at least one person must be assigned",
                )
            # Unassigned swimlane OR a stale assignment to a deleted lane —
            # the old set-equality check rejected both with this same message.
            if gap.unassigned_lane_ids or gap.stale_lane_ids:
                raise HTTPException(
                    status_code=422,
                    detail="Cannot start run: not all roles have assigned users",
                )

            # Set started_by_id when run transitions to ACTIVE
            run_obj.started_by_id = user.id

        elif new_status == "COMPLETED":
            # Validate all unit op steps are completed
            exec_data = update_data.execution_data or run_obj.execution_data or {}
            unit_op_ids = [n["id"] for n in iter_unit_op_nodes(run_obj.graph)]

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
            _node_map: dict[str, dict] = {
                n["id"]: n.get("data", {}) for n in iter_unit_op_nodes(run_obj.graph)
            }

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
                            field_label = derive_field_label(
                                param_schema_props,
                                field_key,
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
        _name_map: dict[str, str] = {
            n["id"]: n.get("data", {}).get("label", n["id"])
            for n in iter_unit_op_nodes(run_obj.graph)
        }

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

    # Diff incoming graph against current Run.graph and emit OVERRIDE_EDIT
    # audit entries per changed unit-op field. (F-0081)
    if update_data.graph is not None:
        old_nodes = {n["id"]: n for n in iter_unit_op_nodes(run_obj.graph)}
        new_nodes = {n["id"]: n for n in iter_unit_op_nodes(update_data.graph)}
        for node_id in old_nodes.keys() & new_nodes.keys():
            for diff in diff_unit_op_node(old_nodes[node_id], new_nodes[node_id]):
                await log_audit(
                    db,
                    user.id,
                    "OVERRIDE_EDIT",
                    "Run",
                    run_obj.id,
                    diff,
                )

    changes = update_dict
    if "name" in changes and changes["name"] != run_obj.name:
        run_obj.slug = await assign_slug_or_422(
            db,
            Run,
            Run.project_id,
            run_obj.project_id,
            changes["name"],
            "run",
            exclude_id=run_obj.id,
        )
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
    proto: Protocol | None = None
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

    equipment_ctx, eq_warnings = await build_equipment_context(
        db, user.selected_org_id, graph
    )

    if proto is not None:
        proto_project = await _load_protocol_project(db, proto)
        approval_ctx = await _build_approval_context(db, proto, proto_project)
    else:
        approval_ctx = {
            "approval": None,
            "approval_history": [],
            "unapproved_warning": False,
        }

    # F-0087: GLP sign-offs, run outcome, equipment calibration metadata.
    glp_args = await assemble_signoff_context_args(db, run=run_obj, protocol=proto)

    context, unresolved = build_context(
        protocol_name=protocol_name,
        protocol_description=protocol_description,
        run_name=run_obj.name,
        run_status=run_obj.status,
        started_at=(run_obj.started_at.isoformat() if run_obj.started_at else None),
        completed_at=(
            run_obj.completed_at.isoformat() if run_obj.completed_at else None
        ),
        version_number=proto_version,
        created_at=proto_modified or "",
        roles_with_steps=roles_with_steps,
        flat_steps=flat_steps,
        is_role_based=is_role_based,
        equipment_context=equipment_ctx,
        produces_lot=run_obj.produces_lot,
        execution_data=run_obj.execution_data or {},
        **glp_args,
    )
    # Legacy approval context (F-0066) keeps approval_history /
    # unapproved_warning; the build_context-supplied ``approval`` alias
    # is preserved when no legacy event exists.
    legacy_approval = approval_ctx.get("approval")
    if legacy_approval is not None:
        context["approval"] = legacy_approval
    context["approval_history"] = approval_ctx.get("approval_history", [])
    context["unapproved_warning"] = approval_ctx.get("unapproved_warning", False)
    pdf_bytes = await asyncio.to_thread(render_to_pdf, template_path, context)

    if unresolved:
        logger.warning(
            "Unresolved template variables in run %s: %s", run_obj.id, unresolved
        )
    if eq_warnings:
        logger.warning("Equipment warnings in run %s: %s", run_obj.id, eq_warnings)

    disp = disposition or "attachment"
    filename = f"SOP_{run_obj.name}.pdf".replace(" ", "_")
    return _pdf_response(
        pdf_bytes, filename=filename, disposition=disp, unresolved=unresolved
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
    proto: Protocol | None = None
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

    equipment_ctx, eq_warnings = await build_equipment_context(
        db, user.selected_org_id, graph
    )

    # Build user_map and user_signatures for electronic initials on
    # filled records. user_signatures resolves to absolute paths so the
    # render layer can build InlineImage objects (F-0080).
    user_map: dict[str, str] = {}
    user_signatures: dict[str, dict[str, str]] = {}
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
            sig_storage = FileStorageService()
            result = await db.execute(select(User).where(User.id.in_(user_ids)))
            for u in result.scalars().all():
                user_map[str(u.id)] = u.full_name or u.email
                entry: dict[str, str] = {}
                if u.signature_initials_path:
                    try:
                        entry["signature_initials_path"] = str(
                            sig_storage.resolve_path(u.signature_initials_path)
                        )
                    except (ValueError, FileNotFoundError):
                        pass
                if u.signature_full_path:
                    try:
                        entry["signature_full_path"] = str(
                            sig_storage.resolve_path(u.signature_full_path)
                        )
                    except (ValueError, FileNotFoundError):
                        pass
                if entry:
                    user_signatures[str(u.id)] = entry

    run_status = _run_status_str(run_obj)

    if proto is not None:
        proto_project = await _load_protocol_project(db, proto)
        approval_ctx = await _build_approval_context(db, proto, proto_project)
    else:
        approval_ctx = {
            "approval": None,
            "approval_history": [],
            "unapproved_warning": False,
        }

    context, unresolved = build_context(
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
        user_signatures=user_signatures if filled else None,
        started_by_id=started_by_id_str,
        notes=run_obj.notes if filled else None,
        attachments=run_obj.attachments if filled else None,
        storage=FileStorageService() if filled and embed_images else None,
        equipment_context=equipment_ctx,
        produces_lot=run_obj.produces_lot,
    )
    context.update(approval_ctx)
    pdf_bytes = await asyncio.to_thread(render_to_pdf, template_path, context)

    if unresolved:
        logger.warning(
            "Unresolved template variables in run %s: %s", run_obj.id, unresolved
        )
    if eq_warnings:
        logger.warning("Equipment warnings in run %s: %s", run_obj.id, eq_warnings)

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
        headers = {"Content-Disposition": f'attachment; filename="{zip_name}"'}
        if unresolved:
            headers["X-Unresolved-Placeholders"] = ",".join(unresolved)
        return Response(
            content=zip_buf.getvalue(),
            media_type="application/zip",
            headers=headers,
        )

    filename = f"BatchRecord_{safe_name}_{suffix}.pdf"
    return _pdf_response(
        pdf_bytes, filename=filename, disposition=disp, unresolved=unresolved
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


# --- GLP Sign-offs (F-0087) -----------------------------------------------


@router.post(
    "/runs/{run_id}/signoffs",
    response_model=GlpSignoffResponse,
    status_code=201,
)
async def create_run_signoff(
    run_id: UUID,
    payload: GlpSignoffCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> GlpSignoffResponse:
    """Create a GLP sign-off on a run.

    Replaces the originally-proposed standalone ``RunSignoff`` model; see
    F-0087 design spec. Permission and QAU-independence checks run inside
    :func:`app.services.signoffs.service.create_signoff` via the cross-context
    validators. The role/entity compatibility matrix is enforced by the
    ``ck_run_signoff_roles`` DB constraint and surfaced here as 400.
    """
    run = await get_or_404(db, Run, run_id)

    try:
        signoff = await create_signoff(
            db,
            entity_type="run",
            entity_id=run.id,
            role=payload.role,
            action=payload.action,
            signer=user,
            attestation=payload.attestation,
            signoff_request_id=payload.signoff_request_id,
        )
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(
            status_code=400,
            detail={
                "error": "INVALID_SIGNOFF",
                "role": payload.role,
                "entity_type": "run",
            },
        ) from exc

    return GlpSignoffResponse.model_validate(signoff)


# --- Run lifecycle: complete (F-0087 Task 14) ------------------------------


@router.post(
    "/runs/{run_id}/complete",
    response_model=RunResponse,
)
async def complete_run(
    run_id: UUID,
    payload: RunCompleteRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> RunResponse:
    """Transition an ACTIVE/EDITED run to COMPLETED.

    Gates closure on the GLP sign-off matrix resolved from the linked
    protocol's ``graph["glpSettings"]`` snapshot (see
    :func:`app.services.runs.validation.assert_run_can_close`). Records the
    outcome, optional outcome_notes, and a UTC ``completed_at`` timestamp.
    """
    run = await get_or_404(db, Run, run_id)
    status_str = _run_status_str(run)
    if status_str not in ("ACTIVE", "EDITED"):
        raise HTTPException(
            status_code=400,
            detail={"error": "INVALID_RUN_STATE", "status": status_str},
        )

    # Resolve effective glpSettings from the run's protocol snapshot.
    glp_settings: dict = {}
    if run.protocol_id is not None:
        proto = await db.get(Protocol, run.protocol_id)
        if proto is not None and isinstance(proto.graph, dict):
            glp_settings = proto.graph.get("glpSettings") or {}

    await assert_run_can_close(db, run, glp_settings)

    run.status = "COMPLETED"
    run.outcome = payload.outcome
    run.outcome_notes = payload.outcome_notes
    run.completed_at = datetime.now(timezone.utc)

    await db.commit()
    await db.refresh(run)
    return RunResponse.model_validate(run)


# --- Run lifecycle: reopen (F-0087 Task 15) --------------------------------


@router.post(
    "/runs/{run_id}/reopen",
    response_model=RunResponse,
)
async def reopen_run(
    run_id: UUID,
    payload: RunReopenRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> RunResponse:
    """Reopen a COMPLETED run, invalidating all active sign-offs.

    Transitions the run back to EDITED, clears ``completed_at``, and writes a
    ``run.reopen`` audit entry capturing the supplied justification reason.
    """
    run = await get_or_404(db, Run, run_id)
    status_str = _run_status_str(run)
    if status_str != "COMPLETED":
        raise HTTPException(
            status_code=400,
            detail={"error": "INVALID_RUN_STATE", "status": status_str},
        )

    await invalidate_active_signoffs(
        db,
        run.id,
        reason=payload.reason,
        user_id=user.id,
    )
    run.status = "EDITED"
    run.completed_at = None
    await log_audit(
        db,
        user.id,
        "run.reopen",
        "run",
        run.id,
        {"reason": payload.reason},
    )
    await db.commit()
    await db.refresh(run)
    return RunResponse.model_validate(run)


# --- Run state lifecycle (F-0087 Tasks 17-18) ------------------------------


_RUN_STATE_TRANSITIONS = {
    "PLANNED": {"ACTIVE"},
    "ACTIVE": {"COMPLETED", "EDITED"},
    "COMPLETED": {"EDITED"},
    "EDITED": {"EDITED", "COMPLETED"},
}


@router.patch(
    "/runs/{run_id}/state",
    response_model=RunResponse,
)
async def patch_run_state(
    run_id: UUID,
    payload: RunStateUpdate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> RunResponse:
    """Transition a run's lifecycle state with GLP audit-trail inputs.

    PLANNED -> ACTIVE stamps ``started_at`` and ``started_by_id``.
    Any -> EDITED requires a non-blank ``edit_reason`` for each modified
    step in ``execution_data_delta``; reasons are persisted onto the
    matching ``execution_data[step_id].edit_reason`` so downstream readers
    (PDFs, audit log views) can render them. A COMPLETED run with active
    sign-offs cannot be edited without first reopening it.
    """
    run = await get_or_404(db, Run, run_id)
    current_status = _run_status_str(run)
    new_status = payload.state

    if new_status is not None and new_status != current_status:
        allowed_next = _RUN_STATE_TRANSITIONS.get(current_status, set())
        if new_status not in allowed_next:
            raise HTTPException(
                status_code=422,
                detail=(f"Cannot transition from {current_status} to {new_status}"),
            )

    if new_status == "EDITED":
        delta = payload.execution_data_delta or {}
        reasons = payload.edit_reasons or {}
        merged = {
            sid: {**fields, "edit_reason": reasons.get(sid)}
            for sid, fields in delta.items()
        }
        assert_no_unjustified_edit_errors(merged)
        await assert_can_edit_completed_run(db, run)

        # Persist the edit_reason into execution_data[sid].edit_reason and
        # apply the per-step field delta so the audit trail stays consistent
        # with the request payload.
        exec_data = dict(run.execution_data or {})
        for sid, fields in delta.items():
            step = dict(exec_data.get(sid) or {})
            for key, value in fields.items():
                step[key] = value
            step["edit_reason"] = reasons.get(sid)
            exec_data[sid] = step
        run.execution_data = exec_data
        flag_modified(run, "execution_data")

    if new_status is not None and new_status != current_status:
        if new_status == "ACTIVE" and current_status == "PLANNED":
            # F-0087 Task 18: stamp run-start metadata.
            run.started_at = datetime.now(timezone.utc)
            run.started_by_id = user.id
        run.status = new_status

    await log_audit(
        db,
        user.id,
        "run.state",
        "run",
        run.id,
        {
            "from": current_status,
            "to": new_status,
            "edit_reasons": payload.edit_reasons or {},
        },
    )

    await db.commit()
    await db.refresh(run)
    return RunResponse.model_validate(run)


# --- Run step state (F-0087 Task 19) ---------------------------------------


@router.patch(
    "/runs/{run_id}/steps/{step_id}",
    response_model=RunResponse,
)
async def patch_run_step_state(
    run_id: UUID,
    step_id: str,
    payload: RunStepStateUpdate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> RunResponse:
    """Transition a single step's status within a run.

    On the ``not in_progress -> in_progress`` edge, captures the actor and
    timestamp (F-0087 Task 19) so a later ``/review`` can enforce
    second-set-of-eyes independence.
    """
    run = await get_or_404(db, Run, run_id)
    exec_data = dict(run.execution_data or {})
    step = dict(exec_data.get(step_id) or {})

    old_status = step.get("status")
    new_step_status = payload.status

    if new_step_status == "in_progress" and old_status != "in_progress":
        step["started_by_user_id"] = str(user.id)
        step["started_at"] = datetime.now(timezone.utc).isoformat()

    step["status"] = new_step_status
    exec_data[step_id] = step
    run.execution_data = exec_data
    flag_modified(run, "execution_data")

    await log_audit(
        db,
        user.id,
        "run.step.state",
        "run_step",
        run.id,
        {"step_id": step_id, "from": old_status, "to": new_step_status},
    )

    await db.commit()
    await db.refresh(run)
    return RunResponse.model_validate(run)


# --- Run step review (F-0087 Task 20) --------------------------------------


@router.post(
    "/runs/{run_id}/steps/{step_id}/review",
    response_model=RunResponse,
)
async def review_run_step(
    run_id: UUID,
    step_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> RunResponse:
    """Record an independent reviewer's sign-off on a completed step.

    The reviewer cannot be the same user who started the step (F-0087
    Task 20). Sets ``reviewed_by_user_id`` and ``reviewed_at`` on the
    matching ``execution_data`` entry and emits a ``run.step.review``
    audit log row.
    """
    run = await get_or_404(db, Run, run_id)
    step = (run.execution_data or {}).get(step_id)
    if step is None or step.get("status") != "completed":
        raise HTTPException(
            status_code=400,
            detail={"error": "STEP_NOT_REVIEWABLE", "step_id": step_id},
        )
    if step.get("started_by_user_id") == str(user.id):
        raise HTTPException(
            status_code=400,
            detail={"error": "REVIEWER_NOT_INDEPENDENT", "step_id": step_id},
        )

    step = dict(step)
    step["reviewed_by_user_id"] = str(user.id)
    step["reviewed_at"] = datetime.now(timezone.utc).isoformat()
    run.execution_data = {**(run.execution_data or {}), step_id: step}
    flag_modified(run, "execution_data")

    await log_audit(
        db,
        user.id,
        "run.step.review",
        "run_step",
        run.id,
        {"step_id": step_id},
    )

    await db.commit()
    await db.refresh(run)
    return RunResponse.model_validate(run)


# --- Sign-off listing (F-0087 Task 16) -------------------------------------


@router.get(
    "/runs/{run_id}/signoffs",
    response_model=List[GlpSignoffResponse],
)
async def list_run_signoffs(
    run_id: UUID,
    active: bool = False,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> List[GlpSignoffResponse]:
    """List sign-offs on a run.

    ``active=true`` returns only non-invalidated APPROVED rows (the live
    sign-off set). ``active=false`` (default) returns the full audit trail
    including invalidated rows, ordered by ``signed_at`` ascending.
    """
    if active:
        rows = await list_active_signoffs(db, "run", run_id)
    else:
        result = await db.execute(
            select(GlpSignoff)
            .where(GlpSignoff.run_id == run_id)
            .order_by(GlpSignoff.signed_at)
        )
        rows = result.scalars().all()
    return [GlpSignoffResponse.model_validate(r) for r in rows]
