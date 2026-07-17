from contextlib import asynccontextmanager
from typing import AsyncGenerator
from fastapi import FastAPI
from sqlalchemy import text
from app.core.config import settings
from app.core.db import engine
from app.core.logging import logger
from app.routes.health_routes import router as health_router

@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    # Startup: test database connection and pre-load ML models
    logger.info("Starting up Ticket Management System", env=settings.ENV, debug=settings.DEBUG)
    try:
        # Pre-load local embedding model
        from app.integrations.embedding_client import get_model
        get_model()
        
        # Pre-initialize classification prototypes
        from app.services.classification_service import ClassificationService
        classifier = ClassificationService()
        classifier.initialize_prototypes()
        
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        logger.info("Successfully connected to the database during startup")
    except Exception as e:
        logger.critical("Database connection failed during startup", error=str(e))
        # Do not crash in local environment to allow Docker containers to initialize and migrations to run
        if settings.ENV != "local":
            raise e

    yield

    # Shutdown: clean up db engine resources
    logger.info("Shutting down Ticket Management System")
    await engine.dispose()
    logger.info("Database connection pool disposed")

def create_app() -> FastAPI:
    app = FastAPI(
        title="Ticket Management System API",
        version="1.0.0",
        lifespan=lifespan,
    )

    # Register routers
    from app.routes.webhook_routes import router as webhook_router
    from app.routes.review_routes import router as review_router
    app.include_router(health_router, prefix="/api/v1")
    app.include_router(webhook_router, prefix="/api/v1")
    app.include_router(review_router, prefix="/api/v1")

    return app

app = create_app()
