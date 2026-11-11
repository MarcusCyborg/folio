"""add_partial_unique_index_for_open_reports

Revision ID: 20261106_report_open_unique
Revises: 20261105_context_fallback
Create Date: 2026-11-06 07:15:00.000000

"""
import json
import uuid
from datetime import datetime, timezone
from typing import Sequence, Union, Dict, Any, List
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "20261106_report_open_unique"
down_revision: Union[str, None] = "20261105_context_fallback"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def inspect_duplicate_open_reports(conn) -> Dict[str, Any]:
    """
    Preflight / dry-run inspection of duplicate open reports sharing (comment_id, reporter_id).
    Deterministically selects the canonical earliest open report ordered by (created_at ASC, id ASC)
    and identifies all later duplicate rows to be resolved without deleting history.
    """
    rows = conn.execute(
        sa.text(
            """
            SELECT id, comment_id, reporter_id, created_at
            FROM reports
            WHERE status = 'open'
            ORDER BY comment_id ASC, reporter_id ASC, created_at ASC, id ASC
            """
        )
    ).fetchall()

    seen_canonical: Dict[tuple, str] = {}
    groups: Dict[tuple, Dict[str, Any]] = {}
    duplicate_ids: List[str] = []

    for row in rows:
        report_id, comment_id, reporter_id, created_at = row[0], row[1], row[2], row[3]
        key = (comment_id, reporter_id)
        if key not in seen_canonical:
            seen_canonical[key] = report_id
            groups[key] = {
                "comment_id": comment_id,
                "reporter_id": reporter_id,
                "kept_report_id": report_id,
                "kept_created_at": str(created_at),
                "duplicate_report_ids": [],
            }
        else:
            duplicate_ids.append(report_id)
            groups[key]["duplicate_report_ids"].append(report_id)

    affected_groups = [g for g in groups.values() if g["duplicate_report_ids"]]
    return {
        "total_open_reports": len(rows),
        "duplicate_groups_count": len(affected_groups),
        "duplicate_rows_to_resolve": len(duplicate_ids),
        "duplicate_ids": duplicate_ids,
        "groups": affected_groups,
    }


def deduplicate_open_reports(conn, dry_run: bool = False) -> Dict[str, Any]:
    """
    Resolves duplicate open reports deterministically (tie-breaking equal created_at by id ASC).
    Preserves all historical records by setting status='resolved' and recording an audit trail.
    """
    plan = inspect_duplicate_open_reports(conn)
    plan["dry_run"] = dry_run
    if dry_run or plan["duplicate_rows_to_resolve"] == 0:
        plan["resolved_count"] = 0
        return plan

    # Deterministic tie-break: keep earliest (created_at ASC, id ASC); resolve all strictly greater pairs
    update_result = conn.execute(
        sa.text(
            """
            UPDATE reports
            SET status = 'resolved',
                resolution = 'auto_merged_duplicate_open_report',
                handled_at = CURRENT_TIMESTAMP
            WHERE id IN (
                SELECT r1.id
                FROM reports r1
                JOIN reports r2
                  ON r1.comment_id = r2.comment_id
                 AND r1.reporter_id = r2.reporter_id
                 AND r1.status = 'open'
                 AND r2.status = 'open'
                WHERE (r1.created_at > r2.created_at)
                   OR (r1.created_at = r2.created_at AND r1.id > r2.id)
            )
            """
        )
    )
    resolved_count = int(update_result.rowcount or 0)
    plan["resolved_count"] = resolved_count

    # Record migration data impact in audit_logs if the table exists
    inspector = sa.inspect(conn)
    if "audit_logs" in inspector.get_table_names():
        conn.execute(
            sa.text(
                """
                INSERT INTO audit_logs (
                    id, actor_id, action, entity_type, entity_id, before, after, timestamp
                ) VALUES (
                    :id, NULL, 'migration.deduplicate_open_reports',
                    'reports', '20261106_report_open_unique', :before, :after, :timestamp
                )
                """
            ),
            {
                "id": str(uuid.uuid4()),
                "before": json.dumps(
                    {
                        "total_open_reports": plan["total_open_reports"],
                        "duplicate_groups_count": plan["duplicate_groups_count"],
                        "duplicate_ids": plan["duplicate_ids"],
                    },
                    ensure_ascii=False,
                ),
                "after": json.dumps(
                    {
                        "revision": revision,
                        "resolved_count": resolved_count,
                        "groups": plan["groups"],
                    },
                    ensure_ascii=False,
                ),
                "timestamp": datetime.now(timezone.utc),
            },
        )

    return plan


def upgrade() -> None:
    conn = op.get_bind()
    deduplicate_open_reports(conn, dry_run=False)

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
