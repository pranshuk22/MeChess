#!/bin/bash
# usage: WATCH_OUT=logfile tools/watch.sh LIMIT_MB cmd...
# Runs cmd in the background, logs its output to WATCH_OUT (default /tmp/watch.out), and kills it (with all its child
# processes) if the RSS of the whole process TREE exceeds LIMIT_MB. Prints the peak when it ends.
# This laptop is memory-tight; every multi-process job (e.g. engine worker pools) must be run under this.
limit=$1; shift
"$@" > "${WATCH_OUT:-/tmp/watch.out}" 2>&1 &
root=$!; peak=0

tree() {  # all descendant pids of $1 (inclusive)
  local all="$1" cur="$1" next
  while [ -n "$cur" ]; do
    next=$(pgrep -P "$(echo $cur | tr ' ' ',')" 2>/dev/null | tr '\n' ' ')
    all="$all $next"; cur="$next"
  done
  echo $all
}

while kill -0 $root 2>/dev/null; do
  pids=$(tree $root)
  rss=$(ps -o rss= -p "$(echo $pids | tr ' ' ',')" 2>/dev/null | awk '{s+=$1} END{print int(s/1024)}')
  [ -n "$rss" ] && [ "$rss" -gt "$peak" ] && peak=$rss
  if [ -n "$rss" ] && [ "$rss" -gt "$limit" ]; then
    kill -9 $pids 2>/dev/null; echo "KILLED: process tree at ${rss}MB (limit ${limit}MB)"; break
  fi
  sleep 1
done
echo "peak RSS (whole tree) ${peak}MB"
