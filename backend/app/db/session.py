from sqlalchemy.ext.asyncio import (AsyncSession, async_sessionmaker,
                                    create_async_engine)

from app.core.config import settings

engine = create_async_engine(
    settings.database_url,
    echo=settings.debug,
    # Detect connections killed while idle (e.g. by pgbouncer / postgres
    # idle_in_transaction_session_timeout) before SQLAlchemy hands them out.
    pool_pre_ping=True,
    # Force-recycle conns older than 30 min so we never reuse one that
    # outlived a server-side idle timeout we don't control.
    pool_recycle=1800,
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
