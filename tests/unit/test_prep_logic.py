import chess
import chess.pgn
import pytest

from chessme.prep import games as PG
from chessme.prep import graph as GR
from chessme.prep import openings as OP
from chessme.prep import plan as PL
from chessme.prep import report as RP
from chessme.prep import weakness as WK
from chessme.analysis import runner as AR
from tests.unit.prep_helpers import search

LICHESS = """[Event "Rated Blitz game"]
[Site "https://lichess.org/AbCd1234"]
[White "Rival"]
[Black "other"]
[Result "1-0"]
[UTCDate "2026.09.18"]
[WhiteElo "1850"]
[BlackElo "1790"]
[TimeControl "180+0"]
[Termination "Time forfeit"]
[Opening "Italian Game: Evans Gambit"]

1. e4 { [%clk 0:03:00] } e5 { [%clk 0:03:00] } 2. Nf3 { [%clk 0:02:58] } Nc6 { [%clk 0:02:59] } 1-0
"""

CHESSCOM = """[Event "Live Chess"]
[Site "Chess.com"]
[White "other"]
[Black "rival"]
[Result "0-1"]
[Link "https://www.chess.com/game/live/123456"]
[ECOUrl "https://www.chess.com/openings/Sicilian-Defense-Open-Najdorf-Variation-6.Be3"]
[WhiteElo "1700"]
[BlackElo "1810"]
[TimeControl "600"]

1. e4 c5 2. Nf3 d6 0-1
"""


def test_a_game_is_read_from_the_opponents_side_with_clock_speed_opening_and_result():
    g = PG.parse(LICHESS, ["rival"])
    assert g.colour == "white" and g.score == 1.0 and g.speed == "blitz" and g.family == "Italian Game" and g.opening == "Italian Game: Evans Gambit"
    assert g.moves == ["e2e4", "e7e5", "g1f3", "b8c6"] and g.clocks[0] == 180 and g.opp_elo == 1850 and g.their_elo == 1790 and g.id == "AbCd1234"
    assert g.url == "https://lichess.org/AbCd1234" and g.base == 180 and "forfeit" in g.termination.lower()
    c = PG.parse(CHESSCOM, ["RIVAL"])                                                        # handles are not case sensitive
    assert c.colour == "black" and c.score == 1.0 and c.family == "Sicilian Defense Open Najdorf Variation" and c.speed == "rapid" and c.id == "123456"
    assert PG.parse(LICHESS, ["someone else"]) is None
    assert PG.parse(LICHESS.replace('[Result', '[FEN "8/8/8/8/8/8/8/K6k w - - 0 1"]\n[Result'), ["rival"]) is None


def test_the_summary_says_who_the_opponent_is():
    gs = [PG.parse(LICHESS, ["rival"]), PG.parse(CHESSCOM, ["rival"])]
    s = PG.summarise(gs)
    assert s["games"] == 2 and s["white"] == 1 and s["black"] == 1 and s["score"] == 1.0 and s["rating"] == 1850 and s["speeds"] == {"blitz": 1, "rapid": 1}


def test_the_graph_merges_transpositions_and_counts_moves_with_scores():
    class G:
        def __init__(self, moves, score):
            self.moves, self.score, self.colour = moves.split(), score, "white"
    g = GR.build([G("e2e4 e7e5 g1f3", 1.0), G("g1f3 e7e5 e2e4", 0.0), G("e2e4 c7c5", 0.5)])
    start = chess.Board()
    assert g.visits(start) == 3 and g.moves(start) == [("e2e4", 2, 0.75), ("g1f3", 1, 0.0)]
    b = chess.Board()
    for m in ("e2e4", "e7e5", "g1f3"):
        b.push_uci(m)
    b2 = chess.Board()
    for m in ("g1f3", "e7e5", "e2e4"):
        b2.push_uci(m)
    assert GR.key_of(b) == GR.key_of(b2)                                                    # the same position by another move order is one node


# ---- the plan ------------------------------------------------------------------------------------------------------------------------------

def mk(moves, score=0.0, colour="black", gid="g"):
    ucis = []
    b = chess.Board()
    for san in moves.split():
        mv = b.parse_san(san)
        ucis.append(mv.uci())
        b.push(mv)
    g = PG.OppGame(id=gid, colour=colour, moves=ucis, score=score, speed="blitz", date="2026-09-01", opening="Italian Game", family="Italian Game", opp_elo=1500, their_elo=1500, termination=None)
    return g


def trap_games(n=5):
    """The opponent (Black) plays 3...Nf6?? into 4.Qxf7# in most games and 3...Bc5 in one."""
    out = [mk("e4 e5 Qh5 Nc6 Bc4 Nf6 Qxf7#", 0.0, gid=f"t{i}") for i in range(n - 1)]
    out.append(mk("e4 e5 Qh5 Nc6 Bc4 Bc5 Qxf7#", 0.0, gid="t-last"))
    return out


