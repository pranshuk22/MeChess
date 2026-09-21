# Resources for learning from annotated games and books

What we can read, what it is good for, and under what terms. **Verified** = the page or file was opened and checked (date in the
row); **[A]** = seen in a paper abstract or search result only, to be verified before use. Nothing here is a licence: check the terms
of each source before you use or share anything derived from it.

## Public-domain books (text)

Listed in [`chessme/books/sources.json`](../chessme/books/sources.json); `chessme books-fetch` downloads and reads them.

| Book | Where | Notation | Status |
|---|---|---|---|
| Capablanca, *Chess Fundamentals* (1921) | Project Gutenberg #33870; Internet Archive `chessfundamental00capa` | descriptive (`P - K 4`, `Kt-B3`) | verified 2026-09-21; 22 lines from the start position extracted |
| E. Lasker, *Chess Strategy* | Gutenberg #5614; Archive `chessstrategy00lask` | descriptive | verified; 58 lines |
| E. Lasker, *Chess and Checkers* | Gutenberg #4913 | descriptive | listed |
| Nimzowitsch, *My System* (1925) | Archive `nimzowitsch-my-system` (public-domain mark in its metadata) | algebraic, OCR errors (`NiS` for `Nf6`) | verified; the download server answered 500 once, so the fetcher retries |
| Em. Lasker, *Manual of Chess*; *Common Sense in Chess* | Archive `lasker-s-manual-of-chess`, `commonsenseinche00laskrich` | descriptive | listed |
| Znosko-Borovsky, *The Middle Game in Chess* | Archive `middlegameinches00znos` | descriptive | listed |
| Steinitz, *Modern Chess Instructor*; Morphy's games; Young, *Grand Tactics*; Staunton, *Blue Book* | Archive / Gutenberg (see sources.json) | descriptive | listed |
| Tartakower, *Die hypermoderne Schachpartie* | Archive `diehypermodernes00tart_0` | German | listed; needs a German parser |

Copyright depends on the country and on the author's death date; US pre-1929 publication is public domain in the US, but other
countries use life-plus-70 years (Edward Lasker died in 1981). Check before relying on a work outside the US. **Modern books are not
used** (Silman, Dvoretsky, Kasparov, ...): they are copyrighted and must not be copied, stored in the repository, or redistributed.

## Annotated games

| Source | What it holds | Terms | Status |
|---|---|---|---|
| Lichess open database (`database.lichess.org`) | every rated game, with evaluations for a part of them | CC0 | verified |
| Lichess studies | user-annotated games with comments, variations and glyphs; exportable through the API | user-generated: **check the terms before bulk use** | [A] |
| GameKnot commentary corpus (Jhamtani et al., ACL 2018) | about 11,500 games, about 298,000 move-comment pairs | not stated in the paper: **check** | [A] |
| ChessGPT data builders (Feng et al., NeurIPS 2023) | scripts that build corpora from `pathtochessmastery`, `pgnlib`, `gameknot`, `lichess_studies` | code Apache-2.0; each data source has its own terms | [A] (code licence verified earlier) |
| Concept-guided commentary (CCC, NAACL 2025) | engine-derived concepts verbalised for explanations | paper | [A] |

## Chess diagrams (pictures of positions) in scanned books

| Tool | Licence | Notes |
|---|---|---|
| `notnil/fenify` | MIT (verified) | targets chess-book images; the author reports 99.8% per-square accuracy [A]; last push 2023 |
| `tsoj/Chess_diagram_to_FEN` | MIT (verified) | pretrained models available; recently maintained (2026) |

Until a diagram model is in the pipeline we read only game lines that start from the initial position; lines that start from a
diagram need its FEN.

## Reading PDFs

- A PDF with a **text layer**: `pypdf` (BSD) extracts it. (PyMuPDF is AGPL: mind the licence before shipping it.)
- A **scan** (an image per page): OCR with Tesseract (Apache-2.0) through `ocrmypdf`; the Internet Archive also publishes ready OCR
  text (`*_djvu.txt`), which is what we use for public-domain books, so we do not OCR those ourselves.
- OCR is noisy (`NiS` for `Nf6`), which is why every move is checked for legality and a line ends at the first token that fails.

## What is integrated (checked 2026-09-21)

| Source | Status |
|---|---|
| 103 public-domain books and periodicals (`chessme/books/sources.json`) | every entry verified to have OCR text; of the first 12 all were read and 9 gave game lines (three use layouts the reader does not parse yet) |
| ChessGPT "free" annotated archive: GameKnot (12,769 games), PGN Library, Path to Chess Mastery, Lichess studies | integrated (`books-learn`) |
| ChessGPT annotated-PGN shards (2 x 87 MB, includes variations) | integrated; overlapping Lichess studies are dropped by study id |
| `Icannos/chess_studies` (CC0, about 3,000 annotated chapters) | integrated |
| ChessGPT Stack Exchange (30 MB) and Wikipedia (40 MB) subsets | integrated as prose (CC BY-SA; attribution list kept for Wikipedia) |
| Lichess chess-openings (3,815 named lines) | integrated (opening names, Book class, theory books) |
| Lichess database | integrated (the opening explorer) |
| Chess-diagram recognition (`fenify`, `Chess_diagram_to_FEN`, both MIT) | **not integrated**; lines that start from a diagram are skipped |
| `ChessInstruct` (instruction-tuning data, no commentary) | deliberately not used |

## The notebooks

See [kaggle.md](kaggle.md) for the three notebooks that run these steps on Kaggle, and [language-model.md](language-model.md) for what is read and
learned.
