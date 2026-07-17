import uuid
import pytest
from unittest.mock import patch, AsyncMock
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from httpx import AsyncClient, ASGITransport

from app.main import app as fastapi_app
from app.core.db import AsyncSessionLocal, engine
from app.models.customer import Customer
from app.models.ticket import Ticket
from app.models.ticket_embedding import TicketEmbedding
from app.models.audit_log import AuditLog
from app.repositories.customer_repo import CustomerRepository
from app.repositories.ticket_repo import TicketRepository
from app.services.guardrail_service import GuardrailService
import app.core.redis_client as redis_module
from app.core.redis_client import get_redis_client

pytestmark = pytest.mark.asyncio

@pytest.fixture
async def db() -> AsyncSession:
    """Fixture to provide a database session and clean up created entities."""
    async with AsyncSessionLocal() as session:
        yield session
        await session.rollback()
    # Dispose of engine connection pool cleanly to handle event loop lifecycle
    await engine.dispose()

@pytest.fixture
async def redis_client():
    """Fixture to provide Redis client and clean up keys after test."""
    redis_module._redis_client = None
    client = get_redis_client()
    yield client
    await client.aclose()
    redis_module._redis_client = None

async def test_guardrail_flagging_unauthorized_commitment(db: AsyncSession):
    # Setup mock data
    customer_repo = CustomerRepository(db)
    ticket_repo = TicketRepository(db)

    customer = Customer(
        email=f"test-cust-{uuid.uuid4()}@example.com",
        name="Alice Jones",
        tier="standard"
    )
    await customer_repo.create(customer)

    ticket = Ticket(
        thread_id=f"thread-{uuid.uuid4()}",
        message_id=f"msg-{uuid.uuid4()}",
        customer_id=customer.id,
        status="drafted",
        raw_subject="Pricing help",
        cleaned_body="How much does X cost?",
        category="Sales",
        category_confidence=0.9,
        priority_score=60,
        draft_json={
            # Unauthorized commitment: "4 business hours" and "50% refund" not present in body or references
            "draft_reply": "We will get back to you within 4 business hours and issue a 50% refund.",
            "category_confirmation": "Sales",
            "cc_list": [],
            "confidence_score": 0.95
        }
    )
    await ticket_repo.create(ticket)
    await db.commit()

    # Scan draft with guardrails (empty references list)
    service = GuardrailService()
    flags = service.scan_draft(ticket, retrieved_references=[])
    
    assert len(flags) == 3
    flag_types = [f["type"] for f in flags]
    assert "time_commitment" in flag_types
    assert "discount_commitment" in flag_types
    assert "refund_commitment" in flag_types

async def test_get_review_queue(db: AsyncSession):
    # Setup mock data
    customer_repo = CustomerRepository(db)
    ticket_repo = TicketRepository(db)

    customer = Customer(
        email=f"test-cust-{uuid.uuid4()}@example.com",
        name="Review Queue Cust",
        tier="standard"
    )
    await customer_repo.create(customer)

    # Ticket 1: Lower priority
    t1 = Ticket(
        thread_id=f"thread-{uuid.uuid4()}",
        message_id=f"msg-{uuid.uuid4()}",
        customer_id=customer.id,
        status="drafted",
        raw_subject="Low priority subject",
        cleaned_body="Body text...",
        category="General",
        category_confidence=0.8,
        priority_score=10,
        draft_json={
            "draft_reply": "General response",
            "category_confirmation": "General",
            "cc_list": [],
            "confidence_score": 0.9
        }
    )
    await ticket_repo.create(t1)

    # Ticket 2: Higher priority
    t2 = Ticket(
        thread_id=f"thread-{uuid.uuid4()}",
        message_id=f"msg-{uuid.uuid4()}",
        customer_id=customer.id,
        status="drafted",
        raw_subject="High priority subject",
        cleaned_body="Important body text...",
        category="Sales",
        category_confidence=0.99,
        priority_score=95,
        draft_json={
            "draft_reply": "Sales response",
            "category_confirmation": "Sales",
            "cc_list": [],
            "confidence_score": 0.95
        }
    )
    await ticket_repo.create(t2)
    await db.commit()

    # Call endpoint via AsyncClient
    async with AsyncClient(transport=ASGITransport(app=fastapi_app), base_url="http://test") as ac:
        response = await ac.get("/api/v1/review/queue")
        
    assert response.status_code == 200
    data = response.json()
    assert len(data) >= 2
    
    # Assert sorting: high priority ticket should come first
    ticket_ids = [item["ticket_id"] for item in data]
    assert str(t2.id) in ticket_ids
    assert str(t1.id) in ticket_ids
    t2_idx = ticket_ids.index(str(t2.id))
    t1_idx = ticket_ids.index(str(t1.id))
    assert t2_idx < t1_idx  # Higher priority comes first

