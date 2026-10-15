"""games, analyses, jobs, settings"""
import sqlalchemy as sa
from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "games",
        sa.Column("id", sa.String, primary_key=True), sa.Column("source", sa.String, nullable=False),
        sa.Column("white", sa.String, nullable=False), sa.Column("black", sa.String, nullable=False),
        sa.Column("white_elo", sa.Integer), sa.Column("black_elo", sa.Integer), sa.Column("result", sa.String, nullable=False),
        sa.Column("played_at", sa.String), sa.Column("speed", sa.String), sa.Column("opening", sa.String), sa.Column("title", sa.String),
        sa.Column("user_colour", sa.String), sa.Column("pgn", sa.Text), sa.Column("plies", sa.Integer, nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_games_source", "games", ["source"])
    op.create_index("ix_games_played_at", "games", ["played_at"])
    op.create_table(
        "analyses",
        sa.Column("game_id", sa.String, sa.ForeignKey("games.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("nodes", sa.Integer, nullable=False), sa.Column("multipv", sa.Integer, nullable=False), sa.Column("engine", sa.String),
        sa.Column("accuracy_white", sa.Float), sa.Column("accuracy_black", sa.Float), sa.Column("moves", sa.JSON, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "jobs",
        sa.Column("id", sa.String, primary_key=True), sa.Column("kind", sa.String, nullable=False), sa.Column("title", sa.String, nullable=False),
        sa.Column("status", sa.String, nullable=False), sa.Column("progress", sa.Float, nullable=False, server_default="0"), sa.Column("message", sa.Text),
        sa.Column("params", sa.JSON), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True)), sa.Column("finished_at", sa.DateTime(timezone=True)),
    )
    op.create_index("ix_jobs_status", "jobs", ["status"])
    op.create_table("settings", sa.Column("key", sa.String, primary_key=True), sa.Column("value", sa.JSON))


def downgrade():
    for t in ("settings", "jobs", "analyses", "games"):
        op.drop_table(t)
