"""Track snapshotted and indexed Wiki revisions separately.

Revision ID: 20260913_0003
Revises: 20260913_0002
"""

from alembic import op
import sqlalchemy as sa


revision = "20260913_0003"
down_revision = "20260913_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("wiki_pages") as batch_op:
        batch_op.add_column(sa.Column("indexed_revision_id", sa.Integer(), nullable=True))
        batch_op.create_index("ix_wiki_pages_indexed_revision_id", ["indexed_revision_id"])

    with op.batch_alter_table("wiki_sync_runs") as batch_op:
        batch_op.alter_column("deleted_count", new_column_name="removed_count")


def downgrade() -> None:
    with op.batch_alter_table("wiki_sync_runs") as batch_op:
        batch_op.alter_column("removed_count", new_column_name="deleted_count")

    with op.batch_alter_table("wiki_pages") as batch_op:
        batch_op.drop_index("ix_wiki_pages_indexed_revision_id")
        batch_op.drop_column("indexed_revision_id")
