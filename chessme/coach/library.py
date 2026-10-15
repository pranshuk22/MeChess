"""The opening library of the coach, and your own repertoire as the games show it.

`families` groups the named openings (Lichess chess-openings dataset, `openings_db`) by their first name ("Italian Game", "Sicilian Defense"), with the side that usually plays them. `library_pgn`
turns one family into a repertoire for a colour: the named lines are a tree; at each of YOUR turns the move the explorer says players choose most often is kept (at most `keep`
moves that have a real share of the games; without the explorer, the moves most named lines go through), at the opponent's turns the named replies. `repertoire_from_graph` builds the same
kind of PGN from what YOU played in your games (the moves you played at least `min_n` times, with their results), so the repertoire you already know can be practised and checked for gaps."""
import re

import chess
import chess.pgn

from .. import openings_db as OD

# openings named for the side that answers: played with Black
BLACK_NAME = re.compile(r"Defen[sc]e|Declined|Accepted|Benoni|Dutch|Indian|Budapest|Englund|Albin|Owen|Nimzowitsch", re.I)
FEATURED_WHITE = ("Italian Game", "Ruy Lopez", "Scotch Game", "Vienna Game", "King's Gambit", "Bishop's Opening", "London System", "Queen's Gambit", "Catalan Opening", "English Opening",
                  "Réti Opening", "Four Knights Game", "Colle System", "Trompowsky Attack")
FEATURED_BLACK = ("Sicilian Defense", "French Defense", "Caro-Kann Defense", "Scandinavian Defense", "Pirc Defense", "Alekhine Defense", "Philidor Defense", "Russian Game",
                  "Queen's Gambit Declined", "Slav Defense", "King's Indian Defense", "Nimzo-Indian Defense", "Grünfeld Defense", "Dutch Defense", "Modern Defense")
MIN_SHARE = 0.05


def family_of(name: str) -> str:
    return name.split(":")[0].strip()


def side_of(family: str) -> str:
    return "black" if family in FEATURED_BLACK or BLACK_NAME.search(family) else "white"


def families() -> list[dict]:
    """[{'name', 'side', 'lines', 'eco', 'featured'}], the featured main openings first (in the order above), the rest by name."""
    groups: dict[str, list] = {}
    for eco, name, moves in OD.lines():
        groups.setdefault(family_of(name), []).append((eco, moves))
    out = []
    for fam, ls in groups.items():
        side = side_of(fam)
        order = FEATURED_BLACK if side == "black" else FEATURED_WHITE
        out.append({"name": fam, "side": side, "lines": len(ls), "eco": sorted(e for e, _ in ls)[0], "featured": fam in order, "_rank": order.index(fam) if fam in order else 999})
    out.sort(key=lambda f: (f["_rank"], f["name"]))
    for f in out:
        del f["_rank"]
    return out


def _trie(lines):
    root = {"w": 0, "c": {}}
    for _, _, moves in lines:
        node = root
        for u in moves:
            node = node["c"].setdefault(u, {"w": 0, "c": {}})
            node["w"] += 1
    return root


def library_pgn(family: str, colour: str, replies=None, *, keep=2, opponent_replies=6) -> str | None:
    """A PGN with variations for `colour` from the named lines of `family` (None when there is no such family). `replies(fen) -> [(uci, share), ...]` is the explorer."""
    lines = [l for l in OD.lines() if family_of(l[1]) == family]
    if not lines:
        return None
    me = chess.WHITE if colour == "white" else chess.BLACK
    game = chess.pgn.Game()
    game.headers.update({"Event": f"{family} (library)", "White": "?", "Black": "?"})

    def walk(trie, board, pgn_node):
        kids = list(trie["c"].items())
        if not kids:
            return
        if board.turn == me:
            share = {}
            if replies is not None:
                share = dict(replies(board.fen()))
            ranked = sorted(kids, key=lambda kv: (-share.get(kv[0], 0.0), -kv[1]["w"], kv[0]))
            chosen = [kv for kv in ranked if not share or share.get(kv[0], 0.0) >= MIN_SHARE][:keep] or ranked[:1]
        else:
            chosen = sorted(kids, key=lambda kv: (-kv[1]["w"], kv[0]))[:opponent_replies]
        for uci, child in chosen:
            mv = chess.Move.from_uci(uci)
            nb = board.copy(stack=False)
            nb.push(mv)
            walk(child, nb, pgn_node.add_variation(mv))
    walk(_trie(lines), chess.Board(), game)
    return str(game)


def repertoire_from_graph(graph, colour: str, *, min_n=2, max_ply=16, keep=2, opp_keep=4):
    """(pgn, stats) of the moves YOU played in your games (`prep.graph.Graph` of your games with `colour`): at your turns the moves played at least `min_n` times (the `keep` most played),
    at the opponent's turns the replies you met at least `min_n` times. Each move carries how often it was played and the score. stats: positions (your turns covered), moves, games."""
    me = chess.WHITE if colour == "white" else chess.BLACK
    game = chess.pgn.Game()
    game.headers.update({"Event": f"My {colour} repertoire (from my games)", "White": "?", "Black": "?"})
    stats = {"positions": 0, "moves": 0, "games": graph.visits(chess.Board())}

    def walk(board, pgn_node, ply):
        if ply >= max_ply:
            return
        moves = [m for m in graph.moves(board, min_n=min_n)]
        moves = moves[:keep] if board.turn == me else moves[:opp_keep]
        if board.turn == me and moves:
            stats["positions"] += 1
        for uci, n, score in moves:
            mv = chess.Move.from_uci(uci)
            child = pgn_node.add_variation(mv)
            child.comment = f"{n} game{'s' if n != 1 else ''}" + (f", score {round(100 * score)}%" if score is not None else "")
            if board.turn == me:
                stats["moves"] += 1
            nb = board.copy(stack=False)
            nb.push(mv)
            walk(nb, child, ply + 1)
    walk(chess.Board(), game, 0)
    return str(game), stats
