#!/bin/bash
# Anchors end to end: fetch archives -> sample peak-year decisions (archives deleted) -> Stockfish analysis.
# Logs: data/style/logs/anchors_fetch.log (timestamped, written by the fetch itself) and data/style/logs/anchors_analyze.log
set -e
.venv/bin/python -u -m chessme style-anchors-fetch --max-games 100 --per-game 10 --log data/style/logs/anchors_fetch.log
echo "=== analysis start $(date +%H:%M:%S)"
.venv/bin/python -u -m chessme style-cohort-analyze --out data/style/anchors --engine stockfish --workers 2
echo "=== analysis done $(date +%H:%M:%S)"
