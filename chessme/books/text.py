"""Read chess books (plan 8n, section C): extract game lines from the text of a book, in algebraic or *descriptive* notation
(P-K4, Kt-KB3, ...), and count concept words in the prose around them.

Book text (from OCR or a typesetter's file) is noisy, so every candidate move is checked for legality against the position: a line
ends at the first token that is not a legal, unambiguous move, and OCR junk simply fails to parse. Only lines that start from the
initial position are extracted (the book's diagrams give other starting positions; those need diagram recognition first)."""
import re

import chess

from . import glyphs as GL

FILE_NAMES = {0: "QR", 1: "QN", 2: "QB", 3: "Q", 4: "K", 5: "KB", 6: "KN", 7: "KR"}
PIECE_LETTER = {chess.PAWN: "P", chess.KNIGHT: "N", chess.BISHOP: "B", chess.ROOK: "R", chess.QUEEN: "Q", chess.KING: "K"}


# ---- descriptive notation ---------------------------------------------------------------------------------------------

def _squares(sq, color):
    """The names of a square from `color`'s side: qualified (KB3) and, for the B, N and R files, the generic one books use (B3)."""
    rank = chess.square_rank(sq) + 1
    rank = rank if color == chess.WHITE else 9 - rank
    name = FILE_NAMES[chess.square_file(sq)]
    return {f"{name}{rank}"} | ({f"{name[-1]}{rank}"} if name[-1] in "BNR" and len(name) == 2 else set())


def descriptive_forms(board, move):
    """All the descriptive spellings of `move` in `board` (no check marks; knights as N): P-K4, N-KB3, QN-Q2, PxP, BxN, PxQP,
    P-K8=Q ... The unqualified and the origin-file-qualified forms are both returned."""
    if board.is_castling(move):
        return {"O-O" if board.is_kingside_castling(move) else "O-O-O"}
    color = board.turn
    piece = board.piece_at(move.from_square)
    letter = PIECE_LETTER[piece.piece_type]
    origin_file = FILE_NAMES[chess.square_file(move.from_square)]
    names = {letter}
    if piece.piece_type == chess.PAWN:
        names.add(origin_file + "P")                                    # QBP, KP, ...
    elif piece.piece_type in (chess.KNIGHT, chess.BISHOP, chess.ROOK) and origin_file.endswith(letter):
        names.add(origin_file)                                          # QN, KN, QB, KB, QR, KR (the piece's home file)
    forms = set()
    if board.is_capture(move):
        if board.is_en_passant(move):
            victim, vsq = chess.PAWN, chess.square(chess.square_file(move.to_square), chess.square_rank(move.from_square))
        else:
            victim, vsq = board.piece_at(move.to_square).piece_type, move.to_square
        vfile = FILE_NAMES[chess.square_file(vsq)]
        targets = {PIECE_LETTER[victim]} | _squares(move.to_square, color)
        if victim not in (chess.QUEEN, chess.KING):
            targets.add(vfile + PIECE_LETTER[victim])
        for n in names:
            for t in targets:
                forms.add(f"{n}x{t}")
    else:
        for n in names:
            for t in _squares(move.to_square, color):
                forms.add(f"{n}-{t}")
    if move.promotion:
        forms = {f + f"={PIECE_LETTER[move.promotion]}" for f in forms}
    return forms


def descriptive_lookup(board):
    """{spelling: move} for the spellings that name exactly one legal move (ambiguous spellings are dropped)."""
    seen, dup = {}, set()
    for mv in board.legal_moves:
        for f in descriptive_forms(board, mv):
            if f in seen and seen[f] != mv:
                dup.add(f)
            seen[f] = mv
    return {f: m for f, m in seen.items() if f not in dup}


_FILE = r"(?:QR|QKt|QN|QB|Q|KB|KKt|KN|KR|K)"
_PIECE = r"(?:[QK]?(?:Kt|N|B|R)P?|[QK]?P|Q|K)"
_TARGET = rf"(?:(?:{_FILE}|Kt|N|B|R)\s{{0,2}}[1-8]|{_PIECE})"
DESC = re.compile(rf"(?:O\s?-\s?O\s?-\s?O|O\s?-\s?O|0-0-0|0-0|{_PIECE}\s*[-x–—]\s*{_TARGET}(?:\s?[=(]\s?[QRBN]\)?)?)")
ALG = re.compile(r"(?:O-O-O|O-O|0-0-0|0-0|[KQRBN][a-h]?[1-8]?[x:]?[a-h][1-8]|[a-h](?:[x:][a-h])?(?:[18](?:=?[QRBN])?|[2-7]))")
_NOISE = re.compile(r"(?:(?:dis\.?\s*ch\.?|ch\.?|e\.p\.|[+#!?])\s*)+")
_SPACED_FILE = re.compile(r"\b([QK])\s+(?=(?:Kt|N|B|R)\s*\d)")
_SPACED_PIECE = re.compile(r"\b([QK])\s+(Kt|N|B|R)(?=\s*(?:P\b|[-x\u2013\u2014]))")


