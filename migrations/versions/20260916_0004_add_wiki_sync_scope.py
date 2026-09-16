"""Record whether a Wiki sync is full or partial.

Revision ID: 20260916_0004
Revises: 20260913_0003
"""

from alembic import op
import sqlalchemy as sa


revision = "20260916_0004"
down_revision = "20260913_0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("wiki_sync_runs") as batch_op:
        batch_op.add_column(
            sa.Column("scope", sa.String(length=32), nullable=False, server_default="full")
        )
        batch_op.add_column(sa.Column("requested_titles_json", sa.Text(), nullable=True))
        batch_op.create_index("ix_wiki_sync_runs_scope", ["scope"])


def downgrade() -> None:
    with op.batch_alter_table("wiki_sync_runs") as batch_op:
        batch_op.drop_index("ix_wiki_sync_runs_scope")
        batch_op.drop_column("requested_titles_json")
        batch_op.drop_column("scope")
