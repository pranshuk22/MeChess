"""drills: positions from the player's mistakes, scheduled for repetition"""
import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "drills",
        sa.Column("id", sa.String, primary_key=True), sa.Column("game_id", sa.String, sa.ForeignKey("games.id", ondelete="SET NULL")), sa.Column("ply", sa.Integer),
        sa.Column("fen", sa.String, nullable=False), sa.Column("colour", sa.String, nullable=False), sa.Column("played_uci", sa.String, nullable=False), sa.Column("best_uci", sa.String, nullable=False),
        sa.Column("exercise", sa.JSON, nullable=False), sa.Column("box", sa.Integer, nullable=False, server_default="0"), sa.Column("due", sa.Float, nullable=False),
        sa.Column("history", sa.JSON), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_drills_game_id", "drills", ["game_id"])
    op.create_index("ix_drills_due", "drills", ["due"])


def downgrade():
    op.drop_table("drills")
