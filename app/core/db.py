from collections.abc import AsyncGenerator
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.exc import SQLAlchemyError
from app.core.config import settings
from app.core.exceptions import DatabaseException
from app.core.logging import logger

# Initialize async engine
try:
    engine = create_async_engine(
        settings.DATABASE_URL,
        echo=False,
        future=True,
        pool_pre_ping=True,       # Recycle dead connections before use
        pool_size=5,              # Persistent connections kept in pool
        max_overflow=10,          # Extra connections allowed under burst load
        pool_timeout=10,          # Seconds to wait for a free connection before raising
        pool_recycle=1800,        # Recycle connections older than 30 min (avoids server-side timeouts)
    )
except Exception as e:
    logger.critical("Failed to create SQLAlchemy engine", error=str(e))
    raise DatabaseException("Failed to initialize database engine", details={"original_error": str(e)})

# Initialize session maker
AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
)

# Declarative base for SQLAlchemy models (Modern 2.0 Style)
class Base(DeclarativeBase):
    pass

async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Dependency generator for database sessions."""
    async with AsyncSessionLocal() as session:
        try:
            yield session
        except SQLAlchemyError as e:
            await session.rollback()
            logger.error("Database session error occurred, rolled back transaction", error=str(e))
            raise DatabaseException("Database transaction failed", details={"original_error": str(e)})
