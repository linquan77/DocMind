"""Create MediaWiki source, page, and sync-run tables.

Revision ID: 20260913_0002
Revises: 20260913_0001
"""

from alembic import op
import sqlalchemy as sa


revision = "20260913_0002"
down_revision = "20260913_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "wiki_sources",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("api_url", sa.String(length=1024), nullable=False),
        sa.Column("base_url", sa.String(length=1024), nullable=False),
        sa.Column("language", sa.String(length=32), nullable=False),
        sa.Column("root_categories_json", sa.Text(), nullable=False),
        sa.Column("excluded_category_keywords_json", sa.Text(), nullable=False),
        sa.Column("license_name", sa.String(length=255), nullable=True),
        sa.Column("license_url", sa.String(length=1024), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("last_synced_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("api_url"),
    )
    op.create_index("ix_wiki_sources_status", "wiki_sources", ["status"])

    op.create_table(
        "wiki_pages",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("document_id", sa.String(length=36), nullable=False),
        sa.Column("source_id", sa.String(length=36), nullable=False),
        sa.Column("page_id", sa.Integer(), nullable=False),
        sa.Column("revision_id", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=512), nullable=False),
        sa.Column("canonical_url", sa.String(length=1024), nullable=False),
        sa.Column("namespace", sa.Integer(), nullable=False),
        sa.Column("categories_json", sa.Text(), nullable=False),
        sa.Column("content_sha256", sa.String(length=64), nullable=False),
        sa.Column("snapshot_path", sa.String(length=1024), nullable=False),
        sa.Column("source_updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("synced_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["source_id"], ["wiki_sources.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("document_id"),
        sa.UniqueConstraint("source_id", "page_id", name="uq_wiki_pages_source_page"),
    )
    op.create_index("ix_wiki_pages_revision_id", "wiki_pages", ["revision_id"])
    op.create_index("ix_wiki_pages_source_id", "wiki_pages", ["source_id"])
    op.create_index("ix_wiki_pages_title", "wiki_pages", ["title"])

    op.create_table(
        "wiki_sync_runs",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("source_id", sa.String(length=36), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("discovered_count", sa.Integer(), nullable=False),
        sa.Column("created_count", sa.Integer(), nullable=False),
        sa.Column("updated_count", sa.Integer(), nullable=False),
        sa.Column("deleted_count", sa.Integer(), nullable=False),
        sa.Column("unchanged_count", sa.Integer(), nullable=False),
        sa.Column("failed_count", sa.Integer(), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["source_id"], ["wiki_sources.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_wiki_sync_runs_source_id", "wiki_sync_runs", ["source_id"])
    op.create_index("ix_wiki_sync_runs_status", "wiki_sync_runs", ["status"])


def downgrade() -> None:
    op.drop_index("ix_wiki_sync_runs_status", table_name="wiki_sync_runs")
    op.drop_index("ix_wiki_sync_runs_source_id", table_name="wiki_sync_runs")
    op.drop_table("wiki_sync_runs")
    op.drop_index("ix_wiki_pages_title", table_name="wiki_pages")
    op.drop_index("ix_wiki_pages_source_id", table_name="wiki_pages")
    op.drop_index("ix_wiki_pages_revision_id", table_name="wiki_pages")
    op.drop_table("wiki_pages")
    op.drop_index("ix_wiki_sources_status", table_name="wiki_sources")
    op.drop_table("wiki_sources")
