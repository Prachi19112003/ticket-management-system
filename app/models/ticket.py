import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any
from sqlalchemy import String, DateTime, ForeignKey, Integer, Float, Index, CheckConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func
from app.core.db import Base

if TYPE_CHECKING:
    from app.models.customer import Customer
    from app.models.attachment import Attachment
    from app.models.ticket_embedding import TicketEmbedding
    from app.models.audit_log import AuditLog

class Ticket(Base):
    __tablename__ = "tickets"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    thread_id: Mapped[str] = mapped_column(String, nullable=False)
    message_id: Mapped[str] = mapped_column(String, unique=True, nullable=False, index=True)
    customer_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("customers.id"), nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False, default="new")
    raw_subject: Mapped[str | None] = mapped_column(String, nullable=True)
    cleaned_body: Mapped[str | None] = mapped_column(String, nullable=True)
    category: Mapped[str | None] = mapped_column(String, nullable=True)
    category_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    priority_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    draft_json: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    guardrail_flags: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    reviewed_by: Mapped[str | None] = mapped_column(String, nullable=True)
    edit_distance_ratio: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    # Relationships
    customer: Mapped["Customer"] = relationship("Customer", back_populates="tickets")
    attachments: Mapped[list["Attachment"]] = relationship(
        "Attachment", back_populates="ticket", cascade="all, delete-orphan"
    )
    embeddings: Mapped[list["TicketEmbedding"]] = relationship(
        "TicketEmbedding", back_populates="ticket", cascade="all, delete-orphan"
    )
    audit_logs: Mapped[list["AuditLog"]] = relationship(
        "AuditLog", back_populates="ticket", cascade="all, delete-orphan"
    )

    __table_args__ = (
        CheckConstraint("priority_score >= 1 AND priority_score <= 100", name="priority_score_check"),
        Index("idx_tickets_status_priority", "status", "priority_score"),
        Index("idx_tickets_thread", "thread_id"),
    )
