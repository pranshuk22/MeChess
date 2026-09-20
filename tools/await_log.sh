#!/bin/bash
# usage: tools/await_log.sh LOGFILE DONE_PATTERN [STALL_MINUTES]
# Returns when the log contains DONE_PATTERN (prints the matching lines), or when the log has not changed for STALL_MINUTES
# (default 10; prints STALLED), or when the file does not appear within the same time. Meant to be run in the background
# so the caller is notified.
log=$1; pat=$2; stall=${3:-10}
last=0; idle=0
while true; do
  if [ -f "$log" ] && grep -q -E "$pat" "$log"; then
    echo "DONE: $(grep -E "$pat" "$log" | tail -3)"; exit 0
  fi
  cur=$(stat -f %m "$log" 2>/dev/null || echo 0)
  if [ "$cur" = "$last" ]; then idle=$((idle+1)); else idle=0; last=$cur; fi
  if [ $idle -ge $((stall*6)) ]; then echo "STALLED: no change in $log for $stall minutes; last line: $(tail -1 "$log" 2>/dev/null | cut -c1-140)"; exit 1; fi
  sleep 10
done