async def test_post_approve_workflow(db: AsyncSession):
    # Setup mock data
    customer_repo = CustomerRepository(db)
    ticket_repo = TicketRepository(db)

    customer = Customer(
        email=f"test-cust-{uuid.uuid4()}@example.com",
        name="Approve Cust",
        tier="standard"
    )
    await customer_repo.create(customer)

    ticket = Ticket(
        thread_id=f"thread-{uuid.uuid4()}",
        message_id=f"msg-{uuid.uuid4()}",
        customer_id=customer.id,
        status="drafted",
        raw_subject="Approve subject",
        cleaned_body="Body...",
        category="Sales",
        category_confidence=0.9,
        priority_score=50,
        draft_json={
            "draft_reply": "Approved response",
            "category_confirmation": "Sales",
            "cc_list": ["sales-placeholder@example.com"],
            "confidence_score": 0.95
        }
    )
    await ticket_repo.create(ticket)
    await db.commit()

    # Mock send_email on GmailClient
    with patch("app.services.send_service.GmailClient.send_email", new_callable=AsyncMock) as mock_send:
        mock_send.return_value = "msg-gmail-id-123"

        async with AsyncClient(transport=ASGITransport(app=fastapi_app), base_url="http://test") as ac:
            response = await ac.post(
                f"/api/v1/review/{ticket.id}/approve",
                json={"reviewed_by": "reviewer-john"}
            )

        assert response.status_code == 200
        assert response.json()["status"] == "approved_and_sent"
        
        # Verify call arguments
        mock_send.assert_called_once_with(
            to_email=customer.email,
            subject=f"Re: {ticket.raw_subject}",
            body="Approved response",
            cc_list=["sales-placeholder@example.com"]
        )

    # Verify DB updates in a clean session
    async with AsyncSessionLocal() as fresh_db:
        fresh_repo = TicketRepository(fresh_db)
        updated_ticket = await fresh_repo.get_by_id(ticket.id)
        assert updated_ticket.status == "sent"
        assert updated_ticket.reviewed_by == "reviewer-john"

        # Verify Audit Logs
        audit_res = await fresh_db.execute(
            select(AuditLog)
            .filter(AuditLog.ticket_id == ticket.id)
            .order_by(AuditLog.created_at.desc())
        )
        logs = audit_res.scalars().all()
        assert len(logs) >= 2
        actions = [log.action for log in logs]
        assert "reviewed" in actions
        assert "sent" in actions

async def test_post_edit_workflow(db: AsyncSession):
    # Setup mock data
    customer_repo = CustomerRepository(db)
    ticket_repo = TicketRepository(db)

    customer = Customer(
        email=f"test-cust-{uuid.uuid4()}@example.com",
        name="Edit Cust",
        tier="standard"
    )
    await customer_repo.create(customer)

    ticket = Ticket(
        thread_id=f"thread-{uuid.uuid4()}",
        message_id=f"msg-{uuid.uuid4()}",
        customer_id=customer.id,
        status="drafted",
        raw_subject="Edit subject",
        cleaned_body="Body...",
        category="Procurement",
        category_confidence=0.9,
        priority_score=50,
        draft_json={
            "draft_reply": "Original response",
            "category_confirmation": "Procurement",
            "cc_list": ["procurement-placeholder@example.com"],
            "confidence_score": 0.95
        }
    )
    await ticket_repo.create(ticket)
    await db.commit()

    # Mock send_email
    with patch("app.services.send_service.GmailClient.send_email", new_callable=AsyncMock) as mock_send:
        mock_send.return_value = "msg-gmail-id-edit"

        async with AsyncClient(transport=ASGITransport(app=fastapi_app), base_url="http://test") as ac:
            response = await ac.post(
                f"/api/v1/review/{ticket.id}/edit",
                json={
                    "revised_reply": "Manually edited reply text",
                    "reviewed_by": "reviewer-jane"
                }
            )

        assert response.status_code == 200
        assert response.json()["status"] == "approved_and_sent"

    # Verify DB updates in a clean session
    async with AsyncSessionLocal() as fresh_db:
        fresh_repo = TicketRepository(fresh_db)
        updated_ticket = await fresh_repo.get_by_id(ticket.id)
        assert updated_ticket.status == "sent"
        assert updated_ticket.reviewed_by == "reviewer-jane"
        assert updated_ticket.draft_json["draft_reply"] == "Manually edited reply text"

