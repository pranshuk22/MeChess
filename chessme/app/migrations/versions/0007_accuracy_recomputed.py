"""game accuracy recomputed the Lichess way (volatility-weighted mean averaged with the harmonic mean) for every stored analysis; the old plain average was too generous"""
import json

import sqlalchemy as sa
from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade():
    from chessme.analysis import accuracy as ACC
    conn = op.get_bind()
    rows = conn.execute(sa.text("select game_id, moves from analyses")).fetchall()
    for gid, moves in rows:
        moves = json.loads(moves) if isinstance(moves, str) else moves
        if not moves:
            continue
        acc = ACC.from_api_moves(moves)
        conn.execute(sa.text("update analyses set accuracy_white = :w, accuracy_black = :b where game_id = :g"), {"w": acc["white"], "b": acc["black"], "g": gid})


def downgrade():
    pass                                                                       # the old figures are not kept; the new ones stay