def test_a_trap_is_a_position_where_their_usual_move_gives_away_a_lot_and_the_way_there_is_sound():
    graph = GR.build(trap_games())
    ev = PL.Evaluator(search)
    traps = PL.find_traps(graph, ev, "black")
    t = traps[0]
    assert t["move"] == "Nf6" and t["better"] and t["games"] == 4 and t["visits"] == 5 and t["loss"] > 0.3 and t["path"] == "1.e4 e5 2.Qh5 Nc6 3.Bc4"
    assert t["youStand"] > 0.9                                                              # after the blunder you are winning
    assert t["punish"] == "Qxf7#" and t["punishUci"] == "h5f7" and t["better"] != t["move"] and t["fenAfter"].split()[1] == "w"     # what you play after it, and what they should have played
    assert t["sound"] is True and t["fen"].split()[1] == "b"
    assert ev.searches > 0 and PL.find_traps(GR.build(trap_games(2)), PL.Evaluator(search), "black") == []         # two games are too few visits


def test_the_search_budget_is_respected_and_reported():
    ev = PL.Evaluator(search, budget=3)
    PL.find_traps(GR.build(trap_games()), ev, "black")
    assert ev.searches == 3 and ev.exhausted


def test_the_plan_steers_into_the_line_where_the_opponent_errs_and_names_what_it_expects():
    graph = GR.build(trap_games(6))
    ev = PL.Evaluator(search)
    planner = PL.Planner(ev, graph, GR.Graph(), "white", depth=3)
    tree = planner.tree()
    first = tree["children"][0]
    assert first["by"] == "you" and first["san"] == "e4"
    # follow the plan: 1.e4 e5 2.Qh5 ... : the opponent's reply is e5 (all of their games), then the plan's move is Qh5, the move that leads to the trap
    reply = first["children"][0]
    assert reply["by"] == "opp" and reply["san"] == "e5" and reply["p"] > 0.7
    mine = reply["children"][0]
    assert mine["san"] == "Qh5" and mine["value"] > mine["engine"] - 1e-9
    assert tree["gain"] > 0.0 and tree["value"] > tree["engine"]                           # the opponent's habits are worth something over best play
    lines = PL.pick_lines(tree)
    assert lines and lines[0]["moves"].startswith("1.e4 e5 2.Qh5")


def test_a_move_you_know_breaks_a_tie_and_no_alternative_costs_more_than_the_tolerance():
    class Y:
        def __init__(self, moves, score):
            self.moves, self.score, self.colour = moves.split(), score, "white"
    yg = GR.build([Y("e2e4 e7e5 g1f3", 1.0)] * 3)
    planner = PL.Planner(PL.Evaluator(search), GR.Graph(), yg, "white", depth=1)
    tree = planner.tree()
    assert tree["children"][0]["uci"] == "e2e4" and tree["children"][0]["yourGames"] == 3
    assert all(tree['children'][0]['engine'] - alt['engine'] <= PL.TOLERANCE + 1e-9 for alt in tree['children'][0]['alts'])     # nothing is recommended or offered that costs more than the tolerance


def test_the_plan_for_black_starts_from_what_they_play_as_white():
    games = [mk("e4 e5 Nf3 Nc6", 1.0, colour="white", gid=f"w{i}") for i in range(4)] + [mk("d4 d5 c4 e6", 0.0, colour="white", gid="w-d4")]
    planner = PL.Planner(PL.Evaluator(search), GR.build(games), GR.Graph(), "black", depth=2)
    tree = planner.tree()
    sans = {k["san"]: k for k in tree["children"]}
    assert set(sans) == {"e4", "d4"} and sans["e4"]["p"] > sans["d4"]["p"] and sans["e4"]["children"][0]["by"] == "you"


def test_the_plan_can_be_saved_as_a_repertoire_pgn():
    planner = PL.Planner(PL.Evaluator(search), GR.build(trap_games(6)), GR.Graph(), "white", depth=3)
    tree = planner.tree()
    pgn = PL.to_pgn(tree, "white", "Prepared")
    game = chess.pgn.read_game(__import__("io").StringIO(pgn))
    assert game.next().san() == "e4" and "of their games" in pgn


# ---- openings and weaknesses ------------------------------------------------------------------------------------------------------------------

def analysed(game, losses):
    """An analysis with the opponent's losses at the given plies (everything else perfect)."""
    moves = []
    b = chess.Board()
    for i, u in enumerate(game.moves):
        colour = "white" if i % 2 == 0 else "black"
        loss = losses.get(i + 1, 0.0) if colour == game.colour else 0.0
        moves.append({"ply": i + 1, "uci": u, "color": colour, "loss": loss, "win_before": 0.5, "win_after": 0.5 - loss, "phase": AR.phase(b), "class": "good", "move": b.san(chess.Move.from_uci(u)),
                      "best_move": u, "accuracy": 100.0})
        b.push(chess.Move.from_uci(u))
    return moves


