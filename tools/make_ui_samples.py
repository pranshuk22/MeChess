"""Sample games with real engine analysis for the UI prototype (frontend/src/samples/sample-games.json).

Three famous public-domain games plus engine-played games between Stockfish at different node limits from varied openings.
Run once; the output is small and committed. Needs Stockfish; opening names come from `data/opening_names` (`theory-book --download`).
Usage: PYTHONPATH=. python tools/make_ui_samples.py OUT.json [--engine PATH] [--games N]"""
import argparse
import io
import json
import random
import shutil
from pathlib import Path

import chess
import chess.engine
import chess.pgn

from chessme.analysis import classify as C
from chessme.analysis import runner as AR
from chessme.book import theory as TH
from chessme.uci_client import UciEngine

FAMOUS = [
    ("Paul Morphy", "Duke of Brunswick and Count Isouard", 1858, "1-0", "Opera Game",
     "1. e4 e5 2. Nf3 d6 3. d4 Bg4 4. dxe5 Bxf3 5. Qxf3 dxe5 6. Bc4 Nf6 7. Qb3 Qe7 8. Nc3 c6 9. Bg5 b5 10. Nxb5 cxb5 11. Bxb5+ Nbd7 12. O-O-O Rd8 13. Rxd7 Rxd7 14. Rd1 Qe6 15. Bxd7+ Nxd7 16. Qb8+ Nxb8 17. Rd8# 1-0"),
    ("Adolf Anderssen", "Lionel Kieseritzky", 1851, "1-0", "Immortal Game",
     "1. e4 e5 2. f4 exf4 3. Bc4 Qh4+ 4. Kf1 b5 5. Bxb5 Nf6 6. Nf3 Qh6 7. d3 Nh5 8. Nh4 Qg5 9. Nf5 c6 10. g4 Nf6 11. Rg1 cxb5 12. h4 Qg6 13. h5 Qg5 14. Qf3 Ng8 15. Bxf4 Qf6 16. Nc3 Bc5 17. Nd5 Qxb2 18. Bd6 Bxg1 19. e5 Qxa1+ 20. Ke2 Na6 21. Nxg7+ Kd8 22. Qf6+ Nxf6 23. Be7# 1-0"),
    ("Adolf Anderssen", "Jean Dufresne", 1852, "1-0", "Evergreen Game",
     "1. e4 e5 2. Nf3 Nc6 3. Bc4 Bc5 4. b4 Bxb4 5. c3 Ba5 6. d4 exd4 7. O-O d3 8. Qb3 Qf6 9. e5 Qg6 10. Re1 Nge7 11. Ba3 b5 12. Qxb5 Rb8 13. Qa4 Bb6 14. Nbd2 Bb7 15. Ne4 Qf5 16. Bxd3 Qh5 17. Nf6+ gxf6 18. exf6 Rg8 19. Rad1 Qxf3 20. Rxe7+ Nxe7 21. Qxd7+ Kxd7 22. Bf5+ Ke8 23. Bd7+ Kf8 24. Bxe7# 1-0"),
]


def opening_name(lines, moves):
    best = ""
    for eco, name, ms in lines:
        if len(ms) <= len(moves) and all(a == b for a, b in zip(ms, moves)) and (not best or len(ms) >= best[0]):
            best = (len(ms), f"{name}")
    return best[1] if best else ""


def record(gid, white, black, welo, belo, result, year, speed, moves, search, lines, user):
    board = chess.Board()
    g = chess.pgn.Game()
    node = g
    for mv in moves:
        node = node.add_variation(mv)
    g.headers["Result"] = result
    res = AR.analyse_game(g, search)
    out = []
    for m in res["moves"]:
        cp_mover = m["played_cp"]
        cp_white = cp_mover if m["color"] == "white" else -cp_mover
        out.append({"san": m["move"], "uci": m["uci"], "cls": m["class"], "loss": m["loss"], "best": m["best_move"],
                    "winBefore": m["win_before"], "winAfter": m["win_after"], "cp": int(max(-1500, min(1500, cp_white))),
                    "acc": m["accuracy"], "phase": m["phase"]})
    if result == "*":                                                 # the game was stopped at the move cap: adjudicate by the last evaluation
        last = out[-1]["cp"] if out else 0
        result = "1-0" if last > 300 else "0-1" if last < -300 else "1/2-1/2"
    return {"id": gid, "white": white, "black": black, "whiteElo": welo, "blackElo": belo, "result": result, "year": year, "speed": speed,
            "opening": opening_name(lines, moves), "user": user, "moves": out,
            "accuracy": {k: res["summary"][k]["accuracy"] for k in ("white", "black")}}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("out")
    ap.add_argument("--engine", default=shutil.which("stockfish"))
    ap.add_argument("--games", type=int, default=9)
    ap.add_argument("--nodes", type=int, default=30000)
    a = ap.parse_args()
    lines = TH.load_lines(sorted(Path("data/opening_names").glob("*.tsv")))
    eng = UciEngine([a.engine], options={"Threads": 1, "Hash": 64}).start()
    search = AR.engine_search(eng, nodes=a.nodes, multipv=3)
    rng = random.Random(7)
    games = []
    for i, (w, b, y, r, title, pgn) in enumerate(FAMOUS):
        g = chess.pgn.read_game(io.StringIO(pgn))
        games.append(record(f"s{i + 1:02d}", w, b, 2600, 2400, r, y, "classical", list(g.mainline_moves()), search, lines, "white"))
        games[-1]["title"] = title
    play = chess.engine.SimpleEngine.popen_uci(a.engine)
    play.configure({"Threads": 1, "Hash": 32})
    speeds = ["blitz", "blitz", "rapid", "bullet", "blitz", "rapid"]
    for k in range(a.games):
        board = chess.Board()
        for _ in range(rng.choice([4, 6, 8])):                        # a varied opening from random legal-but-sensible moves chosen by a quick search
            info = play.analyse(board, chess.engine.Limit(nodes=2000), multipv=4)
            board.push(rng.choice(info)["pv"][0])
        n_w, n_b = rng.choice([300, 1000, 3000]), rng.choice([300, 1000, 3000])
        for _ in range(100):
            if board.is_game_over():
                break
            n = n_w if board.turn else n_b
            res = play.play(board, chess.engine.Limit(nodes=n if rng.random() > 0.12 else 40))
            board.push(res.move)
        res = board.result(claim_draw=True)
        moves = list(board.move_stack)
        elo = lambda n: 1100 + {300: 150, 1000: 450, 3000: 800}[n] + rng.randint(-40, 40)
        games.append(record(f"s{len(games) + 1:02d}", f"Sample player {2 * k + 1}", f"Sample player {2 * k + 2}", elo(n_w), elo(n_b), res, 2026,
                            speeds[k % len(speeds)], moves, search, lines, rng.choice(["white", "black"])))
        print(len(games), res, len(moves), flush=True)
    play.quit()
    eng.close()
    Path(a.out).write_text(json.dumps(games, separators=(",", ":")))
    print("wrote", a.out, Path(a.out).stat().st_size, "bytes")


if __name__ == "__main__":
    main()
