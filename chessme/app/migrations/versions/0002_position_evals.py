"""position_evals: the opening evaluation cache"""
import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "position_evals",
        sa.Column("key", sa.String, primary_key=True), sa.Column("ply", sa.Integer, nullable=False), sa.Column("engine", sa.String),
        sa.Column("nodes", sa.Integer, nullable=False), sa.Column("multipv", sa.Integer, nullable=False), sa.Column("depth", sa.Integer),
        sa.Column("lines", sa.JSON, nullable=False), sa.Column("source", sa.String, nullable=False), sa.Column("hits", sa.Integer, nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False), sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_position_evals_ply", "position_evals", ["ply"])


def downgrade():
    op.drop_table("position_evals")