def tidy(text):
    """Bring the older verbose style ("P. to K.'s 4th", "Kt. to K B 3rd", "P. takes P.") to the compact one ("P-K4", "Kt-KB3", "PxP")."""
    t = GL.normalise_figurines(text)                                              # figurine pieces to letters
    t = re.sub(r"['\u2019]s\b", "", t)                                        # K's -> K
    t = re.sub(r"\b(P|Kt|B|R|Q|K|N)\.", r"\1", t)                                # P. Kt. B. -> P Kt B
    t = re.sub(r"(?<=\d)(?:st|nd|rd|th)\b", "", t)                               # 4th -> 4
    t = re.sub(r"(?<=[A-Za-z])\s+to\s+(?=(?:[QK]|Kt|N|B|R)\s*[A-Za-z]{0,2}\s*\d|[QK]\s*\d)", "-", t)   # P to K 4 -> P-K 4
    t = re.sub(r"\btakes\b", "x", t)
    return t


def _canon_desc(tok):
    t = re.sub(r"\s+", "", tok).replace("–", "-").replace("—", "-").replace("0-0", "O-O")
    t = t.replace("Kt", "N").replace("KKt", "KN")
    t = re.sub(r"\((\w)\)", r"=\1", t)
    return t


def _next_move(text, board, lookup):
    """Try to read one legal move at the start of `text`. Returns (move, chars used) or None."""
    for rx in (DESC, ALG):
        m = rx.match(text)
        if not m:
            continue
        tok = m.group(0)
        if rx is DESC:
            mv = lookup.get(_canon_desc(tok))
        else:
            clean = tok.replace(":", "x").replace("0-0", "O-O").replace(" ", "").replace("=", "")
            try:
                mv = board.parse_san(clean if not re.search(r"[a-h][18][QRBN]$", clean) else clean[:-1] + "=" + clean[-1])
            except ValueError:
                mv = None
        if mv is not None:
            return mv, m.end()
    return None


_SKIP = re.compile(r"^(?:\s|\d+\s*\.(?:\s*\.\s*\.)?|\.\.\.|…|,|;|-|\.)+")


def parse_line(text, board=None, glyphs=None):
    """The legal moves at the start of `text` (numbers, spaces and commas skipped), stopping at the first non-move. Returns
    (list of SAN strings, chars consumed). If a list is passed as `glyphs`, the marks after moves are appended to it as
    (index of the move, NAG): `Nf3!` -> (k, 1)."""
    board = (board or chess.Board()).copy()
    text = _SPACED_PIECE.sub(r"\1\2", _SPACED_FILE.sub(r"\1", tidy(text)))   # "K B 3" -> "KB 3", "Q B P" -> "QBP"
    out, pos = [], 0
    while True:
        m = _SKIP.match(text[pos:])
        p = pos + (m.end() if m else 0)
        lookup = descriptive_lookup(board)
        got = _next_move(text[p:], board, lookup)
        if got is None:
            break
        mv, used = got
        out.append(board.san(mv))
        board.push(mv)
        pos = p + used
        n = _NOISE.match(text[pos:].lstrip())
        if n and glyphs is not None:
            glyphs.extend((len(out) - 1, g) for g in GL.marks_after_move(n.group(0).lstrip()))
        if n:
            pos = len(text) - len(text[pos:].lstrip()) + n.end()
    return out, pos


START = re.compile(r"(?<![\d.])1\s*\.\s*(?=[A-Za-z0O])")


def find_lines(text, min_plies=4):
    """Game lines that start at the initial position: [{"start": offset, "moves": [SAN...], "glyphs": [(move index, NAG)],
    "notation": "algebraic" | "descriptive"}]."""
    lines = []
    for m in START.finditer(text):
        seg = text[m.end(): m.end() + 1500]
        marks = []
        moves, used = parse_line(seg, glyphs=marks)
        if len(moves) >= min_plies:
            rest = seg[:used]
            lines.append({"start": m.start(), "moves": moves, "glyphs": marks,
                          "notation": "descriptive" if DESC.match(rest.lstrip()) else "algebraic"})
    return lines