def test_an_opening_is_weak_when_they_score_clearly_below_their_usual_or_often_err_early():
    games, analyses = [], {}
    for i in range(6):
        g = mk("e4 e5 Nf3 Nc6", 0.0, colour="black", gid=f"s{i}")
        g.family = "Scotch Game"
        games.append(g)
        analyses[g.id] = analysed(g, {4: 0.3} if i < 4 else {})
    for i in range(10):
        g = mk("d4 d5 c4 e6", 1.0 if i < 8 else 0.0, colour="black", gid=f"q{i}")
        g.family = "Queen's Gambit"
        games.append(g)
        analyses[g.id] = analysed(g, {})
    fam = OP.families(games, analyses)["black"]
    rows = {r["name"]: r for r in fam["families"]}
    assert rows["Scotch Game"]["weak"] and rows["Scotch Game"]["earlyMistakes"] == pytest.approx(4 / 6) and set(rows["Scotch Game"]["why"]) == {"scores badly", "often errs early"}
    assert not rows["Queen's Gambit"]["weak"] and rows["Queen's Gambit"]["score"] == 0.8 and fam["games"] == 16 and fam["families"][0]["name"] == "Queen's Gambit"


def test_endgame_kinds_time_trouble_and_conversion():
    b = chess.Board("8/5pk1/6p1/8/8/6P1/5PK1/R7 w - - 0 1")
    assert WK.endgame_type(b) == "rook ending" and WK.endgame_type(chess.Board("8/5pk1/8/8/8/8/5PK1/8 w - - 0 1")) == "pawn ending" and WK.endgame_type(chess.Board()) == "queen and others"
    g = mk("e4 e5 Nf3 Nc6", 0.0, colour="black", gid="c1")
    g.clocks, g.base, g.termination = [180, 180, 175, 5], 180, "Time forfeit"
    assert WK.low_clock_limit(180) == 15.0 and WK.low_clock_limit(60) == 6.0
    prof = WK.time_profile([g], WK.rows(g, analysed(g, {4: 0.3})))
    assert prof["troubleShare"] == 1.0 and prof["flagLosses"] == 1 and prof["mistakeRateLow"] == 1.0 and prof["scoreInTrouble"] == 0.0
    sentences = WK.opponent_sentences({"findings": [{"area": "phase: endgame", "moves": 40, "rate": 0.3, "elsewhere": 0.1, "z": 3}, {"area": "kind: ignores a threat", "moves": 20, "rate": 0.5, "elsewhere": None, "z": None}]})
    assert "endgame" in sentences[0] and "Aim for an endgame" in sentences[0] and "threats" in sentences[1]


def test_the_whole_report_has_every_part_and_says_when_data_is_thin():
    opp = trap_games(6) + [mk("e4 e5 Nf3 Nc6", 1.0, colour="white", gid=f"w{i}") for i in range(4)]
    analyses = {g.id: analysed(g, {6: 0.5} if g.id.startswith("t") else {}) for g in opp}
    you = [mk("e4 e5 Nf3", 1.0, colour="white", gid="u1")]
    out = RP.build(opp, analyses, you, {}, search, handles=[{"site": "lichess", "name": "rival"}], budget=400, depth=3)
    assert out["opponent"]["games"] == 10 and set(out) >= {"opponent", "openings", "you", "traps", "plan", "weakness", "headline", "notes", "searches"}
    assert out["plan"]["white"]["tree"]["children"][0]["san"] == "e4" and out["plan"]["black"]["tree"]["children"] and out["plan"]["white"]["pgn"].startswith("[Event")
    assert out["traps"]["black"] and out["headline"] and any("trap" in h.lower() for h in out["headline"])
    assert any("Only 10 games" in n for n in out["notes"]) and any("analysed in full" in n for n in out["notes"])
    thin = RP.build([mk("e4 e5", 1.0, colour="white")], {}, [], {}, search, handles=[], budget=50)
    assert thin["plan"]["black"]["tree"] is None and "not enough" in thin["plan"]["black"]["reason"]


def test_a_slightly_inferior_move_is_chosen_only_when_the_opponent_has_often_fallen_for_it():
    """The engine puts 2.Qh5 about 6 points under 2.Nf3, over the normal tolerance: it is a candidate only where the opponent was seen at least four times after it."""
    from chessme.analysis.runner import SimpleLine
    start = chess.Board()
    for m in ("e2e4", "e7e5"):
        start.push_uci(m)
    after_qh5 = start.copy()
    after_qh5.push_uci("d1h5")
    after_nf3 = start.copy()
    after_nf3.push_uci("g1f3")
    table = {GR.key_of(start): [SimpleLine("g1f3", 30, ["g1f3"]), SimpleLine("d1h5", -40, ["d1h5"])], GR.key_of(after_qh5): [SimpleLine("b8c6", 40, ["b8c6"])], GR.key_of(after_nf3): [SimpleLine("b8c6", -30, ["b8c6"])]}
    search_ = lambda b: table.get(GR.key_of(b), [])

    def planner(n):
        games = [mk("e4 e5 Qh5 Nc6", 0.0, gid=f"q{i}") for i in range(n)]
        return PL.Planner(PL.Evaluator(search_), GR.build(games), GR.Graph(), "white", depth=1)
    assert ("d1h5") in [u for u, _ in planner(5).candidates(start)] and "d1h5" not in [u for u, _ in planner(3).candidates(start)]
