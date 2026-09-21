#!/bin/bash
# Low-priority checks that must not disturb a timing-sensitive calibration: waits (a cheap poll) until tools/after_calibration.sh has ended, then
#   1. the anchors through the game-level features and the embedding (network + light CPU)
#   2. a trial of the language-model labelling on the first 3,000 annotated moves (CPU; the report shows what the labels look like)
set -u
cd "$(dirname "$0")/.."
PY=.venv/bin/python
LOG=data/style/logs/after_calibration_checks.log
say() { echo "$(date +%H:%M:%S) $*" | tee -a "$LOG"; }
while pgrep -f "tools/after_calibration.sh" > /dev/null; do sleep 60; done
say "1/2 anchors: fetch the games and compute the game-level features"
$PY -m chessme style-anchors-games --max-games 100 >> "$LOG" 2>&1
say "anchors: report"
$PY -m chessme style-anchors-games-report --out data/style/anchors_games_report.md >> "$LOG" 2>&1
say "2/2 labelling trial (3,000 moves)"
OMP_NUM_THREADS=2 $PY -m chessme books-nlp-label --data data/books_learn/run --model-dir "${NLP_MODEL:-data/books_learn/run/nlp}" --limit 3000 --sample 40 \
    --out data/books_learn/labelled_trial/labelled.jsonl.gz --log data/books_learn/labelled_trial/label.log >> "$LOG" 2>&1
say "all done: data/style/anchors_games_report.md, data/books_learn/labelled_trial/label_report.md"
