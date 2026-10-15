"""book_notes and its full-text index"""
import sqlalchemy as sa
from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "book_notes",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True), sa.Column("fen", sa.String, nullable=False), sa.Column("san", sa.String, nullable=False), sa.Column("uci", sa.String, nullable=False),
        sa.Column("ply", sa.Integer), sa.Column("colour", sa.String), sa.Column("glyph", sa.String), sa.Column("judgement", sa.String), sa.Column("evaluation", sa.String), sa.Column("source", sa.String),
        sa.Column("comment", sa.Text, nullable=False), sa.Column("concepts", sa.String, nullable=False, server_default=","),
    )
    op.execute("CREATE VIRTUAL TABLE book_notes_fts USING fts5(comment, content='book_notes', content_rowid='id')")


def downgrade():
    op.execute("DROP TABLE IF EXISTS book_notes_fts")
    op.drop_table("book_notes")
