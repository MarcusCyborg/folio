"""search_context_fallback_meta

Revision ID: 20261105_context_fallback
Revises: 20261101_index_lifecycle
Create Date: 2026-11-05 08:00:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "20261105_context_fallback"
down_revision: Union[str, None] = "20261101_index_lifecycle"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "search_contexts",
        sa.Column("engine_used", sa.String(length=30), nullable=False, server_default="bm25"),
    )
    op.add_column(
        "search_contexts",
        sa.Column("is_degraded", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )
    op.add_column(
        "search_contexts",
        sa.Column("degraded_reason", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("search_contexts", "degraded_reason")
    op.drop_column("search_contexts", "is_degraded")
    op.drop_column("search_contexts", "engine_used")