async def test_post_reject_workflow(db: AsyncSession):
    # Setup mock data
    customer_repo = CustomerRepository(db)
    ticket_repo = TicketRepository(db)

    customer = Customer(
        email=f"test-cust-{uuid.uuid4()}@example.com",
        name="Reject Cust",
        tier="standard"
    )
    await customer_repo.create(customer)

    ticket = Ticket(
        thread_id=f"thread-{uuid.uuid4()}",
        message_id=f"msg-{uuid.uuid4()}",
        customer_id=customer.id,
        status="drafted",
        raw_subject="Reject subject",
        cleaned_body="Body...",
        category="General",
        category_confidence=0.9,
        priority_score=50,
        draft_json={
            "draft_reply": "Response...",
            "category_confirmation": "General",
            "cc_list": [],
            "confidence_score": 0.95
        }
    )
    await ticket_repo.create(ticket)
    await db.commit()

    async with AsyncClient(transport=ASGITransport(app=fastapi_app), base_url="http://test") as ac:
        response = await ac.post(
            f"/api/v1/review/{ticket.id}/reject",
            json={"reviewed_by": "reviewer-bob"}
        )

    assert response.status_code == 200
    assert response.json()["status"] == "rejected"

    # Verify DB updates in a clean session
    async with AsyncSessionLocal() as fresh_db:
        fresh_repo = TicketRepository(fresh_db)
        updated_ticket = await fresh_repo.get_by_id(ticket.id)
        assert updated_ticket.status == "rejected"
        assert updated_ticket.reviewed_by == "reviewer-bob"


async def test_post_approve_gmail_failure_workflow(db: AsyncSession):
    # Setup mock data
    customer_repo = CustomerRepository(db)
    ticket_repo = TicketRepository(db)

    customer = Customer(
        email=f"test-cust-{uuid.uuid4()}@example.com",
        name="Failure Cust",
        tier="standard"
    )
    await customer_repo.create(customer)

    ticket = Ticket(
        thread_id=f"thread-{uuid.uuid4()}",
        message_id=f"msg-{uuid.uuid4()}",
        customer_id=customer.id,
        status="drafted",
        raw_subject="Approve failure subject",
        cleaned_body="Body...",
        category="Sales",
        category_confidence=0.9,
        priority_score=50,
        draft_json={
            "draft_reply": "Approved response",
            "category_confirmation": "Sales",
            "cc_list": ["sales-placeholder@example.com"],
            "confidence_score": 0.95
        }
    )
    await ticket_repo.create(ticket)
    await db.commit()

    from app.core.exceptions import GmailException
    # Mock send_email on GmailClient to raise GmailException
    with patch("app.services.send_service.GmailClient.send_email", new_callable=AsyncMock) as mock_send:
        mock_send.side_effect = GmailException("Failed to send email due to simulated server error.")

        async with AsyncClient(transport=ASGITransport(app=fastapi_app), base_url="http://test") as ac:
            response = await ac.post(
                f"/api/v1/review/{ticket.id}/approve",
                json={"reviewed_by": "reviewer-failed"}
            )

        assert response.status_code == 502
        assert "Failed to send approved draft" in response.json()["detail"]

    # Verify DB updates in a clean session: status should remain "approved" (not sent)
    async with AsyncSessionLocal() as fresh_db:
        fresh_repo = TicketRepository(fresh_db)
        updated_ticket = await fresh_repo.get_by_id(ticket.id)
        assert updated_ticket.status == "approved"
        assert updated_ticket.reviewed_by == "reviewer-failed"

        # Verify Audit Logs
        audit_res = await fresh_db.execute(
            select(AuditLog)
            .filter(AuditLog.ticket_id == ticket.id)
            .order_by(AuditLog.created_at.desc())
        )
        logs = audit_res.scalars().all()
        assert len(logs) >= 2
        actions = [log.action for log in logs]
        assert "reviewed" in actions
        assert "send_failed" in actions


