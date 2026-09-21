# Opening explorer and theory books

Two related tools, both producing the `book.bin` format that the controller reads (`mechess --book PATH`).

| Tool | Built from | Gives |
|---|---|---|
| `theory-book` | the CC0 Lichess opening names plus the cohort's games | a small book of known theory for a rating band |
| `explorer-build` | a Lichess database month (CC0), streamed | an **opening explorer** (SQLite) for every rating range, plus one book per band |

## What the explorer collects

The Lichess database dump is streamed (the 30 GB file is never downloaded whole) and, for the first **24 plies** of every qualifying game, the
counts per **(rating band, position, move)** are kept.

**A game counts when** it has both ratings and a result, a normal ending (mate, resignation, draw, time forfeit), is not ultra-bullet (base time
of at least 30 s; bullet and faster-than-bullet-but-not-ultra games are counted, because above 2400 they are most of what is played), and the
two ratings are within 300 points. Its band is the average rating. **Bands** cover every range: under 800, 200-point bands to 2600, and 2600+.

**Counts are exact, never sampled.** Every qualifying game is counted until its band holds `--max-per-band` games (default 1,000,000). Dense
bands fill early in the scan and stop; rare bands (under 800, 2400 and up) collect over the whole scan, so **each band has its own window**, and
the report states it. The first 1,000 games of each band are kept aside to measure book coverage honestly and are added to the counts
afterwards. Thresholds scale with the size of the band (a dense band ignores more noise than a thin one).

## Output

| File | Format | Content |
|---|---|---|
| `explorer.db` | SQLite | `moves`: per band, position and move: games, White wins, draws, Black wins, average rating, average engine evaluation from annotated games (with the number of games it rests on), and the **top game** (the highest-rated game that played the move, a public Lichess id, first 12 plies). `positions`: the true number of games that reached each position, so moves below the minimum are reported as "other moves". Also `bands` (with each band's window), `band_stats` (results, game length, games with an engine evaluation), `speed_mix`, `clock` (per band, speed and ply: moves, seconds spent, instant moves), `population` (every scanned game before any filter, by band, speed and ending), `rating_hist` (50-point bins), `openings` (3,815 names by position), `meta` |
| `theory_LO_HI.bin` | `book.bin` | one playable book per band: a move is kept with at least max(20, 0.005% of the band's games) games and 3% of its position; `mechess --book DIR --elo N` picks the band of the target Elo |
| `report.md` | Markdown | windows and counts per band, book coverage on held-out games, results, game length, speed and ending mix, time per move |
| `state.pkl.gz` | gzip + pickle | the full unthresholded counts (the checkpoint); `explorer-rebuild` regenerates the three files above from it with other thresholds without streaming again. It is a Python pickle: load only your own files |

Players' names and dates are never stored, only public game ids, ratings and counts.

## Commands

```bash
python -m chessme explorer-build --check                       # read 300 games: tests the URL, decompression and parsing in seconds
python -m chessme explorer-build --out data/explorer           # the long run (resumable)
python -m chessme explorer-query data/explorer/explorer.db --rating 1500 --fen "<FEN>"
python -m chessme explorer-rebuild data/explorer/state.pkl.gz --book-min-games 10   # other thresholds, no streaming
python -m chessme theory-book --download --out data/book/theory_1500_1800.bin --games data/style/cohort2 --band 1500 1800
```

`explorer-query` prints, per move: games, share, average rating, engine evaluation and the White / draw / Black bar (`░ ▒ █`), then the top
game link of each move.

## Robustness

- **Checkpoints** every million games and every 15 minutes (atomic; refused if the settings changed). Stop and resume with the same command
  (`chessme control stop explorer`, or Ctrl-C); on Kaggle add the earlier output as an input (`--resume-glob`).
- **The stream** is re-opened and fast-forwarded if the connection drops. A download that ends before the size the server promised raises an
  error instead of looking like the end of the file, and a stream that ends before `--max-scan` prints a warning and is flagged in the report.
- **Memory** is bounded: past `--max-entries` (60 million) or `--max-memory-gb`, the rarest entries are pruned, and the report and the database
  record that entries with at most N games may be missing.

## Sizes (measured on a first real run, then estimated)

The first Kaggle run scanned 4.0 million games (3.83 million counted): 47 million entries, 7.2 GB of memory, a 66 MB database (731,000 rows) and an
848 MB checkpoint. Games are not stored, so the size follows the number of *distinct positions*, which saturates: at the full scan the
checkpoint should stay near 1.1-1.5 GB (the entry cap) and the database at a few hundred MB (**estimates**; growth was measured only up to 47
million entries).

## Known issue from the first run

That run ended after about 62 minutes at game 4,025,876, silently, out of a planned 100 million. Reading the file locally with the same code went
past 4.3 million games, so the file is fine; the likely cause is the download connection closing (Python's HTTP client returns an empty read on
an early close). The reader now detects a short download and reconnects; **this has been tested with simulated drops and a truncated
download, not against a real hourly disconnect**. The run's counts are exact for the games it did scan, and the checkpoint is compatible: rerunning
with the earlier output as an input resumes from game 4,025,876.

## Limits

- Speeds are merged in the move counts (the speed mix and clock use are kept separately); per-speed opening tables are not stored.
- Only about 9-15% of games carry engine evaluations, so the average evaluation of a rare move rests on few games (the count is shown).
- Popularity is not soundness: a low-rated band's book contains the weak moves people really play. `--eval-margin` can drop moves whose average
  evaluation is clearly worse than the best sibling's, when enough annotated games exist.
