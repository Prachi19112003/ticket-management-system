import uuid
import pytest
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import AsyncSession
from app.main import app
from app.models.customer import Customer
from app.models.ticket import Ticket
from app.models.llm_usage_log import LLMUsageLog
from app.core.db import AsyncSessionLocal, engine

pytestmark = pytest.mark.asyncio


@pytest.fixture
async def db() -> AsyncSession:
    """Fixture to provide a database session and clean up connections."""
    async with AsyncSessionLocal() as session:
        yield session
        await session.rollback()
    await engine.dispose()


async def test_dashboard_stats_endpoint(db: AsyncSession):
    # 1. Setup mock data
    customer = Customer(
        email="test-dashboard-customer@example.com",
        name="Charlie Test",
        tier="standard"
    )
    db.add(customer)
    await db.commit()
    await db.refresh(customer)

    ticket1 = Ticket(
        thread_id="thread-dashboard-1",
        message_id="msg-dashboard-1",
        customer_id=customer.id,
        status="drafted",
        raw_subject="Stats Test 1",
        cleaned_body="Body 1",
        category="Sales",
        category_confidence=0.9,
        priority_score=60
    )
    ticket2 = Ticket(
        thread_id="thread-dashboard-2",
        message_id="msg-dashboard-2",
        customer_id=customer.id,
        status="approved",
        raw_subject="Stats Test 2",
        cleaned_body="Body 2",
        category="Procurement",
        category_confidence=0.8,
        priority_score=80
    )
    db.add(ticket1)
    db.add(ticket2)
    await db.commit()
    await db.refresh(ticket1)
    await db.refresh(ticket2)

    log1 = LLMUsageLog(
        ticket_id=ticket1.id,
        call_type="draft_generation",
        model="anthropic/claude-sonnet-4.5",
        input_tokens=100,
        output_tokens=50,
        total_tokens=150
    )
    log2 = LLMUsageLog(
        ticket_id=ticket1.id,
        call_type="thread_summary",
        model="anthropic/claude-sonnet-4.5",
        input_tokens=50,
        output_tokens=20,
        total_tokens=70
    )
    db.add(log1)
    db.add(log2)
    await db.commit()

    # 2. Call stats endpoint
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        response = await ac.get("/api/v1/dashboard/stats")
    
    assert response.status_code == 200
    data = response.json()
    assert "tickets_by_status" in data
    assert data["tickets_by_status"]["drafted"] == 1
    assert data["tickets_by_status"]["approved"] == 1
    assert data["tickets_by_category"]["Sales"] == 1
    assert data["tickets_by_category"]["Procurement"] == 1
    assert data["tokens_used"]["all_time"] == 220
    assert data["average_tokens_per_draft"] == 150.0


async def test_dashboard_tickets_list_endpoint(db: AsyncSession):
    # Setup mock customer and ticket
    customer = Customer(
        email="test-dashboard-list@example.com",
        name="Charlie List",
        tier="standard"
    )
    db.add(customer)
    await db.commit()
    await db.refresh(customer)

    ticket = Ticket(
        thread_id="thread-list-1",
        message_id="msg-list-1",
        customer_id=customer.id,
        status="drafted",
        raw_subject="List Subject",
        cleaned_body="List Body",
        category="General",
        category_confidence=0.9,
        priority_score=75
    )
    db.add(ticket)
    await db.commit()
    await db.refresh(ticket)

    # Call /dashboard/tickets
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        response = await ac.get("/api/v1/dashboard/tickets")
    
    assert response.status_code == 200
    tickets = response.json()
    assert len(tickets) >= 1
    assert tickets[0]["ticket_id"] == str(ticket.id)
    assert tickets[0]["status"] == "drafted"
    assert tickets[0]["total_tokens"] == 0

    # Call with filtering
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        response_filtered = await ac.get("/api/v1/dashboard/tickets?status=approved")
    assert response_filtered.status_code == 200
    assert len(response_filtered.json()) == 0


async def test_dashboard_ticket_detail_endpoint(db: AsyncSession):
    # Setup mock data
    customer = Customer(
        email="test-dashboard-detail@example.com",
        name="Charlie Detail",
        tier="standard"
    )
    db.add(customer)
    await db.commit()
    await db.refresh(customer)

    ticket = Ticket(
        thread_id="thread-detail-1",
        message_id="msg-detail-1",
        customer_id=customer.id,
        status="drafted",
        raw_subject="Detail Subject",
        cleaned_body="Detail Body",
        category="General",
        category_confidence=0.9,
        priority_score=75
    )
    db.add(ticket)
    await db.commit()
    await db.refresh(ticket)

    # Call /dashboard/tickets/{id}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        response = await ac.get(f"/api/v1/dashboard/tickets/{ticket.id}")
    
    assert response.status_code == 200
    data = response.json()
    assert data["ticket_id"] == str(ticket.id)
    assert data["status"] == "drafted"
    assert "llm_usage_logs" in data
    assert len(data["llm_usage_logs"]) == 0

    # Call with invalid ID
    fake_id = uuid.uuid4()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        response_fake = await ac.get(f"/api/v1/dashboard/tickets/{fake_id}")
    assert response_fake.status_code == 404
