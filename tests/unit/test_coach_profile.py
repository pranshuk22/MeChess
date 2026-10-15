import chess

from chessme.coach import profile as P


def analysis_for(ucis, losses, win_before=0.5, phase="middlegame"):
    """An analysis dict for a game given as UCI moves with a loss per move."""
    board = chess.Board()
    moves = []
    for i, (u, loss) in enumerate(zip(ucis, losses)):
        mover = "white" if board.turn == chess.WHITE else "black"
        moves.append({"ply": i + 1, "uci": u, "color": mover, "loss": loss, "win_before": win_before, "phase": phase})
        board.push_uci(u)
    return {"moves": moves}


def test_rows_keep_the_players_moves_with_situation_and_kind():
    a = analysis_for(["f2f3", "e7e5", "g2g4", "d8h4"], [0.0, 0.0, 0.9, 0.0], win_before=0.7)
    rows = P.player_rows(a, "white")
    assert [r["situation"] for r in rows] == ["ahead", "ahead"] and rows[0]["kind"] is None and rows[1]["kind"] == "mate in 1"
    assert P.player_rows(a, "black")[0]["loss"] == 0.0


def test_a_category_is_a_weakness_only_with_enough_moves_and_a_clearly_higher_rate():
    rows = ([{"phase": "endgame", "situation": "level", "loss": 0.2, "kind": "deeper"}] * 15 + [{"phase": "endgame", "situation": "level", "loss": 0.0, "kind": None}] * 25
            + [{"phase": "middlegame", "situation": "level", "loss": 0.2, "kind": "deeper"}] * 5 + [{"phase": "middlegame", "situation": "level", "loss": 0.0, "kind": None}] * 95)
    prof = P.profile(rows)
    areas = [f["area"] for f in prof["findings"]]
    assert "phase: endgame" in areas and "phase: middlegame" not in areas
    assert prof["by_phase"]["endgame"]["mistake_rate"] == 15 / 40 and prof["moves"] == 140
    text = " ".join(P.sentences(prof))
    assert "endgame" in text and "endgame practice" in text
    few = [{"phase": "endgame", "situation": "level", "loss": 0.2, "kind": "deeper"}] * 5 + [{"phase": "opening", "situation": "level", "loss": 0.0, "kind": None}] * 50
    assert P.profile(few)["findings"] == []                                        # 5 moves are too few to call a weakness
    assert P.sentences(P.profile([]))[0].startswith("Nothing stands out")


def test_a_dominant_kind_of_mistake_is_reported_with_its_practice():
    rows = [{"phase": "middlegame", "situation": "level", "loss": 0.3, "kind": "walks into a capture"}] * 12 + [{"phase": "middlegame", "situation": "level", "loss": 0.0, "kind": None}] * 60 \
        + [{"phase": "middlegame", "situation": "level", "loss": 0.3, "kind": "deeper"}] * 8
    prof = P.profile(rows)
    assert any(f["area"] == "kind: walks into a capture" for f in prof["findings"])
    assert "put a piece where it can be captured" in " ".join(P.sentences(prof))
