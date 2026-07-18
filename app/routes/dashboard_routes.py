import uuid
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from app.core.db import get_db
from app.core.logging import logger
from app.models.ticket import Ticket
from app.models.ticket_embedding import TicketEmbedding
from app.models.llm_usage_log import LLMUsageLog

router = APIRouter(prefix="/dashboard", tags=["Dashboard"])


@router.get("/tickets", status_code=status.HTTP_200_OK)
async def get_tickets(
    status: str | None = None,
    db: AsyncSession = Depends(get_db)
) -> list[dict]:
    """
    Retrieves all tickets ordered by priority_score DESC, including the sum of total_tokens from llm_usage_log.
    Supports optional status filter.
    """
    try:
        stmt = (
            select(
                Ticket,
                func.coalesce(func.sum(LLMUsageLog.total_tokens), 0).label("total_tokens")
            )
            .outerjoin(LLMUsageLog, Ticket.id == LLMUsageLog.ticket_id)
            .group_by(Ticket.id)
            .order_by(Ticket.priority_score.desc())
        )
        if status:
            stmt = stmt.where(Ticket.status == status)

        res = await db.execute(stmt)
        rows = res.all()

        tickets_list = []
        for ticket, total_tokens in rows:
            tickets_list.append({
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
                "total_tokens": int(total_tokens)
            })
        return tickets_list
    except Exception as e:
        logger.error("Failed to query dashboard tickets", error=str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to query tickets list."
        )


@router.get("/tickets/{ticket_id}", status_code=status.HTTP_200_OK)
async def get_ticket_detail(
    ticket_id: uuid.UUID,
    db: AsyncSession = Depends(get_db)
) -> dict:
    """
    Retrieves full details of a single ticket by its UUID, including RAG references and all associated LLM usage log rows.
    """
    try:
        from app.repositories.ticket_repo import TicketRepository
        ticket_repo = TicketRepository(db)
        ticket = await ticket_repo.get_by_id(ticket_id)
        if not ticket:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Ticket with ID {ticket_id} does not exist."
            )

        # 1. Fetch RAG references used for this ticket
        retrieved_refs = []
        emb_query = select(TicketEmbedding).filter(
            TicketEmbedding.ticket_id == ticket.id,
            TicketEmbedding.source == "incoming"
        )
        res_emb = await db.execute(emb_query)
        embedding_row = res_emb.scalars().first()
        if embedding_row:
            try:
                from app.services.retrieval_service import RetrievalService
                retrieval_service = RetrievalService(db)
                retrieved_refs = await retrieval_service.retrieve_similar_tickets(
                    category=ticket.category or "General",
                    query_embedding=embedding_row.embedding,
                    limit=3
                )
            except Exception as e:
                logger.warning("Failed to fetch references for ticket", ticket_id=str(ticket.id), error=str(e))

        # 2. Fetch LLM usage logs
        logs_stmt = select(LLMUsageLog).where(LLMUsageLog.ticket_id == ticket.id).order_by(LLMUsageLog.created_at.asc())
        res_logs = await db.execute(logs_stmt)
        usage_logs = res_logs.scalars().all()

        return {
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
            "references": retrieved_refs,
            "llm_usage_logs": [
                {
                    "id": str(log.id),
                    "call_type": log.call_type,
                    "model": log.model,
                    "input_tokens": log.input_tokens,
                    "output_tokens": log.output_tokens,
                    "total_tokens": log.total_tokens,
                    "created_at": log.created_at.isoformat() if log.created_at else None
                }
                for log in usage_logs
            ]
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Failed to query ticket details", ticket_id=str(ticket_id), error=str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve ticket details."
        )


@router.get("/stats", status_code=status.HTTP_200_OK)
async def get_stats(db: AsyncSession = Depends(get_db)) -> dict:
    """
    Returns aggregate dashboard metrics:
    - Tickets count grouped by status
    - Tickets count grouped by category
    - Total tokens used today vs all-time
    - Average total tokens per draft generation call
    """
    try:
        # 1. Total tickets by status
        status_stmt = select(Ticket.status, func.count(Ticket.id)).group_by(Ticket.status)
        status_res = await db.execute(status_stmt)
        tickets_by_status = {s: c for s, c in status_res.all()}

        # 2. Total tickets by category
        cat_stmt = select(Ticket.category, func.count(Ticket.id)).group_by(Ticket.category)
        cat_res = await db.execute(cat_stmt)
        tickets_by_category = {c or "Unclassified": count for c, count in cat_res.all()}

        # 3. Tokens overall
        all_time_stmt = select(func.sum(LLMUsageLog.total_tokens))
        all_time_res = await db.execute(all_time_stmt)
        tokens_all_time = all_time_res.scalar() or 0

        # 4. Tokens today (created_at >= CURRENT_DATE)
        today_stmt = select(func.sum(LLMUsageLog.total_tokens)).where(LLMUsageLog.created_at >= func.current_date())
        today_res = await db.execute(today_stmt)
        tokens_today = today_res.scalar() or 0

        # 5. Average tokens per draft (call_type = 'draft_generation')
        avg_stmt = select(func.avg(LLMUsageLog.total_tokens)).where(LLMUsageLog.call_type == "draft_generation")
        avg_res = await db.execute(avg_stmt)
        avg_val = avg_res.scalar() or 0.0

        return {
            "tickets_by_status": tickets_by_status,
            "tickets_by_category": tickets_by_category,
            "tokens_used": {
                "today": int(tokens_today),
                "all_time": int(tokens_all_time)
            },
            "average_tokens_per_draft": round(float(avg_val), 2)
        }
    except Exception as e:
        logger.error("Failed to query dashboard statistics", error=str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to load dashboard statistics."
        )
