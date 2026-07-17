from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.db import get_db
from app.core.logging import logger
from app.schemas.webhook import GmailWebhookPayload
from app.services.ingestion_service import IngestionService
from app.core.exceptions import DatabaseException

router = APIRouter(prefix="/webhook", tags=["Webhook"])

@router.post("/gmail", status_code=status.HTTP_200_OK)
async def gmail_webhook(
    payload: GmailWebhookPayload,
    db: AsyncSession = Depends(get_db)
) -> dict:
    """
    Endpoint for receiving Gmail webhook notifications.
    Ingests the email payload, validates deduplication, enqueues background worker job,
    and returns immediately to maintain response time under 200ms.
    """
    logger.info("Received incoming Gmail webhook payload", message_id=payload.message_id)
    try:
        service = IngestionService(db)
        # Convert schema to dict and pass to ingestion service
        result = await service.ingest_email(payload.model_dump())
        return result
    except ValueError as e:
        logger.error("Validation error in webhook handler", error=str(e))
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except DatabaseException as e:
        logger.error("Database connection failure in webhook handler", error=e.message)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Database connection error occurred while validating message."
        )
    except Exception as e:
        logger.critical("Unexpected failure in webhook handler", error=str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected internal error occurred."
        )
