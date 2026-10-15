"""preps and prep_games: preparation against an opponent"""
import sqlalchemy as sa
from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("preps", sa.Column("id", sa.String, primary_key=True), sa.Column("title", sa.String, nullable=False), sa.Column("status", sa.String, nullable=False),
                    sa.Column("handles", sa.JSON, nullable=False), sa.Column("params", sa.JSON, nullable=False), sa.Column("report", sa.JSON), sa.Column("error", sa.Text),
                    sa.Column("job_id", sa.String), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False), sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False))
    op.create_index("ix_preps_status", "preps", ["status"])
    op.create_table("prep_games", sa.Column("prep_id", sa.String, sa.ForeignKey("preps.id", ondelete="CASCADE"), primary_key=True), sa.Column("id", sa.String, primary_key=True),
                    sa.Column("data", sa.JSON, nullable=False), sa.Column("analysis", sa.JSON), sa.Column("full", sa.Integer, nullable=False, server_default="0"))


def downgrade():
    op.drop_table("prep_games")
    op.drop_index("ix_preps_status", "preps")
    op.drop_table("preps")
