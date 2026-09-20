#!/bin/bash
# Analyse fetched cohort players with Stockfish while the fetch (pid $1) is still running, then once more at the end.
# Each pass only does players without a candidate file yet, so it is safe to repeat.
fetch_pid=$1
run() { .venv/bin/python -u -m chessme style-cohort-analyze --engine stockfish --workers "${2:-4}" --out data/style/cohort; }
while kill -0 "$fetch_pid" 2>/dev/null; do run; sleep 90; done
run
echo "cohort analysis finished"
