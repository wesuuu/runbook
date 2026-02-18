from typing import List
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.deps import get_current_user, require_permission
from app.db.session import get_db
from app.models.iam import (
    User,
    ObjectType,
    PermissionLevel,
    ObjectPermission,
    OrganizationMember,
    TeamMember,
)
from app.models.science import (
    UnitOpDefinition,
    Protocol,
    Experiment,
    ProtocolRole,
    Project,
    ExperimentRoleAssignment,
)
from app.schemas.science import (
    UnitOpDefinitionCreate,
    UnitOpDefinitionUpdate,
    UnitOpDefinitionResponse,
    ProtocolCreate,
    ProtocolUpdate,
    ProtocolResponse,
    ProtocolRoleCreate,
    ProtocolRoleUpdate,
    ProtocolRoleResponse,
    ExperimentCreate,
    ExperimentUpdate,
    ExperimentResponse,
    ExperimentRoleAssignmentCreate,
    ExperimentRoleAssignmentResponse,
    ExperimentRoleAssignmentListResponse,
)
from app.schemas.iam import UserSearchResponse
from app.services.audit import log_audit
from app.services.permissions import check_permission

router = APIRouter()


# --- UnitOps (auth only, no per-object perms) ---

@router.get("/unit-ops", response_model=List[UnitOpDefinitionResponse])
async def list_unit_ops(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(UnitOpDefinition))
    return result.scalars().all()


