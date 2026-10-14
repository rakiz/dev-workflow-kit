#!/usr/bin/env bash
# One shard = a subset of ARMS.txt lines, run sequentially: campaign.sh <shard-file>
set -uo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
while read -r model variant; do
  [ -z "$model" ] && continue
  for t in T1 T2 T3 T4; do
    echo "=== $t $model $variant $(date +%T) ===" >> "$DIR/log.txt"
    if [ "$variant" = "none" ]; then
      "$DIR/../run-eval.sh" "$t" "$model" >> "$DIR/log.txt" 2>&1
    else
      "$DIR/../run-eval.sh" "$t" "$model" "$variant" >> "$DIR/log.txt" 2>&1
    fi
    echo "DONE $t $model $variant rc=$? $(date +%T)" >> "$DIR/done.txt"
  done
done < "$1"
echo "SHARD COMPLETE $1" >> "$DIR/done.txt"
