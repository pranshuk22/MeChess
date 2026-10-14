# Running on Kaggle

Fourteen notebooks, on purpose. Collecting text and counting openings are CPU work and do **not** use the weekly GPU quota; only training and labelling do.
Each notebook is an **adapter**: it clones the repository, installs a few packages and runs `chessme` commands, nothing else. All the logic
(resuming from earlier output, linking inputs, checkpoints, time budgets) is in the repository, tested, and runs the same on a laptop; the
Kaggle-specific parts are in `chessme/kaggle.py` and the `--input-root`, `--data-dir`, `--resume-glob` and `--slim` flags.

| Notebook | Accelerator | What it does | Expected cost |
|---|---|---|---|
| `notebooks/1_collect_data_cpu.ipynb` | **None** | preflight, then `chessme books-learn`: 100+ books, all annotated-game sources, Stack Exchange, Wikipedia, opening names | CPU only; roughly 1 to 2 hours (about 300 MB of downloads) |
| `notebooks/2_train_language_model_gpu.ipynb` | **GPU** | preflight (GPU, dependencies, model download, data), a dry-run of the whole training path, then the real run with a time budget | about 105 minutes for 3 epochs of `distilroberta-base` on a T4 or P100 (measured) |
| `notebooks/3_opening_explorer_cpu.ipynb` | **None** | streams a Lichess database month (CC0) and builds the opening explorer for every rating range, a theory book per band and a report ([details](opening-explorer.md)) | hours; checkpointed, with a time budget |
| `notebooks/4_label_comments_gpu.ipynb` | **GPU** | `chessme books-nlp-label`: labels every annotated move's comment with the trained model (concepts, verdict, who stands better) and writes a report; trial on 2,000 moves first | needs the outputs of notebooks 1 and 2 as inputs; the GPU part is short (measured on a laptop CPU with 4 threads: about 115 short comments per second, so a few hundred thousand comments take under an hour even without a GPU; longer comments are slower) |
| `notebooks/5_opening_explorer_rangescan_cpu.ipynb` | **None** | the same explorer as notebook 3, built by `explorer-range-scan`: the dump is cut into about 700 byte windows scanned four at a time over range requests and added up exactly (no 17-minute reconnect problem; [details](opening-explorer.md)) | hours (about 3 to 6 expected); the windows (about 31 GB) live in `/kaggle/temp`, only the merged result is output |
| `notebooks/6_humanlike_testset_cpu.ipynb` | **None** | builds the two test sets of the human-likeness study: ours (24 windows of a month after Maia-3's training data, balanced over rating) and the Allie set with the published filter | about 2 hours on 4 cores (parsing clocked games is the cost) |
| `notebooks/7_humanlike_score_gpu.ipynb` | **GPU** | downloads Maia-3 (code and 5M / 23M / 79M weights, external) and scores them on both sets, then writes the reports; `MAIA2 = True` also scores Maia-2 (blitz) as a second model family (its package downloads and checks its own weights) | needs notebook 6's output as an input; board encoding in Python is the bottleneck, so four worker processes share the GPU |
| `notebooks/8_humanlike_judge_cpu.ipynb` | **None** | downloads a pinned Stockfish release (external) and judges the human's move and Maia-3's most probable moves on a test sample and a training sample (disjoint games), then writes the error-profile report | needs notebooks 6 and 7's outputs as inputs; about 7 positions per second per three processes, so a 100k-position run takes hours |
| `notebooks/9_humanlike_selfplay_gpu.ipynb` | **GPU** | trains the clock adapters on frozen Maia-3 23M (using notebook 8's Stockfish labels) and lets the frozen and the adapted models play games from the positions, clocks and ratings of real test games | needs the outputs of notebooks 6, 7 and 8; about an hour |
| `notebooks/10_humanlike_humangames_cpu.ipynb` | **None** | `chessme humanlike-humangames`: fetches the real continuation (moves, clocks) of up to 20,000 starting positions of notebook 6's test set from the public Lichess games export, the human side of the comparison with notebook 9's generated games | needs notebook 6's output; Internet on; about ten minutes |
| `notebooks/11_humanlike_generate_gpu.ipynb` | **GPU** | `chessme humanlike-selfplay --starts-from`: Maia-3 (frozen, or with one of notebook 9's adapters) plays the same starting positions as notebook 10's human games, against itself; then `humanlike-gamestats` against the real continuations | needs the outputs of notebooks 6, 7, 9 and 10; about 20 minutes per 1,000 games; `TEMPERATURE` (default 1) sharpens or flattens the model on purpose for the dose-response control |
| `notebooks/12_humanlike_c2st_cpu.ipynb` | **None** | `chessme humanlike-c2st`: can a classifier tell the human games of notebook 10 from the generated games of notebook 11 (same starts, moves only)? AUC per generated set, paired differences, human-against-human control | needs the outputs of notebooks 10 and 11; minutes. `ENGINE_FEATURES = True` adds Stockfish-judged move quality (external download, GPL-3.0): about an hour on four processes |
| `notebooks/13_humanlike_arena_cpu.ipynb` | **None** | `chessme humanlike-arena`: matches between Stockfish at node limits (the ladder) and the human-like bot (Maia-3 prior reweighted by the engine's losses), from the opening moves of real games, adjudicated by a referee engine; Elo with intervals; resumable | needs notebook 10's output; Maia-3 and Stockfish are downloaded; hours (bot games are the cost) |
| `notebooks/14_humanlike_confirm_cpu.ipynb` | **None** | `chessme humanlike-confirm` and `humanlike-scaling`: the frozen models and the already trained adapters (not refitted) on a NEW test set built from other windows of the same month, judged by Stockfish: blunder gaps by clock regime, likelihood changes, the gap against model size | needs the outputs of notebooks 6 to 8 for both test sets and of notebook 9; minutes |

## How to run

1. Settings: *Internet -> On* (phone verification once). Notebook 2: *Accelerator -> GPU*; the others: *None*.
2. Put your repository URL in `REPO_URL` (first code cell). Notebook 5 can instead take the repository as an attached dataset (a folder containing `chessme/`).
3. **Save Version -> Save & Run All (Commit)**. A committed run does not depend on your browser, may run up to 12 hours, and keeps its output.
   An interactive session can be lost.
4. Notebook 2 needs notebook 1's output: *Add Input -> Notebook output files*. Set `DATA_DIR` to that output's folder (something like
   `/kaggle/input/notebooks/<your-username>/<notebook-name>`) or leave it empty to search everything under `/kaggle/input`. The notebook prints an
   **inventory** of what it found and stops if an expected source has no examples. The archives (`.tar.gz`) were read by notebook 1; their content is
   in `annotated_moves.jsonl.gz`.
5. To **continue** a run (notebooks 2, 3 and 4), add the notebook's own earlier output as an input and run it again: the checkpoint is restored.

Notebook 4 takes **two** inputs, the output of notebook 1 (the data) and of notebook 2 (the model, found as `nlp/model.pt` with `config.json`; a
model folder can be named with `MODEL_DIR`). It stops at once, before using the GPU, if either is missing. Its progress is saved every 2,048 moves, so an
interrupted or time-limited run continues exactly where it stopped (add its own earlier output as an input); the finished file is identical to an uninterrupted run.
The same on a laptop: `python -m chessme books-nlp-label --data data/books_learn --model-dir <model folder>`.

## What protects the quota

- `books-preflight` runs first and stops within a minute if a dependency, the disk, the GPU, a download URL or the model is unavailable. Tested: on
  a machine without a GPU, notebook 2 refuses at preflight with "turn on Settings -> Accelerator".
- Notebook 2 then runs a **dry-run** (a few examples, the same code path) that also fails unless the loss falls on 64 memorisable examples.
- The real run has a **time budget**: at the deadline it saves a checkpoint and ends normally, so the output is kept. Training also stops early
  after several validations without a new best model.
- Notebook 3 checkpoints every million games and every 15 minutes, guards memory, reconnects if the stream drops, and keeps its counts so
  `explorer-rebuild` can regenerate its outputs with other thresholds without streaming again.
- Training is resumable, and a resumed run gives the same result as an uninterrupted one (tested).

## Lessons from the first real runs

- A **committed** run keeps its output only if it finishes, so every long job has a time budget that ends it before Kaggle's 12-hour limit.
- The second explorer run (11 hours) stopped at 31.5 million games: every connection lasts about 17 minutes and a reconnect re-reads the file from the start (details in [opening-explorer.md](opening-explorer.md)). The first run ended silently after about an hour at 4% of its plan; the likely cause was the download connection closing. The reader
  now detects a short download and reconnects (see [opening-explorer.md](opening-explorer.md)).
- The log of a GPU run is worth reading while it runs: the first version showed a noisy total loss that hid the real signals, so the log now shows
  each head's loss and a validation check every 1,000 steps.

## Getting the output onto your machine

```bash
pip install kaggle          # a token in ~/.kaggle/access_token (or kaggle.json)
kaggle kernels output <your-username>/<notebook-name> -p data/explorer_kaggle --file-pattern '^explorer/'
```

`--file-pattern` (a regular expression) skips the cloned repository that the notebook's working folder also contains.

## Terms

Public-domain books only. Annotated games keep the terms of their sources; Stack Exchange and Wikipedia text is CC BY-SA. Use the outputs for
research and learning; do not redistribute the text. Never publish a notebook or output that contains your own books' text.
