import uuid
from sqlalchemy.ext.asyncio import AsyncSession
from app.repositories.ticket_repo import TicketRepository
from app.repositories.customer_repo import CustomerRepository
from app.integrations.gmail_client import GmailClient
from app.models.audit_log import AuditLog
from app.core.exceptions import GmailException
from app.core.logging import logger

class SendService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.ticket_repo = TicketRepository(db)
        self.customer_repo = CustomerRepository(db)
        self.gmail_client = GmailClient()

    async def send_draft(self, ticket_id: uuid.UUID) -> bool:
        """
        Orchestrates sending the approved draft reply for a ticket via the Gmail API client.
        On success: updates status to 'sent' and logs to audit.
        On failure: logs failure details to audit log and keeps status as-is (approved).
        """
        logger.info("Starting send_draft orchestration", ticket_id=str(ticket_id))
        ticket = await self.ticket_repo.get_by_id(ticket_id)
        if not ticket:
            raise ValueError(f"Ticket with ID {ticket_id} does not exist.")

        if ticket.status not in ["approved"]:
            logger.warning("Ticket is not in approved state, skipping send", ticket_id=str(ticket_id), status=ticket.status)
            return False

        customer = await self.customer_repo.get_by_id(ticket.customer_id)
        if not customer:
            raise ValueError(f"Customer associated with ticket {ticket_id} does not exist.")

        draft_json = ticket.draft_json or {}
        draft_reply = draft_json.get("draft_reply", "")
        cc_list = draft_json.get("cc_list", [])

        if not draft_reply:
            raise ValueError(f"Ticket {ticket_id} does not have a valid draft reply.")

        subject = f"Re: {ticket.raw_subject}" if ticket.raw_subject else "Support Ticket Reply"

        try:
            # Call Gmail REST client to send email
            gmail_msg_id = await self.gmail_client.send_email(
                to_email=customer.email,
                subject=subject,
                body=draft_reply,
                cc_list=cc_list
            )

            # On success, update status and write audit log
            ticket.status = "sent"
            audit = AuditLog(
                ticket_id=ticket_id,
                action="sent",
                detail={
                    "to_email": customer.email,
                    "gmail_message_id": gmail_msg_id,
                    "cc_list": cc_list
                }
            )
            self.db.add(audit)
            await self.db.commit()
            logger.info("Draft sent successfully and status updated to sent", ticket_id=str(ticket_id))

            # Run the write-back learning loop
            try:
                from app.utils.diff_scorer import compute_similarity_ratio
                from app.services.learning_service import LearningService
                
                # Fetch original draft reply from draft_json (fall back to current draft_reply if missing)
                original_reply = draft_json.get("original_draft_reply") or draft_reply
                ratio = compute_similarity_ratio(original_reply, draft_reply)
                
                learning_service = LearningService(self.db)
                await learning_service.writeback_resolved_reply(ticket_id, ratio)
            except Exception as learn_err:
                logger.error("Failed to run learning loop resolved writeback", ticket_id=str(ticket_id), error=str(learn_err))

            return True

        except Exception as e:
            logger.error("Gmail send operation failed", ticket_id=str(ticket_id), error=str(e))
            # Log failure to audit log but keep status as 'approved' (as-is)
            # Rollback current transaction state first in case DB connection had issues
            await self.db.rollback()
            
            # Write failure audit log entry
            audit = AuditLog(
                ticket_id=ticket_id,
                action="send_failed",
                detail={"error": str(e)}
            )
            self.db.add(audit)
            await self.db.commit()
            
            raise e
