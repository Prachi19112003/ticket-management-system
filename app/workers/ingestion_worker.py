import asyncio
import redis.asyncio as aioredis
from datetime import datetime, timezone
from sqlalchemy import select
from app.core.celery_app import celery_app
from app.core.db import AsyncSessionLocal, engine
from app.core.config import settings
from app.core.logging import logger
from app.models.customer import Customer
from app.models.ticket import Ticket
from app.models.ticket_embedding import TicketEmbedding
from app.models.audit_log import AuditLog
from app.repositories.ticket_repo import TicketRepository
from app.repositories.customer_repo import CustomerRepository
from app.utils.html_cleaner import clean_email_body
from app.utils.thread_detector import detect_thread_id
from app.services.priority_service import PriorityService
from app.services.classification_service import ClassificationService
from app.services.draft_service import DraftService
from app.integrations.embedding_client import get_embedding
from app.services.summary_service import ThreadSummaryService

async def _process_email_ingestion_async(payload: dict) -> str:

    # 1. Parse and extract message parameters
    message_id = (payload.get("message_id") or "").strip("<> ")
    subject = (payload.get("subject") or "").strip()
    raw_body = (payload.get("body") or "").strip()
    from_email = (payload.get("from_email") or "").strip()
    from_name = (payload.get("from_name") or "").strip()
    headers = payload.get("headers") or {}
    gmail_thread_id = payload.get("gmail_thread_id")

    if not message_id or not from_email:
        raise ValueError("Invalid payload: message_id and from_email are required properties.")

    # Wrap the entire session lifecycle in try/finally so engine.dispose()
    # always runs inside this coroutine's event loop — before asyncio.run()
    # tears the loop down. Disposing after loop closure causes asyncpg to raise
    # "AttributeError: 'NoneType' object has no attribute 'send'" because the
    # underlying transport is already gone (Windows ProactorEventLoop behaviour).
    try:
        async with AsyncSessionLocal() as db:
            ticket_repo = TicketRepository(db)
            customer_repo = CustomerRepository(db)
            priority_service = PriorityService()
            classification_service = ClassificationService()

            # 2. Customer validation and mapping
            customer = await customer_repo.get_by_email(from_email)
            if not customer:
                customer = Customer(
                    email=from_email,
                    name=from_name if from_name else None,
                    tier="standard"
                )
                customer = await customer_repo.create(customer)
                logger.info("Created new customer profile during ingestion", email=from_email, customer_id=str(customer.id))

            # 3. Thread Grouping
            thread_id = await detect_thread_id(message_id, headers, db, gmail_thread_id)

            # 4. Email signature and markup stripping
            cleaned_body = clean_email_body(raw_body)

            # 5. Measure wait-time bonus (hours elapsed since last thread interaction)
            wait_time_hours = 0.0
            query = select(Ticket).filter(Ticket.thread_id == thread_id).order_by(Ticket.created_at.desc())
            result = await db.execute(query)
            last_ticket = result.scalars().first()
            if last_ticket:
                last_time = last_ticket.created_at.replace(tzinfo=timezone.utc)
                delta = datetime.now(timezone.utc) - last_time
                wait_time_hours = max(0.0, delta.total_seconds() / 3600.0)
                logger.info("Discovered matching thread interaction history", thread_id=thread_id, wait_time_hours=wait_time_hours)

            # 6. Apply rules-based priority scoring
            priority_score = priority_service.calculate_priority(
                subject=subject,
                body=cleaned_body,
                customer_tier=customer.tier,
                wait_time_hours=wait_time_hours
            )

            # 7. Local zero-shot class prediction and confidence mapping
            category, confidence = classification_service.classify_ticket(cleaned_body)

            # 8. Construct and persist Ticket record
            ticket = Ticket(
                thread_id=thread_id,
                message_id=message_id,
                customer_id=customer.id,
                status="classified",
                raw_subject=subject,
                cleaned_body=cleaned_body,
                category=category,
                category_confidence=confidence,
                priority_score=priority_score
            )
            ticket = await ticket_repo.create(ticket)
            logger.info("Persisted new ticket details", ticket_id=str(ticket.id), status=ticket.status)

            # 9. Generate and save embedding record in PostgreSQL vector table
            try:
                vector = get_embedding(cleaned_body)
                embedding_entry = TicketEmbedding(
                    ticket_id=ticket.id,
                    category=category,
                    embedding=vector,
                    source="incoming"
                )
                db.add(embedding_entry)
                logger.info("Saved local embedding vector to PostgreSQL database", ticket_id=str(ticket.id))
            except Exception as e:
                logger.error("Failed to populate vector embedding row during ingestion", error=str(e))

            # 10. Audit log tracking
            audit = AuditLog(
                ticket_id=ticket.id,
                action="classified",
                detail={
                    "category": category,
                    "confidence": confidence,
                    "priority_score": priority_score,
                    "wait_time_hours": wait_time_hours
                }
            )
            db.add(audit)

            # 11. Update running thread summary in Redis
            # Create a fresh Redis client bound to this task's event loop.
            # Using the process-level singleton is unsafe in Celery workers because
            # each asyncio.run() call creates and destroys its own event loop —
            # the singleton would be bound to a dead loop from a prior task.
            redis_client = aioredis.from_url(
                settings.REDIS_URL,
                decode_responses=True,
                socket_timeout=5.0,
                socket_connect_timeout=5.0
            )
            try:
                summary_service = ThreadSummaryService(redis_client=redis_client)
                await summary_service.update_summary(
                    thread_id=thread_id,
                    new_body=f"Customer: {cleaned_body}"
                )
                logger.info("Updated running thread summary in Redis", thread_id=thread_id)
            except Exception as e:
                logger.warning("Failed to update thread summary during ingestion", thread_id=thread_id, error=str(e))
            finally:
                await redis_client.aclose()

            await db.commit()
            logger.info("Ingestion pipeline phase 1 complete (classified)", ticket_id=str(ticket.id))

            # 12. Automatically proceed to draft generation (RAG + LLM + guardrails)
            # DraftService handles its own commit and status transition to "drafted".
            # Failures are isolated — ticket remains at "classified" for manual retry.
            try:
                draft_service = DraftService(db)
                await draft_service.generate_draft(ticket.id)
                logger.info("Draft generated automatically during ingestion", ticket_id=str(ticket.id))
            except Exception as e:
                logger.error(
                    "Automated draft generation failed after classification — "
                    "ticket remains at classified status for manual retry",
                    ticket_id=str(ticket.id),
                    error=str(e)
                )

            return str(ticket.id)

    finally:
        await engine.dispose()


@celery_app.task(name="process_email_ingestion")
def process_email_ingestion(payload: dict) -> str:
    """Celery task processing email parsing, prioritization, and classification."""
    logger.info("Processing asynchronous email ingestion task", message_id=payload.get("message_id"))
    try:
        # Run async logic synchronously inside worker process context.
        # engine.dispose() is called inside _process_email_ingestion_async
        # (in its own finally block) so it runs within the same event loop
        # that created the asyncpg connections — avoiding the cross-loop
        # 'NoneType has no attribute send' error on Windows ProactorEventLoop.
        ticket_id = asyncio.run(_process_email_ingestion_async(payload))
        logger.info("Completed asynchronous email ingestion successfully", ticket_id=ticket_id)
        return ticket_id
    except Exception as e:
        logger.error("Asynchronous email ingestion task failure", error=str(e))
        raise e
