# Books, annotated games and the chess-text language model

Chess books and annotated games say *why* moves are good. This part of MeChess collects that text, reads the game lines and glyphs in it, and
trains a small language model on it. Everything is a `chessme` command (also runnable on Kaggle: see [kaggle.md](kaggle.md)); the code is in
`chessme/books/`.

## What is collected (`chessme books-learn`)

| Source | What it is | Terms |
|---|---|---|
| 103 public-domain books and periodicals | Project Gutenberg and Internet Archive OCR text: instruction, openings, annotated tournament books, chess magazines (`chessme/books/sources.json`, every entry checked to exist) | public domain (check per country; modern books are not used) |
| Annotated games | GameKnot, PGN Library, Path to Chess Mastery and Lichess studies (from the ChessGPT "free" archive), the larger ChessGPT annotated-PGN shards, the CC0 `chess_studies` dataset | each source keeps its own terms: research and learning use, do not redistribute |
| Explanations in prose | the chess Stack Exchange (questions and answers) and chess Wikipedia articles (ChessGPT data) | CC BY-SA |
| Opening names | Lichess chess-openings | CC0 |

Steps (each skips finished work): `books` (download and read), `pairs` (game lines with the concepts mentioned near them), `annotated`, `prose`,
`report`. The result is `annotated/annotated_moves.jsonl.gz` (one record per annotated move: the position before it, the move, all glyphs, the
comment, the concepts it mentions, a game id, average rating, opening code and result; **never player or annotator names**), `prose/`, `books/`
and a `report.md`.

## Reading chess text

- **Notation**: algebraic; descriptive (`P-K4`, `Kt-KB3`, with the spacing and abbreviation variants of Gutenberg and OCR text); the older verbose
  style (`P. to K.'s 4th`); figurines (`♘f3`). Every candidate move is **checked for legality**, and a line ends at the first token that is not
  a legal, unambiguous move, so OCR junk simply fails to parse. Only lines from the initial position are read (other examples start from a
  diagram, which needs diagram recognition first).
- **Glyphs** (`glyphs.py`): every NAG number with its symbol, meaning and kind (move judgement `! ? !! ?? !? ?! □`, position evaluation
  `= ∞ ⩲ ⩱ ± ∓ +− −+`, zugzwang, counterplay, time pressure, novelty), the same symbols written inside comments (`Nf3!`, `±`), and marks after
  book moves.
- **Concepts**: a lexicon of 32 strategic concepts (outpost, prophylaxis, zugzwang, minority attack, ...) counted in prose and comments.

Measured on the first 12 public-domain books, the reader extracts game lines from 9 of them (about 650 lines in all); the other three (Steinitz,
Znosko-Borovsky, *Chess and Checkers*) use layouts it does not read yet, and most examples in books start from diagrams. Treat the extracted lines as a small, precise sample, not a corpus of all book moves.

## The model (`chessme books-nlp-train`)

One shared text encoder, three heads, trained together on comments and prose (`chessme/books/nlp.py`):

| Head | Predicts | Labels come from |
|---|---|---|
| Concepts | which of the 32 concepts a text discusses (multi-label) | the lexicon, but **the keywords are masked in the input**, so the model must infer the concept from context |
| Judgement | the annotator's verdict on the move: `!! ! !? ?! ? ??` | the glyph on that move (about 3-10% of annotated moves) |
| Evaluation | who stands better and by how much (7 classes) | the evaluation glyph on that move |

**Input** is one comment or paragraph (25-1,200 characters, English) and **only the text**: the model does not see the board or the move.

**Encoders**: `bow` (hashed word and bigram embeddings, small, runs anywhere) and `transformer` (any Hugging Face encoder; default
`distilroberta-base`, mean-pooled, 128 tokens; GPU for real use). Examples are split by game or document, so no game is on both sides.

**Steady training** (each measure was added after watching a real run):
- the learning rate warms up over the first 6% of the steps and decays linearly; gradients are clipped, and a non-finite gradient never reaches the
  weights; the heads train at a higher rate (1e-3) than the pretrained encoder (3e-5);
- every batch contains a fixed number of glyph-labelled examples (default 4), because the glyph heads otherwise see about two labelled examples
  per batch and the loss swings; dropout 0.2 before the heads;
- a validation check every 1,000 steps (concept average precision against a random ranking, judgement and evaluation accuracy against the
  majority guess) and per epoch; the model kept is the **best validated** one (a composite of the three heads), and the best model on concepts
  alone is kept separately when it is a different step (`--variant concepts`);
- **early stopping** (`--patience`, default 4 validations without a new best) and a wall-clock budget (`--deadline-minutes`) that saves a checkpoint
  and ends normally; training resumes from the checkpoint;