# ---- prose -----------------------------------------------------------------------------------------------------------

LEXICON = {
    "outpost": r"outpost", "weak_squares": r"weak (?:square|point|complex)|hole\b", "isolated_pawn": r"isolated (?:pawn|queen)",
    "passed_pawn": r"passed pawn", "backward_pawn": r"backward pawn", "pawn_chain": r"pawn[- ]chain",
    "open_file": r"open file|half[- ]open", "seventh_rank": r"seventh rank|7th rank", "prophylaxis": r"prophyla",
    "overprotection": r"overprotect", "blockade": r"blockad", "minority_attack": r"minority attack", "initiative": r"initiative",
    "tempo": r"\btempo|\btempi", "development": r"\bdevelop", "centre": r"\bcent(?:er|re)\b", "king_attack": r"attack (?:on|against) the king|king'?s? attack|mating attack",
    "sacrifice": r"sacrific", "bishop_pair": r"two bishops|bishop pair|pair of bishops", "good_bad_bishop": r"(?:good|bad) bishop",
    "zugzwang": r"zugzwang", "fork": r"\bfork", "pin": r"\bpin(?:ned|s|ning)?\b", "discovered": r"discovered (?:check|attack)", "mobility": r"mobility",
    "space": r"\bspace\b|cramp", "opposition": r"opposition", "exchange": r"exchange (?:sacrifice|the)|win the exchange", "combination": r"combination",
    "endgame": r"end[- ]?game|ending", "simplification": r"simplif", "strategy": r"strateg|plan\b",
}
_LEX = {k: re.compile(v, re.I) for k, v in LEXICON.items()}


def concept_counts(paragraph):
    """{concept: number of matches} for the concepts that occur in a paragraph."""
    return {k: n for k, rx in _LEX.items() if (n := len(rx.findall(paragraph)))}


def paragraphs(text):
    """Blank-line separated paragraphs with line breaks joined (hyphenated line ends rejoined)."""
    out = []
    for p in re.split(r"\n\s*\n", text):
        p = re.sub(r"-\n(?=[a-z])", "", p)
        p = re.sub(r"\s*\n\s*", " ", p).strip()
        if p:
            out.append(p)
    return out


def strip_gutenberg(text):
    """The book itself: without Project Gutenberg's header and licence footer."""
    a = re.search(r"\*\*\* ?START OF (?:THE|THIS) PROJECT GUTENBERG EBOOK[^\n]*\n", text)
    b = re.search(r"\*\*\* ?END OF (?:THE|THIS) PROJECT GUTENBERG EBOOK", text)
    return text[a.end(): b.start()] if a and b else text


def analyse_book(text, min_plies=4):
    """{"paragraphs", "lines", "notation": {algebraic, descriptive}, "concepts": {concept: paragraphs}, "concept_with_moves": {...}}:
    which concepts the prose mentions, and which of those paragraphs also give a game line (the material for weak supervision)."""
    paras = paragraphs(text)
    lines = find_lines(text, min_plies)
    concepts, with_moves = {}, {}
    for p in paras:
        cc = concept_counts(p)
        has = bool(START.search(p) and find_lines(p, min_plies))
        for k in cc:
            concepts[k] = concepts.get(k, 0) + 1
            if has:
                with_moves[k] = with_moves.get(k, 0) + 1
    return {"paragraphs": len(paras), "lines": lines,
            "notation": {n: sum(1 for l in lines if l["notation"] == n) for n in ("algebraic", "descriptive")},
            "concepts": concepts, "concept_with_moves": with_moves}


def concept_line_pairs(paras, window=2, book=None):
    """Game lines from the initial position, each with the concepts the prose mentions in the same paragraph and in the `window`
    paragraphs before and after it (books put the explanation and the moves in neighbouring paragraphs)."""
    pairs = []
    for i, p in enumerate(paras):
        if not START.search(p):
            continue
        lines = find_lines(p)
        if not lines:
            continue
        near = {}
        for j in range(max(0, i - window), min(len(paras), i + window + 1)):
            for k, n in concept_counts(paras[j]).items():
                near[k] = near.get(k, 0) + n
        if near:
            pairs.append({"book": book, "paragraph": i, "concepts": near, "moves": lines[0]["moves"], "glyphs": lines[0]["glyphs"],
                          "notation": lines[0]["notation"],
                          "text": " ".join(paras[max(0, i - window): i + window + 1])[:2400]})
    return pairs
