import uuid
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel, Field

from app.core.db import get_db
from app.core.logging import logger
from app.services.review_service import ReviewService
from app.core.exceptions import TicketSystemException

router = APIRouter(prefix="/review", tags=["Review"])

class ReviewApprovePayload(BaseModel):
    reviewed_by: str = Field(..., description="Name or identifier of the reviewer.")

class ReviewEditPayload(BaseModel):
    revised_reply: str = Field(..., description="The edited/revised draft reply body.")
    reviewed_by: str = Field(..., description="Name or identifier of the reviewer.")

class ReviewRejectPayload(BaseModel):
    reviewed_by: str = Field(..., description="Name or identifier of the reviewer.")

@router.get("/queue", status_code=status.HTTP_200_OK)
async def get_review_queue(db: AsyncSession = Depends(get_db)) -> list[dict]:
    """Retrieves the priority-sorted queue of tickets awaiting review."""
    try:
        service = ReviewService(db)
        queue = await service.get_review_queue()
        return queue
    except Exception as e:
        logger.critical("Unexpected failure in get_review_queue handler", error=str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected error occurred while loading the review queue."
        )

@router.post("/{ticket_id}/approve", status_code=status.HTTP_200_OK)
async def approve_ticket(
    ticket_id: uuid.UUID,
    payload: ReviewApprovePayload,
    db: AsyncSession = Depends(get_db)
) -> dict:
    """Approves the draft reply as-is and sends the email."""
    try:
        service = ReviewService(db)
        success = await service.approve_ticket(ticket_id, payload.reviewed_by)
        return {
            "status": "approved_and_sent" if success else "approved_but_not_sent",
            "message": "Ticket successfully approved and queued for transmission."
        }
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except TicketSystemException as e:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=f"Failed to send approved draft: {e.message}")
    except Exception as e:
        logger.critical("Unexpected failure in approve_ticket handler", error=str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected error occurred during ticket approval."
        )

@router.post("/{ticket_id}/edit", status_code=status.HTTP_200_OK)
async def edit_ticket(
    ticket_id: uuid.UUID,
    payload: ReviewEditPayload,
    db: AsyncSession = Depends(get_db)
) -> dict:
    """Updates the draft reply with custom text, approves the ticket, and sends the email."""
    try:
        service = ReviewService(db)
        success = await service.edit_ticket(ticket_id, payload.revised_reply, payload.reviewed_by)
        return {
            "status": "approved_and_sent" if success else "approved_but_not_sent",
            "message": "Ticket successfully edited, approved, and queued for transmission."
        }
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except TicketSystemException as e:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=f"Failed to send edited draft: {e.message}")
    except Exception as e:
        logger.critical("Unexpected failure in edit_ticket handler", error=str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected error occurred while saving the edited draft."
        )

@router.post("/{ticket_id}/reject", status_code=status.HTTP_200_OK)
async def reject_ticket(
    ticket_id: uuid.UUID,
    payload: ReviewRejectPayload,
    db: AsyncSession = Depends(get_db)
) -> dict:
    """Rejects the draft reply, moving the ticket status to 'rejected'."""
    try:
        service = ReviewService(db)
        await service.reject_ticket(ticket_id, payload.reviewed_by)
        return {
            "status": "rejected",
            "message": "Ticket draft successfully rejected."
        }
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except Exception as e:
        logger.critical("Unexpected failure in reject_ticket handler", error=str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected error occurred during ticket rejection."
        )
