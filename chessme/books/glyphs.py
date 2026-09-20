"""Chess annotation symbols: what the marks and signs in books and annotated games mean.

Three notations carry meaning that a model must understand:
  * NAG numbers ($1 ... $146) in PGN files, shown as symbols: ! ? !! ?? !? ?!  and evaluations such as +- += ∞ ;
  * the same symbols written inside comments and book text (`Nf3!`, `±`, `∞`, `=+`);
  * figurine pieces (♘f3 for Nf3) used by many modern books and files.

The numbering and names follow the PGN standard as implemented in python-chess; ids 20 and 21 (crushing advantage) are added from the
standard's list. `kind` says what the glyph judges: a move (judgement), a position (evaluation), zugzwang, counterplay, time pressure or a novelty."""
import re

import chess.pgn as P

# id: (symbol, meaning, kind, side)   side: the colour the glyph favours or concerns (None: neither)
NAGS = {
    1: ("!", "good move", "judgement", None), 2: ("?", "mistake", "judgement", None), 3: ("!!", "brilliant move", "judgement", None),
    4: ("??", "blunder", "judgement", None), 5: ("!?", "speculative move", "judgement", None), 6: ("?!", "dubious move", "judgement", None),
    7: ("□", "forced move", "judgement", None), 8: ("", "singular move (no reasonable alternative)", "judgement", None),
    9: ("", "worst move", "judgement", None),
    10: ("=", "drawish position", "evaluation", None), 11: ("=", "equal chances, quiet position", "evaluation", None),
    12: ("=", "equal chances, active position", "evaluation", None), 13: ("∞", "unclear position", "evaluation", None),
    14: ("⩲", "White has a slight advantage", "evaluation", "white"), 15: ("⩱", "Black has a slight advantage", "evaluation", "black"),
    16: ("±", "White has a moderate advantage", "evaluation", "white"), 17: ("∓", "Black has a moderate advantage", "evaluation", "black"),
    18: ("+−", "White has a decisive advantage", "evaluation", "white"), 19: ("−+", "Black has a decisive advantage", "evaluation", "black"),
    20: ("+−", "White has a crushing advantage", "evaluation", "white"), 21: ("−+", "Black has a crushing advantage", "evaluation", "black"),
    22: ("⨀", "White is in zugzwang", "zugzwang", "white"), 23: ("⨀", "Black is in zugzwang", "zugzwang", "black"),
    132: ("⇆", "White has moderate counterplay", "counterplay", "white"), 133: ("⇆", "Black has moderate counterplay", "counterplay", "black"),
    134: ("⇆", "White has decisive counterplay", "counterplay", "white"), 135: ("⇆", "Black has decisive counterplay", "counterplay", "black"),
    136: ("", "White is in moderate time pressure", "time_pressure", "white"), 137: ("", "Black is in moderate time pressure", "time_pressure", "black"),
    138: ("", "White is in severe time pressure", "time_pressure", "white"), 139: ("", "Black is in severe time pressure", "time_pressure", "black"),
    146: ("N", "novelty", "novelty", None),
}
# White's advantage on a -3 ... +3 scale, for the evaluation glyphs that say who is better (None: no claim)
EVAL_SCORE = {10: 0, 11: 0, 12: 0, 14: 1, 15: -1, 16: 2, 17: -2, 18: 3, 19: -3, 20: 3, 21: -3}
JUDGEMENT = (3, 1, 5, 6, 2, 4)            # the six move glyphs, best to worst: !! ! !? ?! ? ??


def info(nag):
    """(symbol, meaning, kind, side) of a NAG; an unknown number is kept as an unnamed 'other' glyph."""
    return NAGS.get(nag, ("", f"annotation glyph ${nag}", "other", None))


def symbol(nag):
    return info(nag)[0]


def check_against_library():
    """The ids we name that python-chess also defines must agree in meaning (used by the tests): returns the list of mismatching ids."""
    bad = []
    for k, v in vars(P).items():
        if k.startswith("NAG_") and isinstance(v, int) and v in NAGS:
            lib = k[4:].lower().replace("_", " ")
            words = set(lib.split()) - {"move", "position"}
            if not any(w in NAGS[v][1].lower() for w in words if w not in ("null", "white", "black")):
                bad.append((v, k))
    return bad


# ---- glyphs written in text -------------------------------------------------------------------------------------------

TEXT_EVAL = {"+-": 18, "+−": 18, "-+": 19, "−+": 19, "+/-": 16, "-/+": 17, "+=": 14, "=+": 15, "±": 16, "∓": 17,
             "⩲": 14, "⩱": 15, "∞": 13, "⨀": 22, "□": 7, "⇆": 132}
_EVAL_RX = re.compile("|".join(re.escape(k) for k in sorted(TEXT_EVAL, key=len, reverse=True)))
_MOVE_MARK = re.compile(r"\b(?:[KQRBN]?[a-h]?[1-8]?x?[a-h][1-8]|O-O(?:-O)?)[+#]?(\?\?|!!|\?!|!\?|!|\?)(?![\w?!])")
MARK_NAG = {"!!": 3, "??": 4, "!?": 5, "?!": 6, "!": 1, "?": 2}


def marks_after_move(s):
    """NAG ids for the ! / ? marks at the start of `s` (what follows a move token): '!?' -> [5]."""
    m = re.match(r"\s*([!?]{1,2})", s)
    return [MARK_NAG[m.group(1)]] if m and m.group(1) in MARK_NAG else []


def symbols_in(text):
    """NAG ids found in free text: move marks directly after a move (`Nf3!`) and unambiguous evaluation symbols (`±`, `∞`, `=+`, `+-`)."""
    found = [MARK_NAG[m.group(1)] for m in _MOVE_MARK.finditer(text)]
    found += [TEXT_EVAL[m.group(0)] for m in _EVAL_RX.finditer(text)]
    return found


# ---- figurines -----------------------------------------------------------------------------------------------------------

FIGURINE = {"♔": "K", "♕": "Q", "♖": "R", "♗": "B", "♘": "N", "♙": "",
            "♚": "K", "♛": "Q", "♜": "R", "♝": "B", "♞": "N", "♟": ""}
_FIG_RX = re.compile("[" + "".join(FIGURINE) + "]")


def normalise_figurines(text):
    """Figurine notation to letters: '♘f3' -> 'Nf3', '♙e4' -> 'e4' (pawns have no letter)."""
    return _FIG_RX.sub(lambda m: FIGURINE[m.group(0)], text)


def describe(nags):
    """A short readable description of a list of NAG ids: '! (good move); ± (White has a moderate advantage)'."""
    return "; ".join(f"{symbol(n) or f'${n}'} ({info(n)[1]})" for n in nags)