- a **dry-run** (`--dry-run`) that runs the whole path in about a minute and fails unless the loss falls on 64 memorisable examples.

## Results so far

Two Kaggle runs of the transformer model on the full collected data (about 630,000 examples):

| Run | Concept AP (random 0.008-0.010) | Judgement accuracy (majority 0.33) | Evaluation accuracy (majority 0.25) |
|---|---|---|---|
| First (constant learning rate), end of epoch 3 | 0.212 | not measured in the log | not measured in the log |
| Steady version, validation at step 17,000 of 27,141 | 0.431 | 0.724 | 0.460 |

Two full runs on one GPU (3 epochs, the same data and split; test set of 63,256 examples):

| Test | Run A: 8 labelled examples per batch, no dropout, last step kept (105 min) | Run B: 4 labelled per batch, dropout 0.2, best step kept (97 min) | Baseline |
|---|---|---|---|
| Concepts, average precision (macro) | **0.472** | 0.388 | 0.008 (random) |
| Concepts, F1 micro / macro, tuned thresholds | **0.668 / 0.476** | 0.612 / 0.402 | 0.000 (prior only) |
| Judgement glyph, accuracy / macro F1 | 0.718 / 0.627 | 0.724 / 0.640 | 0.329 (majority) |
| Evaluation, accuracy / macro F1 | 0.408 / 0.371 | 0.418 / 0.392 | 0.245 (majority) |

Run B's changes reduce memorisation in the glyph heads (their training loss stays near 0.2 instead of near 0), but that did **not** buy better held-out
glyph accuracy: the differences (+0.006 judgement, +0.010 evaluation) are inside the noise (the evaluation set has only 181 validation examples), while the
concept head, the useful one, is clearly worse (average precision 0.388 against 0.472; it was still rising when the learning rate ran out). The
model kept is **Run A**, in `data/books_learn/run/nlp` locally. Early stopping did not trigger in either run.

How to read it: the concept head is the useful part. The judgement head has stayed at about 0.72
in every run, so text alone appears to cap it there. The evaluation head is at 0.41 to 0.42 and cannot be told apart from run to run; do not rely on it. The concept and judgement labels are weak (lexicon and glyph based), so these numbers measure agreement with those
labels, not chess understanding. Test metrics on the concept head with the keywords left visible are near zero (0.004) because the model was never
trained on unmasked text; that figure is a distribution mismatch, not a quality measure.

## What it is for, and not for

The model reads text. It helps to (1) tag large amounts of prose with concepts, (2) pick and rank explanations to quote in game reports, and (3)
provide human move judgements as labels. It does **not** judge a move by itself (it never sees the position), does not make the engine stronger, and
its concept labels can only be as good as the 32-concept lexicon. The position-to-concept model that would use these labels is planned, not built; the labels for it are made by the next command.

## Labelling annotated moves (`chessme books-nlp-label`)

Every annotated move with a readable comment (25+ characters, English) becomes a labelled example: the position (FEN), the move, and

| Field | Meaning |
|---|---|
| `concepts_lexicon` | concepts whose keywords the comment contains (high precision, low recall) |
| `concepts_model` | concepts the model finds from context: it is given the comment **with the keywords hidden** (it was trained that way; shown the keywords it predicts nothing) |
| `concepts` / `model_only` | the union, and what only the model found (the part to check by eye) |
| `judgement`, `evaluation` (+ `_conf`) | the verdict and the evaluation class the comment implies, with the model's probability |
| `glyph`, `eval`, `source`, `game` | the human glyph and evaluation symbol where the source had them, the source and a public game id; no player or annotator names |

The command is streaming and resumable (progress every 2,048 moves; a cut-off write is discarded and the finished file equals an uninterrupted run),
takes `--limit` for a trial and `--deadline-minutes` for a time budget (exit code 3 = paused, run it again), and writes `label_report.md` and
`label_stats.json` next to the output: per concept how often the lexicon and the model find it and how well the model finds what the lexicon finds,
the judgement head against the human glyphs (the glyph is not an input), and a sample of model-only concepts to read. **Read that sample before using
the labels**: they are weak labels, and only a check by eye tells whether the model-only concepts are real. The Kaggle version is
[notebook 4](kaggle.md).

## Other commands

`books-fetch` (books only), `books-studies` (export public Lichess studies by author or id; one request at a time), `books-pdf` (PDFs you own,
text layer only), `books-topics` (cluster paragraphs into topics; needs `sentence-transformers`), `books-nlp-predict`, `books-nlp-report`,
`books-preflight` (dependencies, disk, every download URL, GPU: run it before anything long).
