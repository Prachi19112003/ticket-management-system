import pytest
from unittest.mock import patch, MagicMock
from httpx import AsyncClient, ASGITransport

from app.main import app as fastapi_app
from app.core.db import engine
import app.core.redis_client as redis_module
from app.core.redis_client import get_redis_client

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


async def test_webhook_missing_required_field_returns_422():
    """
    Regression test for get_db() exception swallowing:
    A webhook payload missing a Pydantic-required field must return HTTP 422
    (Unprocessable Entity) with field-level error detail — NOT HTTP 500
    caused by get_db() wrapping RequestValidationError as DatabaseException.
    """
    # Omit the required 'subject' field to trigger FastAPI RequestValidationError
    incomplete_payload = {
        "message_id": "test-msg-id-missing-subject",
        "body": "Some email body text.",
        "from_email": "sender@example.com"
        # 'subject' is intentionally missing
    }

    async with AsyncClient(transport=ASGITransport(app=fastapi_app), base_url="http://test") as ac:
        response = await ac.post("/api/v1/webhook/gmail", json=incomplete_payload)

    assert response.status_code == 422, (
        f"Expected 422 from missing required field, got {response.status_code}. "
        f"Response body: {response.text}"
    )

    detail = response.json().get("detail", [])
    assert isinstance(detail, list), f"Expected list of validation errors, got: {type(detail)}"
    field_paths = [".".join(str(loc) for loc in err.get("loc", [])) for err in detail]
    assert any("subject" in path for path in field_paths), (
        f"Expected 'subject' in validation error locations, got: {field_paths}"
    )


async def test_webhook_missing_from_email_returns_422():
    """
    Confirms omitting 'from_email' (EmailStr field) also returns 422, not 500,
    ensuring the fix covers all required field violations.
    """
    incomplete_payload = {
        "message_id": "test-msg-id-missing-email",
        "subject": "Test subject",
        "body": "Some email body text."
        # 'from_email' is intentionally missing
    }

    async with AsyncClient(transport=ASGITransport(app=fastapi_app), base_url="http://test") as ac:
        response = await ac.post("/api/v1/webhook/gmail", json=incomplete_payload)

    assert response.status_code == 422, (
        f"Expected 422 from missing required field, got {response.status_code}. "
        f"Response body: {response.text}"
    )

    detail = response.json().get("detail", [])
    assert isinstance(detail, list)
    field_paths = [".".join(str(loc) for loc in err.get("loc", [])) for err in detail]
    assert any("from_email" in path for path in field_paths), (
        f"Expected 'from_email' in validation error locations, got: {field_paths}"
    )


async def test_webhook_valid_payload_does_not_return_422():
    """
    Sanity check: a structurally complete payload is not rejected by Pydantic
    validation. The Celery task is mocked so no actual worker queue is needed.
    """
    valid_payload = {
        "message_id": "test-msg-id-valid",
        "subject": "Test subject",
        "body": "Some email body text.",
        "from_email": "sender@example.com"
    }

    mock_task_result = MagicMock()
    mock_task_result.id = "mock-celery-task-id"

    with patch("app.services.ingestion_service.process_email_ingestion") as mock_task:
        mock_task.delay.return_value = mock_task_result
        async with AsyncClient(transport=ASGITransport(app=fastapi_app), base_url="http://test") as ac:
            response = await ac.post("/api/v1/webhook/gmail", json=valid_payload)

    assert response.status_code != 422, (
        f"A valid payload must not return 422. Got {response.status_code}: {response.text}"
    )
