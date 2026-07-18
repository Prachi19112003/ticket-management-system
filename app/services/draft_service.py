import uuid
import json
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.ticket import Ticket
from app.models.customer import Customer
from app.models.ticket_embedding import TicketEmbedding
from app.models.audit_log import AuditLog
from app.repositories.ticket_repo import TicketRepository
from app.repositories.customer_repo import CustomerRepository
from app.services.retrieval_service import RetrievalService
from app.services.summary_service import ThreadSummaryService
from app.schemas.draft import DraftResponseSchema
from app.integrations.llm_client import generate_completion_json
from app.integrations.embedding_client import get_embedding
from app.core.config import settings
from app.core.logging import logger
from app.core.exceptions import DatabaseException, LLMException, ValidationException
from app.repositories.llm_usage_repo import LLMUsageRepository

class DraftService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.ticket_repo = TicketRepository(db)
        self.customer_repo = CustomerRepository(db)
        self.retrieval_service = RetrievalService(db)
        self.summary_service = ThreadSummaryService()
        self.llm_usage_repo = LLMUsageRepository(db)

    async def generate_draft(self, ticket_id: uuid.UUID) -> dict:
        """
        Orchestrates RAG context retrieval and rolling thread summary retrieval,
        calls the LLM to generate a structured reply draft, validates it,
        resolves the CC list, persists the draft to the database, and logs audit events.
        """
        logger.info("Starting draft generation orchestration", ticket_id=str(ticket_id))
        
        # 1. Fetch target Ticket
        ticket = await self.ticket_repo.get_by_id(ticket_id)
        if not ticket:
            raise ValueError(f"Ticket with ID {ticket_id} does not exist.")

        # 2. Fetch Customer details
        customer = await self.customer_repo.get_by_id(ticket.customer_id)
        
        customer_name = customer.name if customer and customer.name else "Valued Customer"
        customer_tier = customer.tier if customer else "standard"

        # 3. Retrieve rolling thread summary from Redis
        thread_summary = await self.summary_service.get_summary(ticket.thread_id)
        if not thread_summary:
            thread_summary = "No previous context. This is the first interaction in the thread."

        # 4. Semantic Search (RAG)
        # Retrieve incoming ticket embedding
        query_vector = None
        emb_query = select(TicketEmbedding).filter(
            TicketEmbedding.ticket_id == ticket.id,
            TicketEmbedding.source == "incoming"
        )
        res_emb = await self.db.execute(emb_query)
        embedding_row = res_emb.scalars().first()
        
        if embedding_row:
            query_vector = embedding_row.embedding
        else:
            # Fallback: calculate embedding inline if not cached
            try:
                query_vector = get_embedding(ticket.cleaned_body)
            except Exception as e:
                logger.warning("Failed to generate embedding inline for RAG search", error=str(e))

        retrieved_refs = []
        if query_vector:
            try:
                retrieved_refs = await self.retrieval_service.retrieve_similar_tickets(
                    category=ticket.category or "General",
                    query_embedding=query_vector,
                    limit=3
                )
            except Exception as e:
                logger.error("RAG semantic retrieval failed during drafting", error=str(e))

        # 5. Build LLM prompt
        system_prompt = (
            "You are a customer support agent. Generate a professional reply to the customer.\n"
            "You MUST output a valid JSON object matching the following structure exactly:\n"
            "{\n"
            '  "draft_reply": "Dear [Name], thank you for reaching out...",\n'
            '  "category_confirmation": "Sales",\n'
            '  "cc_list": [],\n'
            '  "confidence_score": 0.95\n'
            "}\n"
            "Rules:\n"
            "- Confirmed category must be one of: Sales, Procurement, General.\n"
            "- cc_list must always be empty (leave it as []).\n"
            "- Address the customer using their name if provided.\n"
            "- Tailor the tone professionally based on subscription tier (platinum is extra premium).\n"
            "- Use the provided reference resolutions (RAG context) to match response style if relevant.\n"
            "- Never output markdown wrapping like ```json. Return raw JSON text only."
        )

        rag_text = ""
        for i, ref in enumerate(retrieved_refs, 1):
            rag_text += f"Reference #{i}:\nSubject: {ref['subject']}\nIncoming Email: {ref['cleaned_body']}\nResolution Answer: {ref['resolution']}\n\n"

        user_prompt = (
            f"Customer Name: {customer_name}\n"
            f"Customer Tier: {customer_tier}\n"
            f"Thread Running Summary: {thread_summary}\n\n"
            f"Incoming Ticket Subject: {ticket.raw_subject}\n"
            f"Incoming Ticket Body:\n---\n{ticket.cleaned_body}\n---\n\n"
            f"Semantic Reference Context (RAG):\n{rag_text}"
            "Please draft the response."
        )

        # 6. Call LLM & Validate
        draft_result = None
        try:
            raw_json, usage = await generate_completion_json(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                temperature=0.2
            )
            if usage:
                await self.llm_usage_repo.log_usage(
                    ticket_id=ticket_id,
                    call_type="draft_generation",
                    model=settings.OPENROUTER_MODEL,
                    input_tokens=usage.get("prompt_tokens"),
                    output_tokens=usage.get("completion_tokens"),
                    total_tokens=usage.get("total_tokens")
                )
            
            # Parse raw response and validate against schema
            from app.utils.json_cleaner import clean_json_markdown
            cleaned_json = clean_json_markdown(raw_json)
            try:
                parsed = json.loads(cleaned_json)
                validated = DraftResponseSchema(**parsed)
            except Exception as val_err:
                from pydantic import ValidationError
                err_details = {
                    "original_error": str(val_err),
                    "raw_response": raw_json
                }
                if isinstance(val_err, ValidationError):
                    err_details["validation_errors"] = val_err.errors()
                raise ValidationException(
                    "LLM response parsing or validation against DraftResponseSchema failed.",
                    details=err_details
                ) from val_err

            draft_result = validated.model_dump()
            draft_result["original_draft_reply"] = draft_result["draft_reply"]
            logger.info("LLM draft generated and validated successfully", category=draft_result["category_confirmation"])

        except Exception as e:
            details = getattr(e, "details", {})
            logger.error(
                "LLM draft generation or contract validation failed, running fallback draft",
                error=str(e),
                details=details
            )
            # Fallback path: standard polite boilerplate reply
            fallback_reply = (
                f"Dear {customer_name},\n\n"
                f"Thank you for contacting us regarding '{ticket.raw_subject}'. We have successfully "
                "received your inquiry and our support team is currently looking into it. "
                "We appreciate your patience.\n\n"
                "Sincerely,\nSupport Team"
            )
            draft_result = {
                "draft_reply": fallback_reply,
                "original_draft_reply": fallback_reply,
                "category_confirmation": ticket.category if ticket.category else "General",
                "cc_list": [],
                "confidence_score": 0.0
            }

        # 7. Resolve CC list (deterministic replacement based purely on category)
        confirmed_category = draft_result["category_confirmation"]
        draft_result["cc_list"] = list(settings.CC_MAPPING.get(confirmed_category, []))

        # 8. Persist Draft to DB
        ticket.draft_json = draft_result
        ticket.status = "drafted"
        # Update category if LLM confirmed category is different
        if confirmed_category != ticket.category:
            ticket.category = confirmed_category
            logger.info("Category overridden by LLM", old=ticket.category, new=confirmed_category)

        # Run guardrail checks and attach flags
        try:
            from app.services.guardrail_service import GuardrailService
            guardrail_service = GuardrailService()
            ticket.guardrail_flags = guardrail_service.scan_draft(ticket, retrieved_refs)
            logger.info("Guardrails executed during draft generation", flags_count=len(ticket.guardrail_flags))
        except Exception as e:
            logger.error("Failed to run guardrail scan during draft generation", error=str(e))
            ticket.guardrail_flags = []

        # 9. Audit Logging
        audit = AuditLog(
            ticket_id=ticket.id,
            action="drafted",
            detail={
                "category": confirmed_category,
                "confidence": draft_result["confidence_score"],
                "retrieved_references_count": len(retrieved_refs),
                "cc_count": len(draft_result["cc_list"])
            }
        )
        self.db.add(audit)
        await self.db.commit()
        await self.db.refresh(ticket)

        # 10. Update rolling thread summary in background/asynchronous flow
        # Ingestion of the draft reply is added to update the running thread summary
        try:
            await self.summary_service.update_summary(
                thread_id=ticket.thread_id,
                new_body=f"Agent Response: {draft_result['draft_reply']}",
                db=self.db,
                ticket_id=ticket.id
            )
        except Exception as e:
            logger.warning("Failed to update thread summary after generating draft", error=str(e))

        logger.info("Completed draft generation pipeline successfully", ticket_id=str(ticket.id))
        return draft_result
