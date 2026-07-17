import uuid
import pytest
import json
from unittest.mock import patch, AsyncMock
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import AsyncSessionLocal
from app.models.customer import Customer
from app.models.ticket import Ticket
from app.models.ticket_embedding import TicketEmbedding
from app.models.audit_log import AuditLog
from app.repositories.customer_repo import CustomerRepository
from app.repositories.ticket_repo import TicketRepository
from app.services.draft_service import DraftService
from app.core.redis_client import get_redis_client
from app.core.exceptions import ValidationException

pytestmark = pytest.mark.asyncio

from app.core.db import AsyncSessionLocal, engine

@pytest.fixture
async def db() -> AsyncSession:
    """Fixture to provide a database session and clean up created entities."""
    async with AsyncSessionLocal() as session:
        yield session
        # Roll back any transaction to keep the database clean
        await session.rollback()
    # Dispose of engine connection pool cleanly to handle event loop lifecycle
    await engine.dispose()

import app.core.redis_client

@pytest.fixture
async def redis_client():
    """Fixture to provide Redis client and clean up keys after test."""
    # Reset singleton to bind to the current test's active event loop
    app.core.redis_client._redis_client = None
    client = get_redis_client()
    yield client
    # Clean close
    await client.aclose()
    app.core.redis_client._redis_client = None

async def test_generate_draft_success(db: AsyncSession, redis_client):
    # 1. Setup mock data
    customer_repo = CustomerRepository(db)
    ticket_repo = TicketRepository(db)

    # Clean up Redis first
    test_thread_id = f"test-thread-{uuid.uuid4()}"
    redis_key = f"thread:summary:{test_thread_id}"
    await redis_client.delete(redis_key)

    # Create dummy customer
    customer = Customer(
        email=f"test-customer-{uuid.uuid4()}@example.com",
        name="John Doe",
        tier="platinum"
    )
    await customer_repo.create(customer)

    # Create target ticket
    ticket = Ticket(
        thread_id=test_thread_id,
        message_id=f"msg-{uuid.uuid4()}",
        customer_id=customer.id,
        status="classified",
        raw_subject="Upgrade request",
        cleaned_body="I want to upgrade my billing plan to enterprise.",
        category="Sales",
        category_confidence=0.9,
        priority_score=80
    )
    await ticket_repo.create(ticket)

    # Create a dummy incoming embedding for the target ticket
    # In a real pipeline, the embedding is populated during ingestion.
    # Vector length must be 768.
    dummy_vector = [0.1] * 768
    incoming_embedding = TicketEmbedding(
        ticket_id=ticket.id,
        category="Sales",
        embedding=dummy_vector,
        source="incoming"
    )
    db.add(incoming_embedding)

    # Create a pre-existing resolved ticket to test pgvector retrieval
    resolved_ticket = Ticket(
        thread_id=f"thread-{uuid.uuid4()}",
        message_id=f"msg-{uuid.uuid4()}",
        customer_id=customer.id,
        status="drafted",
        raw_subject="Pricing inquiry",
        cleaned_body="What is the price of the enterprise model?",
        category="Sales",
        category_confidence=0.95,
        priority_score=75,
        draft_json={
            "draft_reply": "Pricing for enterprise starts at $500/month.",
            "category_confirmation": "Sales",
            "cc_list": ["sales-placeholder@example.com"],
            "confidence_score": 0.98
        }
    )
    await ticket_repo.create(resolved_ticket)

    resolved_embedding = TicketEmbedding(
        ticket_id=resolved_ticket.id,
        category="Sales",
        embedding=dummy_vector,
        source="resolved"
    )
    db.add(resolved_embedding)
    await db.commit()

    # Pre-populate thread summary in Redis to verify it's retrieved
    initial_summary = "Customer wants to know about enterprise billing."
    await redis_client.set(redis_key, initial_summary, ex=600)

    # Mock the OpenRouter completion call
    mock_llm_response = {
        "draft_reply": "Hello John Doe, I can assist you with your plan upgrade to enterprise.",
        "category_confirmation": "Sales",
        "cc_list": ["sales-custom@example.com"],
        "confidence_score": 0.95
    }
    
    with patch("app.services.draft_service.generate_completion_json", new_callable=AsyncMock) as mock_complete:
        mock_complete.return_value = json.dumps(mock_llm_response)

        # 2. Run draft generation orchestration
        draft_service = DraftService(db)
        result = await draft_service.generate_draft(ticket.id)

        # 3. Assertions
        assert result is not None
        assert result["category_confirmation"] == "Sales"
        assert result["confidence_score"] == 0.95
        assert "Hello John Doe" in result["draft_reply"]
        
        # CC list must exactly match CC_MAPPING for the category and ignore any LLM output custom CCs
        assert result["cc_list"] == ["sales-placeholder@example.com"]

        # Assert Ticket was updated in the DB
        updated_ticket = await ticket_repo.get_by_id(ticket.id)
        assert updated_ticket.status == "drafted"
        assert updated_ticket.draft_json == result

        # Assert AuditLog entry was written
        audit_query = select(AuditLog).filter(AuditLog.ticket_id == ticket.id)
        audit_res = await db.execute(audit_query)
        audit_entry = audit_res.scalars().first()
        assert audit_entry is not None
        assert audit_entry.action == "drafted"
        assert audit_entry.detail["category"] == "Sales"
        assert audit_entry.detail["retrieved_references_count"] >= 1

        # Clean up Redis
        await redis_client.delete(redis_key)


async def test_generate_draft_fallback_on_invalid_json(db: AsyncSession, redis_client):
    # Setup mock data
    customer_repo = CustomerRepository(db)
    ticket_repo = TicketRepository(db)

    test_thread_id = f"test-thread-{uuid.uuid4()}"
    redis_key = f"thread:summary:{test_thread_id}"
    await redis_client.delete(redis_key)

    customer = Customer(
        email=f"test-customer-{uuid.uuid4()}@example.com",
        name="Jane Smith",
        tier="standard"
    )
    await customer_repo.create(customer)

    ticket = Ticket(
        thread_id=test_thread_id,
        message_id=f"msg-{uuid.uuid4()}",
        customer_id=customer.id,
        status="classified",
        raw_subject="Help request",
        cleaned_body="My account login is failing.",
        category="General",
        category_confidence=0.8,
        priority_score=50
    )
    await ticket_repo.create(ticket)
    await db.commit()

    # Mock the LLM to return malformed JSON to trigger ValidationException
    with patch("app.services.draft_service.generate_completion_json", new_callable=AsyncMock) as mock_complete:
        mock_complete.return_value = "{ malformed json "

        draft_service = DraftService(db)
        result = await draft_service.generate_draft(ticket.id)

        # Assertions
        assert result is not None
        assert "Jane Smith" in result["draft_reply"]
        assert "thank you for contacting us" in result["draft_reply"].lower()
        assert result["category_confirmation"] == "General"
        assert result["confidence_score"] == 0.0
        assert result["cc_list"] == [] # CC list for General is empty

        # Assert Ticket was updated in the DB with fallback draft
        updated_ticket = await ticket_repo.get_by_id(ticket.id)
        assert updated_ticket.status == "drafted"
        assert updated_ticket.draft_json == result

        # Assert AuditLog entry was written
        audit_query = select(AuditLog).filter(AuditLog.ticket_id == ticket.id)
        audit_res = await db.execute(audit_query)
        audit_entry = audit_res.scalars().first()
        assert audit_entry is not None
        assert audit_entry.action == "drafted"
        assert audit_entry.detail["confidence"] == 0.0
