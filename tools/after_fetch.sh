#!/bin/bash
# Waits for the cohort game refetch to finish, then runs, one after the other (never sharing the CPU):
#   1. the game-level report      2. the embedding training      3. the engine move-quality features + their report
#   4. the dial calibration on the depth-based table (uniform prior; personalised prior is a separate decision)
# Every step logs to data/style/logs or data/calibration; a heartbeat is printed each minute while waiting. Run from anywhere.
# If the fetch ends WITHOUT finishing (network down, rate limit), nothing is started: rerun the fetch, then this script.
cd "$(dirname "$0")/.."
PY=.venv/bin/python
FLOG=data/style/logs/games_fetch.log
echo "$(date +%H:%M:%S) waiting for the games fetch to finish (watching $FLOG)"
while pgrep -f "chessme style-games-fetch" >/dev/null; do
  echo "$(date +%H:%M:%S) fetch running: $(tail -1 "$FLOG" | cut -c1-80)"
  sleep 60
done
if ! tail -3 "$FLOG" | grep -q "finished:"; then
  echo "$(date +%H:%M:%S) the fetch stopped without finishing ($(tail -1 "$FLOG" | cut -c1-90)); NOT starting the analysis. Resume the fetch, then rerun this script."
  exit 1
fi
echo "$(date +%H:%M:%S) fetch finished: $(tail -1 "$FLOG" | cut -c1-100)"
echo "$(date +%H:%M:%S) 1/4 game-level report -> data/style/games_report.md"
$PY -m chessme style-games-report --out data/style/games_report.md > data/style/logs/games_report.log 2>&1
echo "$(date +%H:%M:%S) 2/4 embedding training -> data/style/embed (log data/style/logs/embed.log)"
WATCH_OUT=data/style/logs/embed_watch.log tools/watch.sh 3000 $PY -u -m chessme style-embed-train --steps 3000 --eval-every 500
echo "$(date +%H:%M:%S) 3/4 move-quality features (400 players x 10 games, 3 workers) -> data/style/logs/quality.log"
WATCH_OUT=data/style/logs/quality_watch.log tools/watch.sh 3000 $PY -u -m chessme style-games-quality --players 400 --games 10 --workers 3
$PY -m chessme style-quality-report > data/style/quality_report.txt 2>&1
echo "$(date +%H:%M:%S) quality report -> data/style/quality_report.txt"
echo "$(date +%H:%M:%S) 4/4 dial calibration, depth-based table, uniform prior -> data/calibration/dial_v3.json"
WATCH_OUT=data/calibration/v3_abs.log tools/watch.sh 3000 $PY -u -m chessme calibrate --table data/calibration/table_v3.json \
  --dial 1000 1200 1300 1400 1500 1600 1700 1800 2100 2400 2600 --prior uniform --movetime 100 --se 35 --min-games 60 --max-games 300 \
  --concurrency 3 --out data/calibration/dial_v3.json
WATCH_OUT=data/calibration/v3_link.log tools/watch.sh 3000 $PY -u -m chessme calibrate-link --calibration data/calibration/dial_v3.json \
  --table data/calibration/table_v3.json --prior uniform --link-pairs 100 --concurrency 3
echo "$(date +%H:%M:%S) all done: reports in data/style/, calibration data/calibration/dial_v3.json"
