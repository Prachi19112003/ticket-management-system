from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.ticket import Ticket
from app.models.ticket_embedding import TicketEmbedding
from app.core.logging import logger
from app.core.exceptions import DatabaseException

class RetrievalService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def retrieve_similar_tickets(
        self,
        category: str,
        query_embedding: list[float],
        limit: int = 3
    ) -> list[dict]:
        """
        Retrieves the top N most similar resolved tickets matching the category.
        Uses pgvector's cosine_distance calculation mapped to the HNSW database index.
        Returns:
            list[dict]: A list of dictionary objects detailing ticket parameters and resolution details.
        """
        logger.info("Executing pgvector similarity search", category=category, limit=limit)
        try:
            # Query joining tickets and embeddings to fetch semantic context and resolutions
            query = (
                select(Ticket, TicketEmbedding)
                .join(Ticket, Ticket.id == TicketEmbedding.ticket_id)
                .filter(TicketEmbedding.category == category)
                .filter(TicketEmbedding.source == "resolved")
                .order_by(TicketEmbedding.embedding.cosine_distance(query_embedding))
                .limit(limit)
            )

            result = await self.db.execute(query)
            rows = result.all()

            retrieved_tickets = []
            for ticket, embedding in rows:
                draft_data = ticket.draft_json or {}
                # Retrieve the resolved answer from the previous draft_reply field
                resolution = draft_data.get("draft_reply", "")
                if not resolution:
                    resolution = "No resolution text available."

                retrieved_tickets.append({
                    "ticket_id": str(ticket.id),
                    "subject": ticket.raw_subject,
                    "cleaned_body": ticket.cleaned_body,
                    "resolution": resolution
                })

            logger.info("Semantic retrieval completed successfully", count=len(retrieved_tickets))
            return retrieved_tickets

        except Exception as e:
            logger.error("pgvector semantic retrieval query failed", error=str(e))
            raise DatabaseException(
                "Database error occurred during vector search operations.",
                details={"original_error": str(e)}
            )
