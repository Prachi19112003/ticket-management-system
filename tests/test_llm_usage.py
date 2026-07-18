import uuid
import pytest
import json
from unittest.mock import patch, AsyncMock
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import AsyncSessionLocal, engine
from app.models.customer import Customer
from app.models.ticket import Ticket
from app.models.llm_usage_log import LLMUsageLog
from app.repositories.llm_usage_repo import LLMUsageRepository
from app.services.draft_service import DraftService

pytestmark = pytest.mark.asyncio


@pytest.fixture
async def db() -> AsyncSession:
    """Provide clean database session and clean up connections."""
    async with AsyncSessionLocal() as session:
        yield session
        await session.rollback()
    await engine.dispose()


async def test_llm_usage_logging_end_to_end(db: AsyncSession):
    # 1. Setup mock data
    customer = Customer(
        email="test-usage-customer@example.com",
        name="Alice Tester",
        tier="standard"
    )
    db.add(customer)
    await db.commit()
    await db.refresh(customer)

    ticket = Ticket(
        thread_id="test-usage-thread",
        message_id="msg-usage-1",
        customer_id=customer.id,
        status="classified",
        raw_subject="Token tracking test",
        cleaned_body="Track my token usage please.",
        category="General",
        category_confidence=0.9,
        priority_score=50
    )
    db.add(ticket)
    await db.commit()
    await db.refresh(ticket)

    # 2. Mock LLM calls for draft_service and summary_service
    mock_response_draft = (
        json.dumps({
            "draft_reply": "Dear Alice, this is a draft reply.",
            "category_confirmation": "General",
            "cc_list": [],
            "confidence_score": 0.99
        }),
        {"prompt_tokens": 120, "completion_tokens": 80, "total_tokens": 200}
    )
    mock_response_summary = (
        json.dumps({
            "summary": "The customer requested tracking their token usage."
        }),
        {"prompt_tokens": 50, "completion_tokens": 20, "total_tokens": 70}
    )

    with patch("app.services.draft_service.generate_completion_json", new_callable=AsyncMock) as mock_draft_call, \
         patch("app.services.summary_service.generate_completion_json", new_callable=AsyncMock) as mock_summary_call:
        
        mock_draft_call.return_value = mock_response_draft
        mock_summary_call.return_value = mock_response_summary

        # 3. Generate draft (this invokes draft generation and summary updates)
        draft_service = DraftService(db)
        result = await draft_service.generate_draft(ticket.id)

        assert result is not None

        # 4. Verify log entries in DB
        stmt = select(LLMUsageLog).order_by(LLMUsageLog.created_at.asc())
        query_res = await db.execute(stmt)
        logs = query_res.scalars().all()

        # There should be exactly 2 logs: 1 for draft_generation, 1 for thread_summary
        assert len(logs) == 2

        draft_log = [l for l in logs if l.call_type == "draft_generation"][0]
        summary_log = [l for l in logs if l.call_type == "thread_summary"][0]

        assert draft_log.ticket_id == ticket.id
        assert draft_log.call_type == "draft_generation"
        assert draft_log.input_tokens == 120
        assert draft_log.output_tokens == 80
        assert draft_log.total_tokens == 200

        assert summary_log.ticket_id == ticket.id
        assert summary_log.call_type == "thread_summary"
        assert summary_log.input_tokens == 50
        assert summary_log.output_tokens == 20
        assert summary_log.total_tokens == 70

        # Test querying totals via repository
        usage_repo = LLMUsageRepository(db)
        ticket_totals = await usage_repo.get_total_by_ticket(ticket.id)
        assert ticket_totals["input_tokens"] == 170
        assert ticket_totals["output_tokens"] == 100
        assert ticket_totals["total_tokens"] == 270

        overall_totals = await usage_repo.get_total_overall()
        assert overall_totals["total_tokens"] == 270

        by_day = await usage_repo.get_total_by_day()
        assert len(by_day) == 1
        assert by_day[0]["total_tokens"] == 270
