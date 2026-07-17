"""Initial schema

Revision ID: 3dfc7575f3bd
Revises: 
Create Date: 2026-07-16 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '3dfc7575f3bd'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Create vector extension
    op.execute(sa.text("CREATE EXTENSION IF NOT EXISTS vector;"))

    # 2. Create customers table
    op.create_table(
        'customers',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('email', sa.String(), nullable=False),
        sa.Column('name', sa.String(), nullable=True),
        sa.Column('tier', sa.String(), nullable=False, server_default='standard'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_customers_email'), 'customers', ['email'], unique=True)

    # 3. Create tickets table
    op.create_table(
        'tickets',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('thread_id', sa.String(), nullable=False),
        sa.Column('message_id', sa.String(), nullable=False),
        sa.Column('customer_id', sa.UUID(), nullable=False),
        sa.Column('status', sa.String(), nullable=False, server_default='new'),
        sa.Column('raw_subject', sa.String(), nullable=True),
        sa.Column('cleaned_body', sa.String(), nullable=True),
        sa.Column('category', sa.String(), nullable=True),
        sa.Column('category_confidence', sa.Float(), nullable=True),
        sa.Column('priority_score', sa.Integer(), nullable=True),
        sa.Column('draft_json', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('guardrail_flags', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('reviewed_by', sa.String(), nullable=True),
        sa.Column('edit_distance_ratio', sa.Float(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint('priority_score >= 1 AND priority_score <= 100', name='priority_score_check'),
        sa.ForeignKeyConstraint(['customer_id'], ['customers.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_tickets_message_id'), 'tickets', ['message_id'], unique=True)
    op.create_index('idx_tickets_status_priority', 'tickets', ['status', 'priority_score'], unique=False)
    op.create_index('idx_tickets_thread', 'tickets', ['thread_id'], unique=False)

    # 4. Create attachments table
    op.create_table(
        'attachments',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('ticket_id', sa.UUID(), nullable=False),
        sa.Column('s3_url', sa.String(), nullable=False),
        sa.Column('filename', sa.String(), nullable=True),
        sa.Column('content_type', sa.String(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(['ticket_id'], ['tickets.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )

    # 5. Create ticket_embeddings table
    op.create_table(
        'ticket_embeddings',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('ticket_id', sa.UUID(), nullable=False),
        sa.Column('category', sa.String(), nullable=False),
        sa.Column('embedding', Vector(768), nullable=True),
        sa.Column('source', sa.String(), nullable=False, server_default='resolved'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(['ticket_id'], ['tickets.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(
        'idx_ticket_embeddings_hnsw',
        'ticket_embeddings',
        ['embedding'],
        unique=False,
        postgresql_using='hnsw',
        postgresql_ops={'embedding': 'vector_cosine_ops'}
    )

    # 6. Create audit_log table
    op.create_table(
        'audit_log',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('ticket_id', sa.UUID(), nullable=True),
        sa.Column('action', sa.String(), nullable=False),
        sa.Column('detail', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(['ticket_id'], ['tickets.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id')
    )


def downgrade() -> None:
    op.drop_table('audit_log')
    op.drop_index('idx_ticket_embeddings_hnsw', table_name='ticket_embeddings')
    op.drop_table('ticket_embeddings')
    op.drop_table('attachments')
    op.drop_index('idx_tickets_thread', table_name='tickets')
    op.drop_index('idx_tickets_status_priority', table_name='tickets')
    op.drop_index(op.f('ix_tickets_message_id'), table_name='tickets')
    op.drop_table('tickets')
    op.drop_index(op.f('ix_customers_email'), table_name='customers')
    op.drop_table('customers')
    op.execute(sa.text("DROP EXTENSION IF EXISTS vector;"))
