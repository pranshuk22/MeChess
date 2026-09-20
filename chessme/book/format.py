"""Binary book file (see engine/src/book/book.h for the specification)."""
import struct
from dataclasses import dataclass

MAGIC = b"CMBK"
VERSION = 1
HEADER = struct.Struct("<4sIQ")
ENTRY = struct.Struct("<QBBBBfHH")  # key, from, to, promo, reserved, weight, games, score_permille


class BookFormatError(ValueError):
    pass


@dataclass(frozen=True)
class Entry:
    key: int
    from_sq: int
    to_sq: int
    promo: int  # 0, or a chess piece type 2..5 (knight..queen)
    weight: float
    games: int
    score_permille: int

    def uci(self):
        import chess

        s = chess.square_name(self.from_sq) + chess.square_name(self.to_sq)
        return s + (chess.piece_symbol(self.promo) if self.promo else "")


def write_book(path, entries):
    entries = sorted(entries, key=lambda e: (e.key, -e.weight, e.from_sq, e.to_sq, e.promo))
    with open(path, "wb") as f:
        f.write(HEADER.pack(MAGIC, VERSION, len(entries)))
        for e in entries:
            if not (0 <= e.from_sq < 64 and 0 <= e.to_sq < 64 and e.promo in (0, 2, 3, 4, 5)):
                raise BookFormatError(f"invalid move in entry: {e}")
            if not e.weight > 0:
                raise BookFormatError(f"entry weight must be positive: {e}")
            f.write(ENTRY.pack(e.key, e.from_sq, e.to_sq, e.promo, 0, e.weight, min(e.games, 65535),
                               min(max(e.score_permille, 0), 1000)))


def read_book(path):
    data = open(path, "rb").read()
    if len(data) < HEADER.size or data[:4] != MAGIC:
        raise BookFormatError("not a chessme book (bad magic)")
    _, version, count = HEADER.unpack_from(data)
    if version != VERSION:
        raise BookFormatError(f"unsupported book version {version}")
    if len(data) != HEADER.size + count * ENTRY.size:
        raise BookFormatError("book file is truncated or has trailing bytes")
    out, prev = [], -1
    for i in range(count):
        key, f, t, promo, _, weight, games, score = ENTRY.unpack_from(data, HEADER.size + i * ENTRY.size)
        if f > 63 or t > 63 or promo == 1 or promo > 5:
            raise BookFormatError(f"entry {i} is invalid")
        if not weight > 0:
            raise BookFormatError(f"entry {i} has a bad weight")
        if key < prev:
            raise BookFormatError("entries are not sorted by key")
        prev = key
        out.append(Entry(key, f, t, promo, weight, games, score))
    return out
