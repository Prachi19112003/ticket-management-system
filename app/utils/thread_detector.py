from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.ticket import Ticket
import uuid

async def detect_thread_id(
    message_id: str,
    headers: dict[str, str],
    db: AsyncSession,
    gmail_thread_id: str | None = None
) -> str:
    """
    Detects if the incoming message belongs to an existing email thread:
    1. Extracts parent message IDs from 'In-Reply-To' and 'References' headers.
    2. Looks up the parent ticket in the database.
    3. If a parent is found, returns its existing thread_id to group the ticket.
    4. If no parent is found, falls back to the native gmail_thread_id, or generates a new unique UUID.
    """
    safe_headers = headers or {}
    in_reply_to = safe_headers.get("In-Reply-To", "").strip()
    references = safe_headers.get("References", "").strip()

    # Collect potential parent message IDs
    potential_parent_ids = []
    if in_reply_to:
        potential_parent_ids.append(in_reply_to)
        
    if references:
        # Split references by whitespace to inspect multiple IDs
        for ref in references.split():
            clean_ref = ref.strip()
            if clean_ref and clean_ref not in potential_parent_ids:
                potential_parent_ids.append(clean_ref)

    # Standard email message IDs are wrapped in '<...>', strip them for query lookup
    cleaned_ids = [pid.strip("<>") for pid in potential_parent_ids]

    if cleaned_ids:
        # Query database to find any parent ticket matching these message IDs
        query = select(Ticket).filter(Ticket.message_id.in_(cleaned_ids))
        result = await db.execute(query)
        parent_ticket = result.scalars().first()
        if parent_ticket:
            return parent_ticket.thread_id

    # Fallback to Gmail API thread ID if available, otherwise generate a new thread ID
    if gmail_thread_id:
        return gmail_thread_id

    return str(uuid.uuid4())
