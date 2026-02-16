from typing import List
from uuid import UUID
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from pydantic import BaseModel

from app.db.session import get_db
from app.models.iam import Organization

router = APIRouter()

class OrganizationResponse(BaseModel):
    id: UUID
    name: str

    class Config:
        from_attributes = True

@router.get("/organizations", response_model=List[OrganizationResponse])
async def list_organizations(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Organization))
    return result.scalars().all()
