"""Pack the Lichess chess-openings dataset (CC0; the TSV files a.tsv ... e.tsv with columns eco, name, pgn) into `chessme/opening_names.tsv.gz`: one line per named opening,
`eco <TAB> name <TAB> moves in UCI`. The app names the opening of any game from its moves with it (`chessme.openings_db`).

    python tools/build_opening_names.py data/opening_names"""
import gzip
import sys
from pathlib import Path

import chess

OUT = Path(__file__).resolve().parents[1] / "chessme" / "opening_names.tsv.gz"


def main(folder):
    rows = []
    for path in sorted(Path(folder).glob("*.tsv")):
        for line in path.read_text(encoding="utf-8").splitlines()[1:]:
            parts = line.split("\t")
            if len(parts) < 3:
                continue
            eco, name, pgn = parts[:3]
            board, ucis = chess.Board(), []
            try:
                for tok in pgn.split():
                    if tok[0].isdigit():
                        continue
                    ucis.append(board.push_san(tok).uci())
            except ValueError:
                continue
            rows.append((eco, name, " ".join(ucis)))
    with gzip.open(OUT, "wt", encoding="utf-8", compresslevel=9) as f:
        f.write("eco\tname\tuci\n")
        for r in rows:
            f.write("\t".join(r) + "\n")
    print(f"{len(rows)} openings -> {OUT} ({OUT.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "data/opening_names")
