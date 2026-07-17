"""
Integration tests for the ingestion worker's payload parsing logic.
Focuses on robustness against None values in optional payload fields.
"""
import uuid
import pytest
from unittest.mock import patch, AsyncMock, MagicMock
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import AsyncSessionLocal, engine
import app.core.redis_client as redis_module
from app.core.redis_client import get_redis_client
from app.workers.ingestion_worker import _process_email_ingestion_async
from app.repositories.ticket_repo import TicketRepository
from app.repositories.customer_repo import CustomerRepository

pytestmark = pytest.mark.asyncio


@pytest.fixture(autouse=True)
async def redis_client():
    """Reset the Redis singleton per-test to bind to the active event loop."""
    redis_module._redis_client = None
    client = get_redis_client()
    yield client
    await client.aclose()
    redis_module._redis_client = None


@pytest.fixture(autouse=True)
async def dispose_engine():
    """Dispose engine connection pool cleanly after each test."""
    yield
    await engine.dispose()


def _make_patched_worker(extra_patches=()):
    """
    Context manager stack that patches all embedding and summary calls so that
    ingestion tests run without real model inference or Redis summary writes.

    Patches applied:
    - app.integrations.embedding_client.get_embedding  (covers classifier + worker)
    - app.services.classification_service.ClassificationService.initialize_prototypes
    - app.workers.ingestion_worker.ThreadSummaryService
    """
    from contextlib import ExitStack
    import app.integrations.embedding_client as emb_mod

    dummy_vector = [0.1] * 768

    stack = ExitStack()

    # Patch get_embedding at its definition point — covers all callers
    stack.enter_context(
        patch.object(emb_mod, "get_embedding", return_value=dummy_vector)
    )

    # Patch initialize_prototypes so ClassificationService skips model warm-up
    from app.services.classification_service import ClassificationService
    stack.enter_context(
        patch.object(ClassificationService, "initialize_prototypes", return_value=None)
    )
    # Mark as already initialized so classify_ticket doesn't call initialize_prototypes
    stack.enter_context(
        patch.object(ClassificationService, "initialized", new=True, create=True)
    )
    # Patch classify_ticket itself to return a deterministic result
    stack.enter_context(
        patch.object(ClassificationService, "classify_ticket", return_value=("General", 0.9))
    )

    # Patch ThreadSummaryService so no Redis summary write occurs
    async def _async_noop(*args, **kwargs):
        return "mocked summary"

    mock_summary = MagicMock()
    mock_summary.update_summary = _async_noop
    stack.enter_context(
        patch("app.workers.ingestion_worker.ThreadSummaryService", return_value=mock_summary)
    )

    for p in extra_patches:
        stack.enter_context(p)

    return stack


async def test_ingestion_with_from_name_none_succeeds():
    """
    Regression test: payload["from_name"] explicitly set to None (not missing)
    must not crash with AttributeError: 'NoneType' object has no attribute 'strip'.

    Prior to the fix, payload.get("from_name", "").strip() would crash because
    dict.get()'s default only applies when the key is absent, not when the value
    is explicitly None. The fix uses (payload.get("from_name") or "").strip().
    """
    unique_msg_id = f"<test-from-name-none-{uuid.uuid4()}@example.com>"
    payload = {
        "message_id": unique_msg_id,
        "subject": "Test subject for None from_name",
        "body": "Hello, I have a question about pricing.",
        "from_email": f"test-none-name-{uuid.uuid4()}@example.com",
        "from_name": None,   # Explicitly None — the bug trigger
        "headers": {},
        "gmail_thread_id": None
    }

    with _make_patched_worker():
        ticket_id_str = await _process_email_ingestion_async(payload)

    assert ticket_id_str is not None
    assert isinstance(ticket_id_str, str)

    # Verify the ticket was actually persisted correctly
    async with AsyncSessionLocal() as db:
        ticket_repo = TicketRepository(db)
        customer_repo = CustomerRepository(db)

        ticket = await ticket_repo.get_by_id(uuid.UUID(ticket_id_str))
        assert ticket is not None, "Ticket should have been persisted to the database"
        assert ticket.status == "drafted"
        assert ticket.raw_subject == "Test subject for None from_name"

        # Customer should have been auto-created; name should be None or "" (not crash)
        customer = await customer_repo.get_by_id(ticket.customer_id)
        assert customer is not None
        assert customer.name is None or customer.name == ""


async def test_ingestion_with_all_optional_fields_none_succeeds():
    """
    Robustness test: all optional fields (from_name, headers, gmail_thread_id)
    set to None simultaneously must not crash anywhere in the parsing chain.
    Also covers subject=None and body=None being safely coerced to "".
    """
    unique_msg_id = f"<test-all-none-{uuid.uuid4()}@example.com>"
    payload = {
        "message_id": unique_msg_id,
        "subject": None,          # Guards subject None path
        "body": None,             # Guards body None path
        "from_email": f"test-all-none-{uuid.uuid4()}@example.com",
        "from_name": None,
        "headers": None,          # Explicit None for headers dict
        "gmail_thread_id": None
    }

    with _make_patched_worker():
        ticket_id_str = await _process_email_ingestion_async(payload)

    assert ticket_id_str is not None

    async with AsyncSessionLocal() as db:
        ticket_repo = TicketRepository(db)
        ticket = await ticket_repo.get_by_id(uuid.UUID(ticket_id_str))
        assert ticket is not None
        assert ticket.status == "drafted"
