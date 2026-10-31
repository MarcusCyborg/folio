"""click_idempotency_unique

Revision ID: 20261031_click_unique
Revises: efeaa3d84c9b
Create Date: 2026-10-31 17:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '20261031_click_unique'
down_revision: Union[str, None] = 'efeaa3d84c9b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_index('ix_interaction_logs_actor_request', table_name='interaction_logs')
    op.create_index(
        'ix_interaction_logs_actor_request_unique',
        'interaction_logs',
        ['actor_key', 'request_key'],
        unique=True,
        postgresql_where=sa.text('request_key IS NOT NULL')
    )


def downgrade() -> None:
    op.drop_index('ix_interaction_logs_actor_request_unique', table_name='interaction_logs')
    op.create_index(
        'ix_interaction_logs_actor_request',
        'interaction_logs',
        ['actor_key', 'request_key'],
        unique=False
    )
