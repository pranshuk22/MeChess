#!/bin/bash
# Waits (a cheap poll, no CPU) for tools/after_fetch.sh to end, then sets up the personal bot:
#   1. fits your style model                       -> $STYLE_OUT
#   2. smoke-tests the UCI engine with the books and the style prior
#   3. measures the strength of exactly that configuration (dial calibration, memory-guarded)  -> $CAL_OUT
#   4. writes the bot's engine script (bot/lichess-bot/engines/mechess-bot.sh; the generic one is kept as mechess-bot-generic.sh)
# Personal names never appear here: pass them in the environment.
#   PROFILE=<profile name>  STYLE_DATA=<style-data folder>  [CLOCK_MODEL=<file from mechess-clock-fit>]  tools/after_calibration.sh
set -u
cd "$(dirname "$0")/.."
PY=.venv/bin/python
: "${PROFILE:?set PROFILE}" "${STYLE_DATA:?set STYLE_DATA}"
STYLE_OUT=data/style/mechess_style.json
CAL_OUT=data/calibration/dial_mechess.json
BOOKS="profiles/$PROFILE/book.bin,data/explorer"      # your repertoire first, then the theory book of the band being played
LOG=data/calibration/after_calibration.log
say() { echo "$(date +%H:%M:%S) $*" | tee -a "$LOG"; }

say "waiting for after_fetch.sh to end"
while pgrep -f "tools/after_fetch.sh" > /dev/null; do sleep 60; done
[ -f data/calibration/dial_v3.json ] || { say "STOP: dial_v3.json is missing, the calibration chain did not finish"; exit 1; }
say "calibration chain finished"

say "1/4 style model"
$PY -m chessme style-model-fit --data "$STYLE_DATA" --out "$STYLE_OUT" >> "$LOG" 2>&1 || { say "STOP: style model failed"; exit 1; }

say "2/4 smoke test"
out=$(printf 'uci\nisready\nposition startpos\ngo\nposition startpos moves e2e4 e7e5 g1f3 b8c6 f1b5 a7a6 b5a4 g8f6 e1g1 f8e7 f1e1 b7b5 a4b3 d7d6 c2c3 e8g8\ngo\nquit\n' | \
  $PY -m chessme mechess --engine engine/build/chessme-engine --book "$BOOKS" --prior "style=$STYLE_OUT" \
      --calibration data/calibration/dial_v3.json --elo 1800 2>&1)
echo "$out" >> "$LOG"
[ "$(echo "$out" | grep -c '^bestmove')" = 2 ] && echo "$out" | grep -q '^info string book' || { say "STOP: smoke test failed (see $LOG)"; exit 1; }
say "smoke test ok (the first move came from the book)"

say "3/4 strength of the personal configuration -> $CAL_OUT"
WATCH_OUT=data/calibration/mechess_abs.log tools/watch.sh 3000 $PY -u -m chessme calibrate --table data/calibration/table_v3.json \
  --dial 1000 1200 1300 1400 1500 1600 1700 1800 2100 2400 2600 --prior "style=$STYLE_OUT" --book "$BOOKS" --movetime 100 --se 35 \
  --min-games 60 --max-games 300 --concurrency 3 --out "$CAL_OUT"
WATCH_OUT=data/calibration/mechess_link.log tools/watch.sh 3000 $PY -u -m chessme calibrate-link --calibration "$CAL_OUT" \
  --table data/calibration/table_v3.json --prior "style=$STYLE_OUT" --book "$BOOKS" --link-pairs 100 --concurrency 3
[ -f "$CAL_OUT" ] || { say "STOP: no calibration written"; exit 1; }

say "4/4 bot engine script"
E=bot/lichess-bot/engines
[ -f $E/mechess-bot-generic.sh ] || cp $E/mechess-bot.sh $E/mechess-bot-generic.sh
cat > $E/mechess-bot.sh <<EOS
#!/bin/bash
# Starts MeChess as a UCI engine for lichess-bot: your opening repertoire, then theory for the level being played, your style among
# the engine's good moves, and the dial measured for exactly this configuration. The generic version is mechess-bot-generic.sh.
export OMP_NUM_THREADS=1 MKL_NUM_THREADS=1
cd "\$(dirname "\$0")/../../.."          # project root
exec .venv/bin/python -m chessme mechess --engine engine/build/chessme-engine --book "$BOOKS" \\
     --prior "style=$STYLE_OUT" --calibration $CAL_OUT${CLOCK_MODEL:+ \\
     --clock $CLOCK_MODEL}
EOS
chmod +x $E/mechess-bot.sh
say "all done: bot script $E/mechess-bot.sh, calibration $CAL_OUT"