async def test_post_approve_writeback_success_workflow(db: AsyncSession):
    # Setup mock data
    customer_repo = CustomerRepository(db)
    ticket_repo = TicketRepository(db)

    customer = Customer(
        email=f"test-cust-{uuid.uuid4()}@example.com",
        name="Writeback Success Cust",
        tier="standard"
    )
    await customer_repo.create(customer)

    ticket = Ticket(
        thread_id=f"thread-{uuid.uuid4()}",
        message_id=f"msg-{uuid.uuid4()}",
        customer_id=customer.id,
        status="drafted",
        raw_subject="Writeback subject",
        cleaned_body="Body...",
        category="Sales",
        category_confidence=0.9,
        priority_score=50,
        draft_json={
            "draft_reply": "This is a clean and minimally edited response.",
            "original_draft_reply": "This is a clean and minimally edited response.",
            "category_confirmation": "Sales",
            "cc_list": ["sales-placeholder@example.com"],
            "confidence_score": 0.95
        }
    )
    await ticket_repo.create(ticket)
    await db.commit()

    # Mock send_email on GmailClient and get_embedding on embedding_client/learning_service
    dummy_embedding = [0.2] * 768
    with patch("app.services.send_service.GmailClient.send_email", new_callable=AsyncMock) as mock_send, \
         patch("app.services.learning_service.get_embedding", return_value=dummy_embedding) as mock_embed:
        mock_send.return_value = "msg-gmail-id-writeback-ok"

        async with AsyncClient(transport=ASGITransport(app=fastapi_app), base_url="http://test") as ac:
            response = await ac.post(
                f"/api/v1/review/{ticket.id}/approve",
                json={"reviewed_by": "reviewer-writeback-success"}
            )

        assert response.status_code == 200
        assert response.json()["status"] == "approved_and_sent"
        mock_embed.assert_called_once_with("This is a clean and minimally edited response.")

    # Verify DB updates in a clean session
    async with AsyncSessionLocal() as fresh_db:
        fresh_repo = TicketRepository(fresh_db)
        updated_ticket = await fresh_repo.get_by_id(ticket.id)
        assert updated_ticket.status == "sent"
        assert updated_ticket.edit_distance_ratio == 1.0

        # Check that TicketEmbedding was written
        emb_res = await fresh_db.execute(
            select(TicketEmbedding).filter(
                TicketEmbedding.ticket_id == ticket.id,
                TicketEmbedding.source == "resolved"
            )
        )
        embeddings = emb_res.scalars().all()
        assert len(embeddings) == 1
        assert embeddings[0].category == "Sales"
        assert embeddings[0].embedding == dummy_embedding

        # Check Audit Logs
        audit_res = await fresh_db.execute(
            select(AuditLog)
            .filter(AuditLog.ticket_id == ticket.id)
            .order_by(AuditLog.created_at.desc())
        )
        logs = audit_res.scalars().all()
        actions = [log.action for log in logs]
        assert "writeback_completed" in actions


async def test_post_approve_writeback_skipped_workflow(db: AsyncSession):
    # Setup mock data
    customer_repo = CustomerRepository(db)
    ticket_repo = TicketRepository(db)

    customer = Customer(
        email=f"test-cust-{uuid.uuid4()}@example.com",
        name="Writeback Skipped Cust",
        tier="standard"
    )
    await customer_repo.create(customer)

    ticket = Ticket(
        thread_id=f"thread-{uuid.uuid4()}",
        message_id=f"msg-{uuid.uuid4()}",
        customer_id=customer.id,
        status="drafted",
        raw_subject="Writeback skipped subject",
        cleaned_body="Body...",
        category="Sales",
        category_confidence=0.9,
        priority_score=50,
        draft_json={
            "draft_reply": "Heavy human edits replaced the entire message text.",
            "original_draft_reply": "Initial LLM response baseline text draft.",
            "category_confirmation": "Sales",
            "cc_list": ["sales-placeholder@example.com"],
            "confidence_score": 0.95
        }
    )
    await ticket_repo.create(ticket)
    await db.commit()

    with patch("app.services.send_service.GmailClient.send_email", new_callable=AsyncMock) as mock_send, \
         patch("app.services.learning_service.get_embedding") as mock_embed:
        mock_send.return_value = "msg-gmail-id-writeback-skip"

        async with AsyncClient(transport=ASGITransport(app=fastapi_app), base_url="http://test") as ac:
            response = await ac.post(
                f"/api/v1/review/{ticket.id}/approve",
                json={"reviewed_by": "reviewer-writeback-skip"}
            )

        assert response.status_code == 200
        assert response.json()["status"] == "approved_and_sent"
        mock_embed.assert_not_called()

    # Verify DB updates in a clean session
    async with AsyncSessionLocal() as fresh_db:
        fresh_repo = TicketRepository(fresh_db)
        updated_ticket = await fresh_repo.get_by_id(ticket.id)
        assert updated_ticket.status == "sent"
        assert updated_ticket.edit_distance_ratio < 0.85

        # Check that NO TicketEmbedding resolved row was written
        emb_res = await fresh_db.execute(
            select(TicketEmbedding).filter(
                TicketEmbedding.ticket_id == ticket.id,
                TicketEmbedding.source == "resolved"
            )
        )
        embeddings = emb_res.scalars().all()
        assert len(embeddings) == 0

        # Check Audit Logs: must contain writeback_skipped
        audit_res = await fresh_db.execute(
            select(AuditLog)
            .filter(AuditLog.ticket_id == ticket.id)
            .order_by(AuditLog.created_at.desc())
        )
        logs = audit_res.scalars().all()
        actions = [log.action for log in logs]
        assert "writeback_skipped" in actions


