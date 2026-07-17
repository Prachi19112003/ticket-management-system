import uuid
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.ticket import Ticket

class TicketRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def get_by_id(self, ticket_id: uuid.UUID) -> Ticket | None:
        """Fetch a ticket by its primary key UUID."""
        result = await self.db.execute(select(Ticket).filter(Ticket.id == ticket_id))
        return result.scalars().first()

    async def get_by_message_id(self, message_id: str) -> Ticket | None:
        """Fetch a ticket by its unique message_id (used for deduplication)."""
        result = await self.db.execute(select(Ticket).filter(Ticket.message_id == message_id))
        return result.scalars().first()

    async def create(self, ticket: Ticket) -> Ticket:
        """Persist a new ticket to the database."""
        self.db.add(ticket)
        await self.db.commit()
        await self.db.refresh(ticket)
        return ticket

    async def update(self, ticket: Ticket) -> Ticket:
        """Commit changes to an existing ticket."""
        await self.db.commit()
        await self.db.refresh(ticket)
        return ticket
