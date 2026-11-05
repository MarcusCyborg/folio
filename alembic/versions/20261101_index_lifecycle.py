"""index_lifecycle_schema

Revision ID: 20261101_index_lifecycle
Revises: 20261101_rate_limit
Create Date: 2026-11-01 09:00:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "20261101_index_lifecycle"
down_revision: Union[str, None] = "20261101_rate_limit"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    jsonb_type = sa.JSON().with_variant(postgresql.JSONB, "postgresql")

    # 1. document_revisions table
    op.create_table(
        "document_revisions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("document_id", sa.String(length=36), nullable=False),
        sa.Column("revision_num", sa.Integer(), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("title", sa.String(length=240), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("clock_timestamp()")),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("document_id", "revision_num", name="uq_document_revisions_doc_rev"),
    )
    op.create_index("ix_document_revisions_document_id", "document_revisions", ["document_id"], unique=False)
    op.create_index("ix_document_revisions_doc_hash", "document_revisions", ["document_id", "content_hash"], unique=False)

    # 2. index_jobs table
    op.create_table(
        "index_jobs",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("document_id", sa.String(length=36), nullable=False),
        sa.Column("revision_hash", sa.String(length=64), nullable=False),
        sa.Column("operation", sa.String(length=30), nullable=False),
        sa.Column("state", sa.String(length=20), nullable=False, server_default="pending"),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("max_attempts", sa.Integer(), nullable=False, server_default="5"),
        sa.Column("scheduled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("locked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("locked_by", sa.String(length=100), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("clock_timestamp()")),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_index_jobs_state_scheduled", "index_jobs", ["state", "scheduled_at", "created_at"], unique=False)
    op.create_index("ix_index_jobs_doc_created", "index_jobs", ["document_id", "created_at"], unique=False)
    op.create_index("ix_index_jobs_state_locked", "index_jobs", ["state", "locked_at"], unique=False)

    # 3. index_generations table
    op.create_table(
        "index_generations",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("generation_num", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="building"),
        sa.Column("doc_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("manifest", jsonb_type, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("clock_timestamp()")),
        sa.Column("active_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("clock_timestamp()")),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("generation_num", name="uq_index_generations_num"),
    )
    op.create_index("ix_index_generations_status", "index_generations", ["status"], unique=False)

    # 4. search_contexts table
    op.create_table(
        "search_contexts",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("token", sa.String(length=36), nullable=False),
        sa.Column("actor_key", sa.String(length=64), nullable=False),
        sa.Column("query", sa.String(length=200), nullable=False),
        sa.Column("mode", sa.String(length=20), nullable=False, server_default="bm25"),
        sa.Column("filters_hash", sa.String(length=64), nullable=False),
        sa.Column("page_size", sa.Integer(), nullable=False, server_default="20"),
        sa.Column("index_generation_id", sa.String(length=64), nullable=False),
        sa.Column("candidate_ids", jsonb_type, nullable=False),
        sa.Column("candidate_scores", jsonb_type, nullable=True),
        sa.Column("snapshot_total", sa.Integer(), nullable=True),
        sa.Column("snapshot_candidate_count", sa.Integer(), nullable=False),
        sa.Column("is_approximate_total", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("clock_timestamp()")),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["index_generation_id"], ["index_generations.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_search_contexts_token", "search_contexts", ["token"], unique=True)
    op.create_index("ix_search_contexts_actor_key", "search_contexts", ["actor_key"], unique=False)
    op.create_index("ix_search_contexts_expires_at", "search_contexts", ["expires_at"], unique=False)
    op.create_index("ix_search_contexts_gen_expires", "search_contexts", ["index_generation_id", "expires_at"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_search_contexts_gen_expires", table_name="search_contexts")
    op.drop_index("ix_search_contexts_expires_at", table_name="search_contexts")
    op.drop_index("ix_search_contexts_actor_key", table_name="search_contexts")
    op.drop_index("ix_search_contexts_token", table_name="search_contexts")
    op.drop_table("search_contexts")

    op.drop_index("ix_index_generations_status", table_name="index_generations")
    op.drop_table("index_generations")

    op.drop_index("ix_index_jobs_state_locked", table_name="index_jobs")
    op.drop_index("ix_index_jobs_doc_created", table_name="index_jobs")
    op.drop_index("ix_index_jobs_state_scheduled", table_name="index_jobs")
    op.drop_table("index_jobs")

    op.drop_index("ix_document_revisions_doc_hash", table_name="document_revisions")
    op.drop_index("ix_document_revisions_document_id", table_name="document_revisions")
    op.drop_table("document_revisions")
