from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import sessionmaker

# Database URL (Should match environment variable/alembic.ini)
SQLALCHEMY_DATABASE_URL = "postgresql+asyncpg://postgres:postgres@localhost:5432/runbook"

engine = create_async_engine(
    SQLALCHEMY_DATABASE_URL,
    echo=True, # Set to False in production
)

AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
)

async def get_db():
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()
