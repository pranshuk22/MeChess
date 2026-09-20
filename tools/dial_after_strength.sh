#!/bin/bash
# Waits for the engine strength measurement to finish (so the two wall-clock measurements never share the CPU), then calibrates
# the MeChess dial. Logs a heartbeat every minute. Run from anywhere; results go to data/calibration/dial.json.
cd "$(dirname "$0")/.."
WAIT_LOG=data/calibration/strength_engine_2.log
echo "$(date +%H:%M:%S) waiting for the strength measurement to finish (watching $WAIT_LOG)"
while ! grep -q "Elo on the" "$WAIT_LOG" 2>/dev/null; do
  echo "$(date +%H:%M:%S) strength run still going: $(tail -1 "$WAIT_LOG" | cut -c1-100)"
  sleep 60
done
echo "$(date +%H:%M:%S) strength run finished; starting the dial calibration -> data/calibration/dial.log"
WATCH_OUT=data/calibration/dial.log tools/watch.sh 2000 .venv/bin/python -u -m chessme calibrate \
  --dial 1200 1500 1800 2100 2400 2600 --prior uniform --movetime 100 --se 35 --min-games 60 --max-games 300 \
  --concurrency 3 --out data/calibration/dial.json
echo "$(date +%H:%M:%S) dial calibration finished: data/calibration/dial.json"
