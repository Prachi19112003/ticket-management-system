import os
import asyncio
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from alembic.config import Config
from alembic import command

# 1. Override the database URL to point to ticket_db_test BEFORE importing any app modules.
# This ensures Pydantic Settings and the SQLAlchemy engine load the test database.
TEST_DB_URL = "postgresql+asyncpg://postgres:postgres@localhost:5432/ticket_db_test"
os.environ["DATABASE_URL"] = TEST_DB_URL


async def ensure_test_db_exists():
    """Connect to default database and ensure the test database exists."""
    postgres_db_url = "postgresql+asyncpg://postgres:postgres@localhost:5432/postgres"
    engine = create_async_engine(postgres_db_url, isolation_level="AUTOCOMMIT")
    
    async with engine.connect() as conn:
        result = await conn.execute(
            text("SELECT 1 FROM pg_database WHERE datname = 'ticket_db_test'")
        )
        exists = result.scalar()
        if not exists:
            print("\n[conftest] Creating database ticket_db_test...")
            await conn.execute(text("CREATE DATABASE ticket_db_test"))
        else:
            print("\n[conftest] ticket_db_test already exists.")
            
    await engine.dispose()


def run_migrations():
    """Run Alembic migrations programmatically on the test database."""
    print("[conftest] Running Alembic migrations on ticket_db_test...")
    alembic_cfg = Config("alembic.ini")
    command.upgrade(alembic_cfg, "head")
    print("[conftest] Migrations completed.")


def pytest_sessionstart(session):
    """
    pytest hook run at the beginning of the test session.
    Sets up the test database and runs migrations.
    """
    # Run database existence check synchronously inside event loop
    asyncio.run(ensure_test_db_exists())
    # Run migrations
    run_migrations()


@pytest.fixture(autouse=True)
async def clean_db():
    """
    Autouse fixture that truncates all application tables before each test runs.
    Ensures complete database isolation and prevents test data pollution.
    """
    from app.core.db import AsyncSessionLocal
    
    async with AsyncSessionLocal() as session:
        # Query all user tables in the public schema, excluding alembic metadata
        result = await session.execute(
            text("SELECT tablename FROM pg_tables WHERE schemaname = 'public' AND tablename != 'alembic_version'")
        )
        tables = [row[0] for row in result.fetchall()]
        if tables:
            quoted_tables = [f'"{table}"' for table in tables]
            truncate_stmt = f"TRUNCATE TABLE {', '.join(quoted_tables)} RESTART IDENTITY CASCADE;"
            await session.execute(text(truncate_stmt))
            await session.commit()
