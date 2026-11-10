#!/usr/bin/env bash
# Runs one bench-v2 eval: run-eval-v2.sh <model> [variant]
# Runs ONLY the T4 design-review task against the synccli-eval-repo-v2 fixture (plain files, no .git). Requires opencode.
set -euo pipefail

if [ $# -lt 1 ]; then
  echo "usage: run-eval-v2.sh <model> [variant]" >&2
  exit 1
fi
MODEL=$1; VARIANT=${2:-}
EVAL_DIR="$(cd "$(dirname "$0")" && pwd)"
WORK="${TMPDIR:-/tmp}/synccli-eval-v2-$$"
PROMPT_T4="Read DESIGN.md. Critique this approach BEFORE code is written: major risks, wrong assumptions, what will break under real load, decisions to change first. Concrete and brief."
PROMPT=$PROMPT_T4
TAG="$(echo "$MODEL" | tr '/. ' '---')${VARIANT:+-$VARIANT}"
cp -R "$EVAL_DIR/synccli-eval-repo-v2" "$WORK"
if [ -n "$VARIANT" ]; then
  opencode run --dir "$WORK" --model "$MODEL" --variant "$VARIANT" \
    --title "eval-$(date +%F)-T4V2-$TAG" --auto "$PROMPT"
else
  opencode run --dir "$WORK" --model "$MODEL" \
    --title "eval-$(date +%F)-T4V2-$TAG" --auto "$PROMPT"
fi
echo "run dir: $WORK (cost/tokens: sqlite3 ~/.local/share/opencode/opencode.db, session title eval-<date>-T4V2-<tag> above)"
