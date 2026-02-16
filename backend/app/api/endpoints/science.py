from typing import List, Optional
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.orm import selectinload

from app.db.session import get_db
from app.models.science import UnitOpDefinition, Protocol, Experiment
from app.schemas.science import (
    UnitOpDefinitionResponse,
    ProtocolCreate, ProtocolUpdate, ProtocolResponse,
    ExperimentCreate, ExperimentUpdate, ExperimentResponse
)
from app.services.audit import log_audit

router = APIRouter()

# --- UnitOps ---
@router.get("/unit-ops", response_model=List[UnitOpDefinitionResponse])
async def list_unit_ops(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(UnitOpDefinition))
    return result.scalars().all()

# --- Protocols ---
@router.post("/protocols", response_model=ProtocolResponse)
async def create_protocol(protocol: ProtocolCreate, db: AsyncSession = Depends(get_db)):
    # Verify Project Exists
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
    await db.refresh(new_protocol)
    
    # Audit Log
    # Mock User ID for now
    actor_id = UUID("00000000-0000-0000-0000-000000000000") 
    await log_audit(db, actor_id, "CREATE", "Protocol", new_protocol.id, {"name": protocol.name})
    
    return new_protocol

@router.get("/protocols/{protocol_id}", response_model=ProtocolResponse)
async def get_protocol(protocol_id: UUID, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Protocol).where(Protocol.id == protocol_id))
    protocol = result.scalar_one_or_none()
    if not protocol:
        raise HTTPException(status_code=404, detail="Protocol not found")
    return protocol

@router.get("/projects/{project_id}/protocols", response_model=List[ProtocolResponse])
async def list_project_protocols(project_id: UUID, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Protocol).where(Protocol.project_id == project_id))
    return result.scalars().all()

@router.put("/protocols/{protocol_id}", response_model=ProtocolResponse)
async def update_protocol(protocol_id: UUID, update_data: ProtocolUpdate, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Protocol).where(Protocol.id == protocol_id))
    protocol = result.scalar_one_or_none()
    if not protocol:
        raise HTTPException(status_code=404, detail="Protocol not found")
    
    changes = update_data.model_dump(exclude_unset=True)
    for key, value in changes.items():
        setattr(protocol, key, value)
    
    await db.commit()
    await db.refresh(protocol)

    # Audit Log
    actor_id = UUID("00000000-0000-0000-0000-000000000000")
    await log_audit(db, actor_id, "UPDATE", "Protocol", protocol.id, changes)
    
    return protocol

# --- Experiments ---
@router.post("/experiments", response_model=ExperimentResponse)
async def create_experiment(experiment: ExperimentCreate, db: AsyncSession = Depends(get_db)):
    # Verify Project Exists
    from app.models.science import Project
    result = await db.execute(select(Project).where(Project.id == experiment.project_id))
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    # If protocol_id provided, copy the graph
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

    # Audit Log
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

    # Audit Log
    actor_id = UUID("00000000-0000-0000-0000-000000000000")
    await log_audit(db, actor_id, "UPDATE", "Experiment", experiment.id, changes)
    
    return experiment
