#!/usr/bin/env bash
set -uo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
while read -r t model variant; do
  [ -z "$t" ] && continue
  echo "=== RETRY $t $model $variant $(date +%T) ===" >> "$DIR/log.txt"
  "$DIR/../run-eval.sh" "$t" "$model" "$variant" >> "$DIR/log.txt" 2>&1
  echo "RETRYDONE $t $model $variant rc=$? $(date +%T)" >> "$DIR/done.txt"
done < "$DIR/retry.txt"
