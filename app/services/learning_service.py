import uuid
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.ticket import Ticket
from app.models.ticket_embedding import TicketEmbedding
from app.models.audit_log import AuditLog
from app.integrations.embedding_client import get_embedding
from app.core.config import settings
from app.core.logging import logger

class LearningService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def writeback_resolved_reply(self, ticket_id: uuid.UUID, ratio: float) -> None:
        """
        Executes the learning loop writeback logic.
        If similarity ratio >= threshold: generates a new embedding for final sent text and writes to ticket_embeddings.
        If similarity ratio < threshold: skips embedding insertion and writes a writeback_skipped audit log.
        Stores the similarity ratio on the ticket row in all cases.
        """
        logger.info("Executing resolve learning loop", ticket_id=str(ticket_id), similarity_ratio=ratio)
        
        try:
            # Fetch the ticket
            result = await self.db.execute(
                select(Ticket).filter(Ticket.id == ticket_id)
            )
            ticket = result.scalars().first()
            if not ticket:
                logger.error("Ticket not found for learning writeback", ticket_id=str(ticket_id))
                return
            
            # Update edit distance ratio on ticket
            ticket.edit_distance_ratio = ratio
            self.db.add(ticket)
            
            threshold = settings.EDIT_DISTANCE_WRITEBACK_THRESHOLD
            draft_json = ticket.draft_json or {}
            final_reply = draft_json.get("draft_reply", "")
            category = ticket.category or "General"
            
            if ratio >= threshold:
                try:
                    logger.info("Generating embedding for resolved reply writeback", ticket_id=str(ticket_id))
                    # Call existing embedding client (HuggingFace sentence-transformer mpnet model)
                    vector = get_embedding(final_reply)
                    
                    # Create TicketEmbedding row
                    embedding_row = TicketEmbedding(
                        ticket_id=ticket_id,
                        category=category,
                        embedding=vector,
                        source="resolved"
                    )
                    self.db.add(embedding_row)
                    
                    # Write success audit log
                    audit = AuditLog(
                        ticket_id=ticket_id,
                        action="writeback_completed",
                        detail={
                            "edit_distance_ratio": ratio,
                            "threshold": threshold,
                            "category": category
                        }
                    )
                    self.db.add(audit)
                    await self.db.commit()
                    logger.info("Resolve learning writeback completed successfully", ticket_id=str(ticket_id))
                except Exception as e:
                    logger.error("Learning loop embedding generation failed", ticket_id=str(ticket_id), error=str(e))
                    # Rollback changes within the try block (like the attempt to add embedding_row)
                    await self.db.rollback()
                    
                    # Re-fetch ticket to ensure the session session state is fresh, update edit_distance_ratio
                    fresh_res = await self.db.execute(
                        select(Ticket).filter(Ticket.id == ticket_id)
                    )
                    fresh_ticket = fresh_res.scalars().first()
                    if fresh_ticket:
                        fresh_ticket.edit_distance_ratio = ratio
                        self.db.add(fresh_ticket)
                    
                    # Log failure to audit log
                    audit_fail = AuditLog(
                        ticket_id=ticket_id,
                        action="writeback_failed",
                        detail={
                            "error": str(e),
                            "edit_distance_ratio": ratio
                        }
                    )
                    self.db.add(audit_fail)
                    await self.db.commit()
                    # Do NOT propagate or raise the exception. Email is already sent, and the main flow should succeed.
            else:
                logger.info("Writeback skipped due to low similarity ratio", ticket_id=str(ticket_id), ratio=ratio, threshold=threshold)
                # Write skipped audit log
                audit = AuditLog(
                    ticket_id=ticket_id,
                    action="writeback_skipped",
                    detail={
                        "edit_distance_ratio": ratio,
                        "threshold": threshold
                    }
                )
                self.db.add(audit)
                await self.db.commit()

        except Exception as outer_err:
            logger.error("Critical outer error in learning service resolve writeback", ticket_id=str(ticket_id), error=str(outer_err))
            await self.db.rollback()
            # Do NOT propagate outer exceptions.
