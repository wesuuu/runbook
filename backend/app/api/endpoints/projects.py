from typing import List, Optional
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from app.db.session import get_db
from app.models.science import Project
from app.schemas.project import ProjectCreate, ProjectUpdate, ProjectResponse
from app.services.audit import log_audit

router = APIRouter()

# TODO: Replace with current user from OAuth/Auth dependency
MOCK_USER_ID = UUID("00000000-0000-0000-0000-000000000000") 

@router.post("/", response_model=ProjectResponse)
async def create_project(project: ProjectCreate, db: AsyncSession = Depends(get_db)):
    db_project = Project(**project.model_dump())
    db.add(db_project)
    await db.flush() # Flush to get ID for audit log

    # Audit the creation
    await log_audit(
        db,
        actor_id=MOCK_USER_ID,
        action="CREATE",
        entity_type="Project",
        entity_id=db_project.id,
        changes=project.model_dump()
    )
    
    await db.commit()
    await db.refresh(db_project)
    return db_project

@router.get("/", response_model=List[ProjectResponse])
async def list_projects(skip: int = 0, limit: int = 100, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Project).offset(skip).limit(limit))
    return result.scalars().all()

@router.get("/{project_id}", response_model=ProjectResponse)
async def get_project(project_id: UUID, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Project).where(Project.id == project_id))
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    return project

@router.put("/{project_id}", response_model=ProjectResponse)
async def update_project(project_id: UUID, update_data: ProjectUpdate, db: AsyncSession = Depends(get_db)):
    # Fetch existing
    result = await db.execute(select(Project).where(Project.id == project_id))
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    # Detect changes
    changes = update_data.model_dump(exclude_unset=True)
    if not changes:
        return project # No changes

    for key, value in changes.items():
        setattr(project, key, value)
    
    await log_audit(
        db,
        actor_id=MOCK_USER_ID,
        action="UPDATE",
        entity_type="Project",
        entity_id=project.id,
        changes=changes
    )

    await db.commit()
    await db.refresh(project)
    return project

@router.delete("/{project_id}")
async def delete_project(project_id: UUID, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Project).where(Project.id == project_id))
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    
    await log_audit(
        db,
        actor_id=MOCK_USER_ID,
        action="DELETE",
        entity_type="Project",
        entity_id=project.id,
        changes={"name": project.name} # Log name for context
    )

    await db.delete(project)
    await db.commit()
    return {"ok": True}
