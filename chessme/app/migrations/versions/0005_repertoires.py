"""repertoires: the player's opening repertoires"""
import sqlalchemy as sa
from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("repertoires", sa.Column("id", sa.String, primary_key=True), sa.Column("name", sa.String, nullable=False), sa.Column("colour", sa.String, nullable=False),
                    sa.Column("pgn", sa.Text, nullable=False), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False))


def downgrade():
    op.drop_table("repertoires")
