"""add_llm_usage_log

Revision ID: 9c4156642986
Revises: 3dfc7575f3bd
Create Date: 2026-07-17 17:33:09.435103

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '9c4156642986'
down_revision: Union[str, None] = '3dfc7575f3bd'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'llm_usage_log',
        sa.Column('id', sa.UUID(), nullable=False, server_default=sa.text('gen_random_uuid()')),
        sa.Column('ticket_id', sa.UUID(), sa.ForeignKey('tickets.id', ondelete='SET NULL'), nullable=True),
        sa.Column('call_type', sa.String(), nullable=False),
        sa.Column('model', sa.String(), nullable=False),
        sa.Column('input_tokens', sa.Integer(), nullable=True),
        sa.Column('output_tokens', sa.Integer(), nullable=True),
        sa.Column('total_tokens', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint('id')
    )


def downgrade() -> None:
    op.drop_table('llm_usage_log')
