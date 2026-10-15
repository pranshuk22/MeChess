"""games.played_time: the time of day, to order the games of one day"""
import sqlalchemy as sa
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("games") as b:
        b.add_column(sa.Column("played_time", sa.String))


def downgrade():
    with op.batch_alter_table("games") as b:
        b.drop_column("played_time")
