"""Create the document metadata table.

Revision ID: 20260913_0001
Revises: None
"""

from alembic import op
import sqlalchemy as sa


revision = "20260913_0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "documents",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("filename", sa.String(length=512), nullable=False),
        sa.Column("content_type", sa.String(length=255), nullable=True),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("chunk_count", sa.Integer(), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_documents_filename", "documents", ["filename"])
    op.create_index("ix_documents_status", "documents", ["status"])


def downgrade() -> None:
    op.drop_index("ix_documents_status", table_name="documents")
    op.drop_index("ix_documents_filename", table_name="documents")
    op.drop_table("documents")
