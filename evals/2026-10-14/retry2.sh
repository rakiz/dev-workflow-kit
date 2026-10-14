#!/usr/bin/env bash
set -uo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
while read -r model variant; do
  for t in T1 T2 T3 T4; do
    echo "=== $t $model $variant $(date +%T) ===" >> "$DIR/log.txt"
    "$DIR/../run-eval.sh" "$t" "$model" "$variant" >> "$DIR/log.txt" 2>&1
    echo "RETRY2DONE $t $model $variant rc=$? $(date +%T)" >> "$DIR/done.txt"
  done
done < "$DIR/retry2.txt"
