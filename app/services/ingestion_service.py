from sqlalchemy.ext.asyncio import AsyncSession
from app.repositories.ticket_repo import TicketRepository
from app.workers.ingestion_worker import process_email_ingestion
from app.core.logging import logger

class IngestionService:
    def __init__(self, db: AsyncSession) -> None:
        self.ticket_repo = TicketRepository(db)

    async def ingest_email(self, payload: dict) -> dict:
        """
        Processes incoming emails:
        1. Checks database for an existing ticket with the same message_id (deduplication).
        2. If duplicate, returns status and skips queueing.
        3. If unique, enqueues process_email_ingestion task to Celery and returns immediately.
        """
        message_id = (payload.get("message_id") or "").strip("<> ")
        if not message_id:
            raise ValueError("Webhook payload must contain a valid message_id")

        # 1. Deduplication validation
        existing_ticket = await self.ticket_repo.get_by_message_id(message_id)
        if existing_ticket:
            logger.info("Deduplication matched: skipping ingestion task", message_id=message_id, ticket_id=str(existing_ticket.id))
            return {
                "status": "duplicate",
                "ticket_id": str(existing_ticket.id),
                "message": "Email already processed (deduplication active)."
            }

        # 2. Dispatch work to background workers
        task = process_email_ingestion.delay(payload)
        logger.info("Enqueued ingestion background worker task", message_id=message_id, task_id=task.id)

        return {
            "status": "enqueued",
            "task_id": task.id,
            "message": "Ingestion job successfully dispatched to background workers."
        }
