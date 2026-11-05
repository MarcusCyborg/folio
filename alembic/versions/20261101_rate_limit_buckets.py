"""add_rate_limit_buckets_table

Revision ID: 20261101_rate_limit
Revises: 20261031_click_unique
Create Date: 2026-11-01 07:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = '20261101_rate_limit'
down_revision: Union[str, None] = '20261031_click_unique'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    jsonb_type = sa.JSON().with_variant(postgresql.JSONB, 'postgresql')
    op.create_table(
        'rate_limit_buckets',
        sa.Column('key_hash', sa.String(length=64), nullable=False),
        sa.Column('action', sa.String(length=32), nullable=False),
        sa.Column('attempts', jsonb_type, nullable=False, server_default=sa.text("'[]'")),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text("clock_timestamp()")),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text("clock_timestamp()")),
        sa.PrimaryKeyConstraint('key_hash')
    )
    op.create_index(
        'ix_rate_limit_buckets_action_updated',
        'rate_limit_buckets',
        ['action', 'updated_at'],
        unique=False
    )
    op.create_index(
        'ix_rate_limit_buckets_updated_at',
        'rate_limit_buckets',
        ['updated_at'],
        unique=False
    )


def downgrade() -> None:
    op.drop_index('ix_rate_limit_buckets_updated_at', table_name='rate_limit_buckets')
    op.drop_index('ix_rate_limit_buckets_action_updated', table_name='rate_limit_buckets')
    op.drop_table('rate_limit_buckets')
