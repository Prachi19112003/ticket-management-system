import uuid
from datetime import date
from sqlalchemy import select, func, cast, Date
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.llm_usage_log import LLMUsageLog

class LLMUsageRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def log_usage(
        self,
        ticket_id: uuid.UUID | None,
        call_type: str,
        model: str,
        input_tokens: int | None,
        output_tokens: int | None,
        total_tokens: int | None
    ) -> LLMUsageLog:
        """Create and persist a new LLM usage log row."""
        log_entry = LLMUsageLog(
            ticket_id=ticket_id,
            call_type=call_type,
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=total_tokens
        )
        self.db.add(log_entry)
        await self.db.commit()
        await self.db.refresh(log_entry)
        return log_entry

    async def get_total_by_ticket(self, ticket_id: uuid.UUID) -> dict:
        """Query sum of tokens by ticket ID."""
        stmt = select(
            func.sum(LLMUsageLog.input_tokens).label("input_tokens"),
            func.sum(LLMUsageLog.output_tokens).label("output_tokens"),
            func.sum(LLMUsageLog.total_tokens).label("total_tokens")
        ).where(LLMUsageLog.ticket_id == ticket_id)
        
        result = await self.db.execute(stmt)
        row = result.first()
        if row and row.total_tokens is not None:
            return {
                "input_tokens": int(row.input_tokens or 0),
                "output_tokens": int(row.output_tokens or 0),
                "total_tokens": int(row.total_tokens or 0)
            }
        return {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}

    async def get_total_overall(self) -> dict:
        """Query overall sum of tokens."""
        stmt = select(
            func.sum(LLMUsageLog.input_tokens).label("input_tokens"),
            func.sum(LLMUsageLog.output_tokens).label("output_tokens"),
            func.sum(LLMUsageLog.total_tokens).label("total_tokens")
        )
        
        result = await self.db.execute(stmt)
        row = result.first()
        if row and row.total_tokens is not None:
            return {
                "input_tokens": int(row.input_tokens or 0),
                "output_tokens": int(row.output_tokens or 0),
                "total_tokens": int(row.total_tokens or 0)
            }
        return {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}

    async def get_total_by_day(self) -> list[dict]:
        """Query sum of tokens grouped by day."""
        stmt = select(
            cast(LLMUsageLog.created_at, Date).label("day"),
            func.sum(LLMUsageLog.input_tokens).label("input_tokens"),
            func.sum(LLMUsageLog.output_tokens).label("output_tokens"),
            func.sum(LLMUsageLog.total_tokens).label("total_tokens")
        ).group_by(
            cast(LLMUsageLog.created_at, Date)
        ).order_by(
            cast(LLMUsageLog.created_at, Date).asc()
        )
        
        result = await self.db.execute(stmt)
        rows = result.all()
        return [
            {
                "day": str(row.day),
                "input_tokens": int(row.input_tokens or 0),
                "output_tokens": int(row.output_tokens or 0),
                "total_tokens": int(row.total_tokens or 0)
            }
            for row in rows
        ]
