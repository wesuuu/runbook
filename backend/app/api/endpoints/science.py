from typing import List, Optional
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.orm import selectinload

from app.db.session import get_db
from app.models.science import UnitOpDefinition, Protocol, Experiment, ProtocolRole
from app.schemas.science import (
    UnitOpDefinitionCreate, UnitOpDefinitionResponse,
    ProtocolCreate, ProtocolUpdate, ProtocolResponse,
    ProtocolRoleCreate, ProtocolRoleUpdate, ProtocolRoleResponse,
    ExperimentCreate, ExperimentUpdate, ExperimentResponse
)
from app.services.audit import log_audit

router = APIRouter()

# --- UnitOps ---
@router.get("/unit-ops", response_model=List[UnitOpDefinitionResponse])
async def list_unit_ops(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(UnitOpDefinition))
    return result.scalars().all()

@router.post("/unit-ops", response_model=UnitOpDefinitionResponse)
async def create_unit_op(unit_op: UnitOpDefinitionCreate, db: AsyncSession = Depends(get_db)):
    new_op = UnitOpDefinition(
        name=unit_op.name,
        category=unit_op.category,
        description=unit_op.description,
        param_schema=unit_op.param_schema
    )
    db.add(new_op)
    await db.commit()
    await db.refresh(new_op)
    return new_op

# --- Protocols ---
@router.post("/protocols", response_model=ProtocolResponse)
async def create_protocol(protocol: ProtocolCreate, db: AsyncSession = Depends(get_db)):
    from app.models.science import Project
    result = await db.execute(select(Project).where(Project.id == protocol.project_id))
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    new_protocol = Protocol(
        name=protocol.name,
        description=protocol.description,
        project_id=protocol.project_id,
        graph=protocol.graph
    )
    db.add(new_protocol)
    await db.commit()
    
    actor_id = UUID("00000000-0000-0000-0000-000000000000") 
    await log_audit(db, actor_id, "CREATE", "Protocol", new_protocol.id, {"name": protocol.name})
    
    # Re-fetch with roles eagerly loaded to avoid lazy load error
    result = await db.execute(
        select(Protocol)
        .options(selectinload(Protocol.roles))
        .where(Protocol.id == new_protocol.id)
    )
    return result.scalar_one()

@router.get("/protocols/{protocol_id}", response_model=ProtocolResponse)
async def get_protocol(protocol_id: UUID, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Protocol)
        .options(selectinload(Protocol.roles))
        .where(Protocol.id == protocol_id)
    )
    protocol = result.scalar_one_or_none()
    if not protocol:
        raise HTTPException(status_code=404, detail="Protocol not found")
    return protocol

@router.get("/projects/{project_id}/protocols", response_model=List[ProtocolResponse])
async def list_project_protocols(project_id: UUID, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Protocol)
        .options(selectinload(Protocol.roles))
        .where(Protocol.project_id == project_id)
    )
    return result.scalars().all()

@router.put("/protocols/{protocol_id}", response_model=ProtocolResponse)
async def update_protocol(protocol_id: UUID, update_data: ProtocolUpdate, db: AsyncSession = Depends(get_db)):
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
    
    await db.commit()

    actor_id = UUID("00000000-0000-0000-0000-000000000000")
    await log_audit(db, actor_id, "UPDATE", "Protocol", protocol.id, changes)
    
    # Re-fetch with roles eagerly loaded
    result = await db.execute(
        select(Protocol)
        .options(selectinload(Protocol.roles))
        .where(Protocol.id == protocol.id)
    )
    return result.scalar_one()

# --- Protocol Roles ---
@router.get("/protocols/{protocol_id}/roles", response_model=List[ProtocolRoleResponse])
async def list_protocol_roles(protocol_id: UUID, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(ProtocolRole)
        .where(ProtocolRole.protocol_id == protocol_id)
        .order_by(ProtocolRole.sort_order)
    )
    return result.scalars().all()

@router.post("/protocols/{protocol_id}/roles", response_model=ProtocolRoleResponse)
async def create_protocol_role(protocol_id: UUID, role: ProtocolRoleCreate, db: AsyncSession = Depends(get_db)):
    # Verify protocol exists
    result = await db.execute(select(Protocol).where(Protocol.id == protocol_id))
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Protocol not found")

    new_role = ProtocolRole(
        protocol_id=protocol_id,
        name=role.name,
        color=role.color,
        sort_order=role.sort_order
    )
    db.add(new_role)
    await db.commit()
    await db.refresh(new_role)
    return new_role

@router.put("/protocols/{protocol_id}/roles/{role_id}", response_model=ProtocolRoleResponse)
async def update_protocol_role(protocol_id: UUID, role_id: UUID, update_data: ProtocolRoleUpdate, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(ProtocolRole)
        .where(ProtocolRole.id == role_id, ProtocolRole.protocol_id == protocol_id)
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
async def delete_protocol_role(protocol_id: UUID, role_id: UUID, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(ProtocolRole)
        .where(ProtocolRole.id == role_id, ProtocolRole.protocol_id == protocol_id)
    )
    role = result.scalar_one_or_none()
    if not role:
        raise HTTPException(status_code=404, detail="Role not found")
    
    await db.delete(role)
    await db.commit()
    return {"ok": True}

# --- Experiments ---
@router.post("/experiments", response_model=ExperimentResponse)
async def create_experiment(experiment: ExperimentCreate, db: AsyncSession = Depends(get_db)):
    from app.models.science import Project
    result = await db.execute(select(Project).where(Project.id == experiment.project_id))
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    initial_graph = {}
    if experiment.protocol_id:
        result = await db.execute(select(Protocol).where(Protocol.id == experiment.protocol_id))
        protocol = result.scalar_one_or_none()
        if protocol:
            initial_graph = protocol.graph.copy() if protocol.graph else {}

    new_experiment = Experiment(
        name=experiment.name,
        project_id=experiment.project_id,
        protocol_id=experiment.protocol_id,
        graph=initial_graph,
        execution_data={}
    )
    db.add(new_experiment)
    await db.commit()
    await db.refresh(new_experiment)

    actor_id = UUID("00000000-0000-0000-0000-000000000000")
    await log_audit(db, actor_id, "CREATE", "Experiment", new_experiment.id, {"name": experiment.name})
    
    return new_experiment

@router.get("/experiments/{experiment_id}", response_model=ExperimentResponse)
async def get_experiment(experiment_id: UUID, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Experiment).where(Experiment.id == experiment_id))
    experiment = result.scalar_one_or_none()
    if not experiment:
        raise HTTPException(status_code=404, detail="Experiment not found")
    return experiment

@router.get("/projects/{project_id}/experiments", response_model=List[ExperimentResponse])
async def list_project_experiments(project_id: UUID, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Experiment).where(Experiment.project_id == project_id))
    return result.scalars().all()

@router.put("/experiments/{experiment_id}", response_model=ExperimentResponse)
async def update_experiment(experiment_id: UUID, update_data: ExperimentUpdate, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Experiment).where(Experiment.id == experiment_id))
    experiment = result.scalar_one_or_none()
    if not experiment:
        raise HTTPException(status_code=404, detail="Experiment not found")
    
    changes = update_data.model_dump(exclude_unset=True)
    for key, value in changes.items():
        setattr(experiment, key, value)
    
    await db.commit()
    await db.refresh(experiment)

    actor_id = UUID("00000000-0000-0000-0000-000000000000")
    await log_audit(db, actor_id, "UPDATE", "Experiment", experiment.id, changes)
    
    return experiment
