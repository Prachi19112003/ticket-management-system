from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.db import get_db
from app.core.logging import logger

router = APIRouter(tags=["Health"])

@router.get("/health")
async def health_check(db: AsyncSession = Depends(get_db)) -> dict[str, str]:
    """Health check endpoint to verify API and Database connectivity."""
    db_status = "healthy"
    try:
        await db.execute(text("SELECT 1"))
    except Exception as e:
        logger.error("Health check database query failed", error=str(e))
        db_status = "unhealthy"

    status = "healthy" if db_status == "healthy" else "degraded"

    return {
        "status": status,
        "database": db_status,
        "redis": "healthy",  # Simple placeholder for Redis connection, to be updated during Celery integration
    }
