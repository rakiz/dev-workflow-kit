#!/usr/bin/env bash
# Runs one eval: run-eval.sh <T1|T2|T3|T4> <model> [variant]
# The synccli-eval-repo fixture ships as plain files (no .git); the script recreates the 2-commit history in its temp copy. Requires opencode.
set -euo pipefail

TASK=$1; MODEL=$2; VARIANT=${3:-}
EVAL_DIR="$(cd "$(dirname "$0")" && pwd)"
WORK="${TMPDIR:-/tmp}/synccli-eval-$$"
PROMPT_T1="Read GOAL.md and README.md in this repo. You are the orchestrator: produce an execution plan in ordered tasks. For each task: objective, files to create/modify, the pipeline agent that must do it (impl, review, explore, design-review), risks, verifiable acceptance criterion. Apply NO modifications: text-only response."
PROMPT_T2="A test fails in this repo. Run 'python3 -m unittest -v', fix the bug in synccli.py (do NOT modify test_synccli.py), rerun the suite to confirm all tests pass. End with the diff of your fix and the final test results."
PROMPT_T3="Review the LAST commit of this repo (git show HEAD). List only real defects (bugs, data loss, corrupted state, misleading API contract) each with a severity (major/minor). No style nits. Text response."
PROMPT_T4="Read DESIGN.md. Critique this approach BEFORE code is written: major risks, wrong assumptions, what will break under real load, decisions to change first. Concrete and brief."
case $TASK in
  T1) PROMPT=$PROMPT_T1 ;; T2) PROMPT=$PROMPT_T2 ;;
  T3) PROMPT=$PROMPT_T3 ;; T4) PROMPT=$PROMPT_T4 ;;
  *) echo "unknown task: $TASK" >&2; exit 1 ;;
esac
TAG=$(echo "$MODEL" | tr '/. ' '---' )$([ -n "$VARIANT" ] && echo "-$VARIANT")
cp -R "$EVAL_DIR/synccli-eval-repo" "$WORK"
# The fixture ships as plain files (no .git — history stripped on purpose).
# Recreate the exact 2-commit history the tasks expect: baseline without
# incremental.py, then the v0.2 review commit that added it (3 seeded
# defects, T3's target). Robust form: stage everything, unstage
# incremental.py for the baseline, re-add it for the review commit.
git -C "$WORK" init -q
git -C "$WORK" add -A
git -C "$WORK" rm -q --cached incremental.py
git -C "$WORK" -c user.name=eval -c user.email=eval@example.com -c commit.gpgsign=false commit -q -m "Initial synccli"
git -C "$WORK" add incremental.py
git -C "$WORK" -c user.name=eval -c user.email=eval@example.com -c commit.gpgsign=false commit -q -m "v0.2: add exclude filter, batch copy and manifest merge"
if [ -n "$VARIANT" ]; then
  opencode run --dir "$WORK" --model "$MODEL" --variant "$VARIANT" \
    --title "eval-$(date +%F)-$TASK-$TAG" --auto "$PROMPT"
else
  opencode run --dir "$WORK" --model "$MODEL" \
    --title "eval-$(date +%F)-$TASK-$TAG" --auto "$PROMPT"
fi
echo "run dir: $WORK (cost/tokens: sqlite3 ~/.local/share/opencode/opencode.db, session title above)"