@router.post(
    "/unit-ops",
    response_model=UnitOpDefinitionResponse,
    status_code=201,
)
async def create_unit_op(
    unit_op: UnitOpDefinitionCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    new_op = UnitOpDefinition(
        name=unit_op.name,
        category=unit_op.category,
        description=unit_op.description,
        param_schema=unit_op.param_schema,
    )
    db.add(new_op)
    await db.commit()
    await db.refresh(new_op)
    return new_op


@router.put(
    "/unit-ops/{unit_op_id}",
    response_model=UnitOpDefinitionResponse,
)
async def update_unit_op(
    unit_op_id: UUID,
    update_data: UnitOpDefinitionUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Update a global unit op definition.

    Args:
        unit_op_id: The UUID of the unit op to update.
        update_data: Partial update fields.
        user: Authenticated user.
        db: Async DB session.

    Returns:
        Updated UnitOpDefinitionResponse.

    Raises:
        HTTPException: 404 if not found.
    """
    result = await db.execute(
        select(UnitOpDefinition).where(UnitOpDefinition.id == unit_op_id)
    )
    unit_op = result.scalar_one_or_none()
    if not unit_op:
        raise HTTPException(status_code=404, detail="Unit op not found")

    changes = update_data.model_dump(exclude_unset=True)
    for key, value in changes.items():
        setattr(unit_op, key, value)

    await db.commit()
    await db.refresh(unit_op)
    return unit_op


# --- Protocols ---

@router.post(
    "/protocols", response_model=ProtocolResponse, status_code=201,
)
async def create_protocol(
    protocol: ProtocolCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    # Check user has EDIT on the parent project
    allowed = await check_permission(
        db, user.id, ObjectType.PROJECT,
        protocol.project_id, PermissionLevel.EDIT,
    )
    if not allowed:
        raise HTTPException(
            status_code=403,
            detail="EDIT permission required on project",
        )

    result = await db.execute(
        select(Project).where(Project.id == protocol.project_id)
    )
    if result.scalar_one_or_none() is None:
        raise HTTPException(status_code=404, detail="Project not found")

    new_protocol = Protocol(
        name=protocol.name,
        description=protocol.description,
        project_id=protocol.project_id,
        graph=protocol.graph,
    )
    db.add(new_protocol)
    await db.flush()

    await log_audit(
        db, user.id, "CREATE", "Protocol",
        new_protocol.id, {"name": protocol.name},
    )

    await db.commit()

    result = await db.execute(
        select(Protocol)
        .options(selectinload(Protocol.roles))
        .where(Protocol.id == new_protocol.id)
    )
    return result.scalar_one()


@router.get("/protocols/{protocol_id}", response_model=ProtocolResponse)
async def get_protocol(
    protocol_id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    allowed = await check_permission(
        db, user.id, ObjectType.PROTOCOL,
        protocol_id, PermissionLevel.VIEW,
    )
    if not allowed:
        raise HTTPException(status_code=403, detail="Insufficient permissions")

    result = await db.execute(
        select(Protocol)
        .options(selectinload(Protocol.roles))
        .where(Protocol.id == protocol_id)
    )
    protocol = result.scalar_one_or_none()
    if not protocol:
        raise HTTPException(status_code=404, detail="Protocol not found")
    return protocol


@router.get(
    "/projects/{project_id}/protocols",
    response_model=List[ProtocolResponse],
    dependencies=[
        Depends(
            require_permission(
                ObjectType.PROJECT, "project_id", PermissionLevel.VIEW
            )
        )
    ],
)
async def list_project_protocols(
    project_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Protocol)
        .options(selectinload(Protocol.roles))
        .where(Protocol.project_id == project_id)
    )
    return result.scalars().all()


@router.put("/protocols/{protocol_id}", response_model=ProtocolResponse)
async def update_protocol(
    protocol_id: UUID,
    update_data: ProtocolUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    allowed = await check_permission(
        db, user.id, ObjectType.PROTOCOL,
        protocol_id, PermissionLevel.EDIT,
    )
    if not allowed:
        raise HTTPException(status_code=403, detail="Insufficient permissions")

    result = await db.execute(
        select(Protocol)
        .options(selectinload(Protocol.roles))
        .where(Protocol.id == protocol_id)
    )
    protocol = result.scalar_one_or_none()
    if not protocol:
        raise HTTPException(status_code=404, detail="Protocol not found")

    changes = update_data.model_dump(exclude_unset=True)
    for key, value in changes.items():
        setattr(protocol, key, value)

    await log_audit(
        db, user.id, "UPDATE", "Protocol", protocol.id, changes,
    )

    await db.commit()

    result = await db.execute(
        select(Protocol)
        .options(selectinload(Protocol.roles))
        .where(Protocol.id == protocol.id)
    )
    return result.scalar_one()


# --- Protocol Roles (inherit project perms) ---

@router.get(
    "/protocols/{protocol_id}/roles",
    response_model=List[ProtocolRoleResponse],
)
async def list_protocol_roles(
    protocol_id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    allowed = await check_permission(
        db, user.id, ObjectType.PROTOCOL,
        protocol_id, PermissionLevel.VIEW,
    )
    if not allowed:
        raise HTTPException(status_code=403, detail="Insufficient permissions")

    result = await db.execute(
        select(ProtocolRole)
        .where(ProtocolRole.protocol_id == protocol_id)
        .order_by(ProtocolRole.sort_order)
    )
    return result.scalars().all()


@router.post(
    "/protocols/{protocol_id}/roles",
    response_model=ProtocolRoleResponse,
    status_code=201,
)
async def create_protocol_role(
    protocol_id: UUID,
    role: ProtocolRoleCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    allowed = await check_permission(
        db, user.id, ObjectType.PROTOCOL,
        protocol_id, PermissionLevel.EDIT,
    )
    if not allowed:
        raise HTTPException(status_code=403, detail="Insufficient permissions")

    result = await db.execute(
        select(Protocol).where(Protocol.id == protocol_id)
    )
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Protocol not found")

    new_role = ProtocolRole(
        protocol_id=protocol_id,
        name=role.name,
        color=role.color,
        sort_order=role.sort_order,
    )
    db.add(new_role)
    await db.commit()
    await db.refresh(new_role)
    return new_role


@router.put(
    "/protocols/{protocol_id}/roles/{role_id}",
    response_model=ProtocolRoleResponse,
)
async def update_protocol_role(
    protocol_id: UUID,
    role_id: UUID,
    update_data: ProtocolRoleUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    allowed = await check_permission(
        db, user.id, ObjectType.PROTOCOL,
        protocol_id, PermissionLevel.EDIT,
    )
    if not allowed:
        raise HTTPException(status_code=403, detail="Insufficient permissions")

    result = await db.execute(
        select(ProtocolRole).where(
            ProtocolRole.id == role_id,
            ProtocolRole.protocol_id == protocol_id,
        )
    )
    role = result.scalar_one_or_none()
    if not role:
        raise HTTPException(status_code=404, detail="Role not found")

    changes = update_data.model_dump(exclude_unset=True)
    for key, value in changes.items():
        setattr(role, key, value)

    await db.commit()
    await db.refresh(role)
    return role


@router.delete("/protocols/{protocol_id}/roles/{role_id}")
async def delete_protocol_role(
    protocol_id: UUID,
    role_id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    allowed = await check_permission(
        db, user.id, ObjectType.PROTOCOL,
        protocol_id, PermissionLevel.EDIT,
    )
    if not allowed:
        raise HTTPException(status_code=403, detail="Insufficient permissions")

    result = await db.execute(
        select(ProtocolRole).where(
            ProtocolRole.id == role_id,
            ProtocolRole.protocol_id == protocol_id,
        )
    )
    role = result.scalar_one_or_none()
    if not role:
        raise HTTPException(status_code=404, detail="Role not found")

    await db.delete(role)
    await db.commit()
    return {"ok": True}


# --- Experiments ---

@router.post(
    "/experiments", response_model=ExperimentResponse, status_code=201,
)
async def create_experiment(
    experiment: ExperimentCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    allowed = await check_permission(
        db, user.id, ObjectType.PROJECT,
        experiment.project_id, PermissionLevel.EDIT,
    )
    if not allowed:
        raise HTTPException(
            status_code=403,
            detail="EDIT permission required on project",
        )

    result = await db.execute(
        select(Project).where(Project.id == experiment.project_id)
    )
    if result.scalar_one_or_none() is None:
        raise HTTPException(status_code=404, detail="Project not found")

    initial_graph = {}
    if experiment.protocol_id:
        result = await db.execute(
            select(Protocol).where(Protocol.id == experiment.protocol_id)
        )
        protocol = result.scalar_one_or_none()
        if protocol:
            initial_graph = protocol.graph.copy() if protocol.graph else {}

    new_experiment = Experiment(
        name=experiment.name,
        project_id=experiment.project_id,
        protocol_id=experiment.protocol_id,
        graph=initial_graph,
        execution_data={},
    )
    db.add(new_experiment)
    await db.flush()

    await log_audit(
        db, user.id, "CREATE", "Experiment",
        new_experiment.id, {"name": experiment.name},
    )

    await db.commit()
    await db.refresh(new_experiment)
    return new_experiment


@router.get("/experiments/{experiment_id}", response_model=ExperimentResponse)
async def get_experiment(
    experiment_id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    allowed = await check_permission(
        db, user.id, ObjectType.EXPERIMENT,
        experiment_id, PermissionLevel.VIEW,
    )
    if not allowed:
        raise HTTPException(status_code=403, detail="Insufficient permissions")

    result = await db.execute(
        select(Experiment).where(Experiment.id == experiment_id)
    )
    experiment = result.scalar_one_or_none()
    if not experiment:
        raise HTTPException(status_code=404, detail="Experiment not found")
    return experiment


@router.get(
    "/projects/{project_id}/experiments",
    response_model=List[ExperimentResponse],
    dependencies=[
        Depends(
            require_permission(
                ObjectType.PROJECT, "project_id", PermissionLevel.VIEW
            )
        )
    ],
)
async def list_project_experiments(
    project_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Experiment).where(Experiment.project_id == project_id)
    )
    return result.scalars().all()


@router.put(
    "/experiments/{experiment_id}", response_model=ExperimentResponse,
)
async def update_experiment(
    experiment_id: UUID,
    update_data: ExperimentUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    allowed = await check_permission(
        db, user.id, ObjectType.EXPERIMENT,
        experiment_id, PermissionLevel.EDIT,
    )
    if not allowed:
        raise HTTPException(status_code=403, detail="Insufficient permissions")

    result = await db.execute(
        select(Experiment).where(Experiment.id == experiment_id)
    )
    experiment = result.scalar_one_or_none()
    if not experiment:
        raise HTTPException(status_code=404, detail="Experiment not found")

    # Validate status transition to ACTIVE
    new_status = update_data.status.value if update_data.status else None
    current_status = experiment.status if isinstance(experiment.status, str) else experiment.status.value
    if (new_status and
        new_status == "ACTIVE" and
        current_status != "ACTIVE"):
        # Check that all swimlane roles in the graph have assignments
        graph = experiment.graph or {}
        nodes = graph.get("nodes", [])
        swimlane_nodes = [n for n in nodes if n.get("type") == "swimLane"]

        if swimlane_nodes:
            result = await db.execute(
                select(ExperimentRoleAssignment)
                .where(ExperimentRoleAssignment.experiment_id == experiment_id)
            )
            assignments = result.scalars().all()
            assigned_lanes = {a.lane_node_id for a in assignments}
            required_lanes = {n["id"] for n in swimlane_nodes}

            if assigned_lanes != required_lanes:
                raise HTTPException(
                    status_code=422,
                    detail="Cannot start experiment: not all roles have assigned users",
                )

    changes = update_data.model_dump(exclude_unset=True)
    for key, value in changes.items():
        setattr(experiment, key, value)

    await log_audit(
        db, user.id, "UPDATE", "Experiment", experiment.id, changes,
    )

    await db.commit()
    await db.refresh(experiment)
    return experiment


# --- Project Members ---

@router.get(
    "/projects/{project_id}/members",
    response_model=List[UserSearchResponse],
)
async def get_project_members(
    project_id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get all users who have access to a project.

    This includes:
    - Users with direct ObjectPermission rows on the project
    - Users who belong to teams with ObjectPermission on the project
    - Organization admins
    """
    # Check VIEW permission on project
    allowed = await check_permission(
        db, user.id, ObjectType.PROJECT,
        project_id, PermissionLevel.VIEW,
    )
    if not allowed:
        raise HTTPException(status_code=403, detail="Insufficient permissions")

    # Get the project to find its org
    result = await db.execute(
        select(Project).where(Project.id == project_id)
    )
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    user_ids = set()

    # 1. Direct USER permissions on project
    result = await db.execute(
        select(ObjectPermission)
        .where(and_(
            ObjectPermission.object_type == ObjectType.PROJECT,
            ObjectPermission.object_id == project_id,
            ObjectPermission.principal_type == "USER",
        ))
    )
    for perm in result.scalars().all():
        user_ids.add(perm.principal_id)

    # 2. TEAM permissions on project → expand to team members
    result = await db.execute(
        select(ObjectPermission)
        .where(and_(
            ObjectPermission.object_type == ObjectType.PROJECT,
            ObjectPermission.object_id == project_id,
            ObjectPermission.principal_type == "TEAM",
        ))
    )
    team_perms = result.scalars().all()
    if team_perms:
        team_ids = [p.principal_id for p in team_perms]
        result = await db.execute(
            select(TeamMember)
            .where(TeamMember.team_id.in_(team_ids))
        )
        for tm in result.scalars().all():
            user_ids.add(tm.user_id)

    # 3. Organization admins
    result = await db.execute(
        select(OrganizationMember)
        .where(and_(
            OrganizationMember.organization_id == project.organization_id,
            OrganizationMember.is_admin is True,
        ))
    )
    for om in result.scalars().all():
        user_ids.add(om.user_id)

    # Fetch all users
    if not user_ids:
        return []

    result = await db.execute(
        select(User).where(User.id.in_(user_ids))
    )
    users = result.scalars().all()
    return users


# --- Experiment Role Assignments ---

@router.get(
    "/experiments/{experiment_id}/role-assignments",
    response_model=ExperimentRoleAssignmentListResponse,
)
async def get_experiment_role_assignments(
    experiment_id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get all role assignments for an experiment."""
    allowed = await check_permission(
        db, user.id, ObjectType.EXPERIMENT,
        experiment_id, PermissionLevel.VIEW,
    )
    if not allowed:
        raise HTTPException(status_code=403, detail="Insufficient permissions")

    result = await db.execute(
        select(ExperimentRoleAssignment)
        .where(ExperimentRoleAssignment.experiment_id == experiment_id)
    )
    assignments = result.scalars().all()
    return ExperimentRoleAssignmentListResponse(items=assignments)


@router.post(
    "/experiments/{experiment_id}/role-assignments",
    response_model=ExperimentRoleAssignmentResponse,
    status_code=201,
)
async def create_experiment_role_assignment(
    experiment_id: UUID,
    assignment: ExperimentRoleAssignmentCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Assign a user to a role in an experiment."""
    allowed = await check_permission(
        db, user.id, ObjectType.EXPERIMENT,
        experiment_id, PermissionLevel.EDIT,
    )
    if not allowed:
        raise HTTPException(status_code=403, detail="Insufficient permissions")

    result = await db.execute(
        select(Experiment).where(Experiment.id == experiment_id)
    )
    experiment = result.scalar_one_or_none()
    if not experiment:
        raise HTTPException(status_code=404, detail="Experiment not found")

    # Verify user exists
    result = await db.execute(
        select(User).where(User.id == assignment.user_id)
    )
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="User not found")

    # Check if assignment already exists for this lane
    result = await db.execute(
        select(ExperimentRoleAssignment)
        .where(and_(
            ExperimentRoleAssignment.experiment_id == experiment_id,
            ExperimentRoleAssignment.lane_node_id == assignment.lane_node_id,
        ))
    )
    existing = result.scalar_one_or_none()
    if existing:
        # Update existing assignment
        existing.user_id = assignment.user_id
        existing.role_name = assignment.role_name
        await db.commit()
        await db.refresh(existing)
        return existing

    # Create new assignment
    new_assignment = ExperimentRoleAssignment(
        experiment_id=experiment_id,
        lane_node_id=assignment.lane_node_id,
        role_name=assignment.role_name,
        user_id=assignment.user_id,
    )
    db.add(new_assignment)
    await db.commit()
    await db.refresh(new_assignment)
    return new_assignment


@router.delete("/experiments/{experiment_id}/role-assignments/{assignment_id}")
async def delete_experiment_role_assignment(
    experiment_id: UUID,
    assignment_id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Remove a user's role assignment."""
    allowed = await check_permission(
        db, user.id, ObjectType.EXPERIMENT,
        experiment_id, PermissionLevel.EDIT,
    )
    if not allowed:
        raise HTTPException(status_code=403, detail="Insufficient permissions")

    result = await db.execute(
        select(ExperimentRoleAssignment)
        .where(and_(
            ExperimentRoleAssignment.id == assignment_id,
            ExperimentRoleAssignment.experiment_id == experiment_id,
        ))
    )
    assignment = result.scalar_one_or_none()
    if not assignment:
        raise HTTPException(status_code=404, detail="Assignment not found")

    await db.delete(assignment)
    await db.commit()
    return {"ok": True}
