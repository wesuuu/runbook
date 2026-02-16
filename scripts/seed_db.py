import asyncio
import uuid
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from app.models.iam import Organization, User
from app.db.base import Base

DATABASE_URL = "postgresql+asyncpg://postgres:postgres@localhost:5432/runbook"

async def seed_db():
    engine = create_async_engine(DATABASE_URL)
    async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    
    async with async_session() as session:
        # Check if org exists
        from sqlalchemy import select
        result = await session.execute(select(Organization).where(Organization.name == "Demo Org"))
        org = result.scalar_one_or_none()
        
        if not org:
            print("Creating Demo Org...")
            org = Organization(name="Demo Org")
            session.add(org)
            await session.commit()
            await session.refresh(org)
        else:
            print(f"Demo Org exists: {org.id}")
        
        # Check if user exists
        result = await session.execute(select(User).where(User.email == "demo@example.com"))
        user = result.scalar_one_or_none()
        
        if not user:
            print("Creating Demo User...")
            user = User(
                email="demo@example.com",
                full_name="Demo User",
                hashed_password="hashed_secret_password"
            )
            session.add(user)
            await session.commit()
        # Check if Mock User exists (for Audit Log)
        result = await session.execute(select(User).where(User.id == uuid.UUID("00000000-0000-0000-0000-000000000000")))
        mock_user = result.scalar_one_or_none()
        
        if not mock_user:
            print("Creating Mock User (0000...)...")
            mock_user = User(
                id=uuid.UUID("00000000-0000-0000-0000-000000000000"),
                email="system@runbook.ai",
                full_name="System Actor",
                hashed_password="system_locked"
            )
            session.add(mock_user)
            await session.commit()
        else:
            print("Mock User exists.")


    await engine.dispose()

if __name__ == "__main__":
    asyncio.run(seed_db())
