"""add_partial_unique_index_for_open_reports

Revision ID: 20261106_report_open_unique
Revises: 20261105_context_fallback
Create Date: 2026-11-06 07:15:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "20261106_report_open_unique"
down_revision: Union[str, None] = "20261105_context_fallback"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Cleanly resolve any duplicate open reports before adding unique index
    conn = op.get_bind()
    conn.execute(sa.text("""
        UPDATE reports
        SET status = 'resolved',
            resolution = 'auto_merged_duplicate_open_report',
            handled_at = CURRENT_TIMESTAMP
        WHERE id IN (
            SELECT r1.id FROM reports r1
            JOIN reports r2 ON r1.comment_id = r2.comment_id
                AND r1.reporter_id = r2.reporter_id
                AND r1.status = 'open'
                AND r2.status = 'open'
            WHERE r1.created_at > r2.created_at
        )
    """))

    # 2. Create partial unique index on (comment_id, reporter_id) WHERE status = 'open'
    op.create_index(
        "uq_reports_open_comment_reporter",
        "reports",
        ["comment_id", "reporter_id"],
        unique=True,
        postgresql_where=sa.text("status = 'open'"),
        sqlite_where=sa.text("status = 'open'"),
    )


def downgrade() -> None:
    op.drop_index("uq_reports_open_comment_reporter", table_name="reports")
