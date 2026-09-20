#!/bin/bash
# Waits for the cohort analysis to finish, then runs the cohort report. Logs a heartbeat every minute so it is never silent.
# Usage: tools/after_analysis.sh   (run from the project root; log lines go to stdout, redirect them to a file)
cd "$(dirname "$0")/.."
LOG=data/style/logs/cohort_analyze.log
echo "$(date +%H:%M:%S) waiting for the cohort analysis to finish (watching $LOG)"
while ! grep -q "cohort analysis finished" "$LOG"; do
  done_n=$(ls data/style/cohort/cands 2>/dev/null | wc -l | tr -d ' ')
  total=$(python3 -c "import json;print(len(json.load(open('data/style/cohort/players.json'))))" 2>/dev/null)
  echo "$(date +%H:%M:%S) still analysing: ${done_n}/${total} players; last log line: $(tail -1 "$LOG" | cut -c1-90)"
  sleep 60
done
echo "$(date +%H:%M:%S) analysis finished; starting the cohort report -> data/style/logs/cohort_report.log"
WATCH_OUT=data/style/logs/cohort_report.log tools/watch.sh 3500 .venv/bin/python -u -m chessme style-cohort-report --out data/style/cohort
echo "$(date +%H:%M:%S) cohort report finished (peak memory line above is from the guard); result: data/style/cohort/reliability.txt"
