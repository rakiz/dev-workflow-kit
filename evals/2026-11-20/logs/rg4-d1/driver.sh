#!/usr/bin/env bash
# RG4 DNF re-runs (D1, 2026-11-20). Sequential, fail-closed.
# Task: run-eval-v4.sh IV4 (fixture reportgen-eval-repo-i4), EVAL_TIMEOUT_SECS=1800.
# Budget: $3.00 hard max, counted from the opencode DB as spend SINCE THIS LAUNCH'S
# BASELINE (captured below). Before each arm: launch only if delta + 2 x cap <= 3.00
# (the arm's own cost-cap poller kills at 2 x cap, so 2 x cap is the worst case).
# Tags: qwen-xhigh run 1 = q53, run 2 = q53b (the cost poller and the report query key on
# the exact title, so two arms with an identical tag would be conflated); argon q53; carbon q53.
set -u
EVAL="$HOME/code_projects/IA-tooling/dev-workflow-kit/evals"
DB="$HOME/.local/share/opencode/opencode.db"
LOG="$EVAL/2026-11-20/logs/rg4-d1"
BUDGET=3.00
export EVAL_TIMEOUT_SECS=1800
spend() {
  sqlite3 -readonly "$DB" "SELECT ifnull(round(SUM(cost),4),0) FROM session WHERE title LIKE 'eval-2026-11-1%' OR title LIKE 'eval-2026-11-2%' OR title LIKE 'panel-%' OR parent_id IN (SELECT id FROM session WHERE title LIKE 'eval-2026-11-1%' OR title LIKE 'eval-2026-11-2%' OR title LIKE 'panel-%');"
}
BASE=$(spend)
delta() { awk -v s="$(spend)" -v b="$BASE" 'BEGIN{printf "%.4f", s-b}'; }
echo "[$(date +%T)] D1 driver: BASE=\$$BASE ; budget \$$BUDGET"

# queue: "cap name model variant tag"  (variant '-' = default)
QUEUE=(
"1.00 qwen-xhigh fireworks-ai/accounts/fireworks/models/qwen3p8-2p4t-a95b xhigh q53"
"1.00 qwen-xhigh fireworks-ai/accounts/fireworks/models/qwen3p8-2p4t-a95b xhigh q53b"
"0.60 argon-high github-copilot/gemini-4-argon high q53"
"2.00 carbon-high github-copilot/gemini-4-carbon high q53"
)

for item in "${QUEUE[@]}"; do
  read -r cap name model variant tag <<<"$item"
  d=$(delta)
  ok=$(awk -v d="$d" -v c="$cap" -v b="$BUDGET" 'BEGIN{print (d+2*c<=b)?1:0}')
  if [ "$ok" != 1 ]; then
    echo "BUDGET-GUARD stop before [$name $tag]: delta=\$$d (need delta+2x\$$cap <= \$$BUDGET)"
    echo "DRIVER STOPPED (guard)"; exit 0
  fi
  runname="IV4-$(echo "$model" | tr '/. ' '---')${variant:+-$variant}-$tag"
  echo "[$(date +%T)] LAUNCH $name $tag cap=\$$cap delta-before=\$$d"
  EVAL_ARM_CAP="$cap" bash "$EVAL/run-eval-v4.sh" IV4 "$model" "$variant" "$tag" > "$LOG/$runname.log" 2>&1
  st=$?
  echo "[$(date +%T)] EXIT $name $tag status=$st delta-after=\$$(delta)"
done
echo "[$(date +%T)] DRIVER DONE delta-spend=\$$(delta)"