async def test_post_approve_writeback_embedding_failure_workflow(db: AsyncSession):
    # Setup mock data
    customer_repo = CustomerRepository(db)
    ticket_repo = TicketRepository(db)

    customer = Customer(
        email=f"test-cust-{uuid.uuid4()}@example.com",
        name="Writeback Embed Fail Cust",
        tier="standard"
    )
    await customer_repo.create(customer)

    ticket = Ticket(
        thread_id=f"thread-{uuid.uuid4()}",
        message_id=f"msg-{uuid.uuid4()}",
        customer_id=customer.id,
        status="drafted",
        raw_subject="Writeback embed fail subject",
        cleaned_body="Body...",
        category="Sales",
        category_confidence=0.9,
        priority_score=50,
        draft_json={
            "draft_reply": "Minimally edited response text.",
            "original_draft_reply": "Minimally edited response text.",
            "category_confirmation": "Sales",
            "cc_list": ["sales-placeholder@example.com"],
            "confidence_score": 0.95
        }
    )
    await ticket_repo.create(ticket)
    await db.commit()

    with patch("app.services.send_service.GmailClient.send_email", new_callable=AsyncMock) as mock_send, \
         patch("app.services.learning_service.get_embedding", side_effect=Exception("Simulated Hugging Face timeout!")) as mock_embed:
        mock_send.return_value = "msg-gmail-id-writeback-embed-fail"

        async with AsyncClient(transport=ASGITransport(app=fastapi_app), base_url="http://test") as ac:
            response = await ac.post(
                f"/api/v1/review/{ticket.id}/approve",
                json={"reviewed_by": "reviewer-writeback-embed-fail"}
            )

        # Send response should still be successful 200 (not blocked by learning loop fail)
        assert response.status_code == 200
        assert response.json()["status"] == "approved_and_sent"

    # Verify DB updates in a clean session: status is sent, but learning failed
    async with AsyncSessionLocal() as fresh_db:
        fresh_repo = TicketRepository(fresh_db)
        updated_ticket = await fresh_repo.get_by_id(ticket.id)
        assert updated_ticket.status == "sent"
        assert updated_ticket.edit_distance_ratio == 1.0

        # Check that NO TicketEmbedding resolved row was written (transaction rolled back)
        emb_res = await fresh_db.execute(
            select(TicketEmbedding).filter(
                TicketEmbedding.ticket_id == ticket.id,
                TicketEmbedding.source == "resolved"
            )
        )
        embeddings = emb_res.scalars().all()
        assert len(embeddings) == 0

        # Check Audit Logs: must contain writeback_failed
        audit_res = await fresh_db.execute(
            select(AuditLog)
            .filter(AuditLog.ticket_id == ticket.id)
            .order_by(AuditLog.created_at.desc())
        )
        logs = audit_res.scalars().all()
        actions = [log.action for log in logs]
        assert "writeback_failed" in actions


async def test_guardrail_unauthorized_price_quote(db: AsyncSession):
    # Setup mock data
    customer_repo = CustomerRepository(db)
    ticket_repo = TicketRepository(db)

    customer = Customer(
        email=f"test-cust-price-{uuid.uuid4()}@example.com",
        name="Bob Price",
        tier="standard"
    )
    await customer_repo.create(customer)

    ticket = Ticket(
        thread_id=f"thread-{uuid.uuid4()}",
        message_id=f"msg-{uuid.uuid4()}",
        customer_id=customer.id,
        status="drafted",
        raw_subject="Pricing quote test",
        cleaned_body="What is your pricing?",
        category="Sales",
        category_confidence=0.9,
        priority_score=60,
        draft_json={
            "draft_reply": "our pricing is $400 per user when billed annually, which would total $100,000 for your team",
            "category_confirmation": "Sales",
            "cc_list": [],
            "confidence_score": 0.95
        }
    )
    await ticket_repo.create(ticket)
    await db.commit()

    service = GuardrailService()
    flags = service.scan_draft(ticket, retrieved_references=[])

    # Should flag the pricing mentions
    assert len(flags) > 0
    flag_types = [f["type"] for f in flags]
    assert "unauthorized_price_quote" in flag_types

