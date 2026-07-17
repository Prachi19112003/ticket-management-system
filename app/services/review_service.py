import uuid
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.ticket import Ticket
from app.models.customer import Customer
from app.models.ticket_embedding import TicketEmbedding
from app.models.audit_log import AuditLog
from app.repositories.ticket_repo import TicketRepository
from app.services.retrieval_service import RetrievalService
from app.services.guardrail_service import GuardrailService
from app.services.send_service import SendService
from app.core.logging import logger

class ReviewService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.ticket_repo = TicketRepository(db)
        self.retrieval_service = RetrievalService(db)
        self.guardrail_service = GuardrailService()
        self.send_service = SendService(db)

    async def get_review_queue(self) -> list[dict]:
        """
        Retrieves a priority-sorted list of tickets awaiting human review (status in 'drafted', 'in_review').
        Injects the retrieved reference examples (RAG context) and populates guardrail flags on the fly.
        """
        logger.info("Fetching human review queue")
        query = (
            select(Ticket)
            .filter(Ticket.status.in_(["drafted", "in_review"]))
            .order_by(Ticket.priority_score.desc())
        )
        result = await self.db.execute(query)
        tickets = result.scalars().all()

        queue = []
        for ticket in tickets:
            # 1. Fetch RAG references used for this ticket
            retrieved_refs = []
            emb_query = select(TicketEmbedding).filter(
                TicketEmbedding.ticket_id == ticket.id,
                TicketEmbedding.source == "incoming"
            )
            res_emb = await self.db.execute(emb_query)
            embedding_row = res_emb.scalars().first()
            if embedding_row:
                try:
                    retrieved_refs = await self.retrieval_service.retrieve_similar_tickets(
                        category=ticket.category or "General",
                        query_embedding=embedding_row.embedding,
                        limit=3
                    )
                except Exception as e:
                    logger.warning("Failed to fetch references for review queue entry", ticket_id=str(ticket.id), error=str(e))

            # 2. Run guardrails on the fly and save if empty/new
            flags = self.guardrail_service.scan_draft(ticket, retrieved_refs)
            if flags != ticket.guardrail_flags:
                ticket.guardrail_flags = flags
                self.db.add(ticket)
                await self.db.commit()

            queue.append({
                "ticket_id": str(ticket.id),
                "status": ticket.status,
                "raw_subject": ticket.raw_subject,
                "cleaned_body": ticket.cleaned_body,
                "category": ticket.category,
                "category_confidence": ticket.category_confidence,
                "priority_score": ticket.priority_score,
                "draft_json": ticket.draft_json,
                "guardrail_flags": ticket.guardrail_flags,
                "reviewed_by": ticket.reviewed_by,
                "created_at": ticket.created_at.isoformat() if ticket.created_at else None,
                "references": retrieved_refs
            })

        logger.info("Human review queue loaded successfully", count=len(queue))
        return queue

    async def approve_ticket(self, ticket_id: uuid.UUID, reviewed_by: str) -> bool:
        """Approves a ticket as-is, logs the review, and triggers Gmail send."""
        logger.info("Approving ticket as-is", ticket_id=str(ticket_id), reviewer=reviewed_by)
        ticket = await self.ticket_repo.get_by_id(ticket_id)
        if not ticket:
            raise ValueError(f"Ticket with ID {ticket_id} does not exist.")

        ticket.status = "approved"
        ticket.reviewed_by = reviewed_by

        audit = AuditLog(
            ticket_id=ticket.id,
            action="reviewed",
            detail={
                "action": "approved",
                "reviewed_by": reviewed_by,
                "status": "approved"
            }
        )
        self.db.add(audit)
        await self.db.commit()
        
        # Trigger sending
        return await self.send_service.send_draft(ticket_id)

    async def edit_ticket(self, ticket_id: uuid.UUID, revised_reply: str, reviewed_by: str) -> bool:
        """Edits the draft reply, marks ticket as approved, and triggers Gmail send."""
        logger.info("Editing and approving ticket", ticket_id=str(ticket_id), reviewer=reviewed_by)
        ticket = await self.ticket_repo.get_by_id(ticket_id)
        if not ticket:
            raise ValueError(f"Ticket with ID {ticket_id} does not exist.")

        draft_json = dict(ticket.draft_json or {})
        draft_json["draft_reply"] = revised_reply
        ticket.draft_json = draft_json
        ticket.status = "approved"
        ticket.reviewed_by = reviewed_by

        audit = AuditLog(
            ticket_id=ticket.id,
            action="reviewed",
            detail={
                "action": "edited_and_approved",
                "reviewed_by": reviewed_by,
                "status": "approved"
            }
        )
        self.db.add(audit)
        await self.db.commit()

        # Trigger sending
        return await self.send_service.send_draft(ticket_id)

    async def reject_ticket(self, ticket_id: uuid.UUID, reviewed_by: str) -> None:
        """Rejects a ticket draft, changing status to 'rejected'."""
        logger.info("Rejecting ticket draft", ticket_id=str(ticket_id), reviewer=reviewed_by)
        ticket = await self.ticket_repo.get_by_id(ticket_id)
        if not ticket:
            raise ValueError(f"Ticket with ID {ticket_id} does not exist.")

        ticket.status = "rejected"
        ticket.reviewed_by = reviewed_by

        audit = AuditLog(
            ticket_id=ticket.id,
            action="reviewed",
            detail={
                "action": "rejected",
                "reviewed_by": reviewed_by,
                "status": "rejected"
            }
        )
        self.db.add(audit)
        await self.db.commit()
