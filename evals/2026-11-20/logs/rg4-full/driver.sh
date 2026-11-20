#!/usr/bin/env bash
# RG4 full re-pilot driver (2026-11-20). Sequential, fail-closed.
# Task: run-eval-v4.sh IV4 (fixture reportgen-eval-repo-i4). Tags q51 then q52.
# Budget: $20 hard-stop counted from the opencode DB (titles eval-2026-11-1% + panel-%).
# The DB already holds $122.89 of prior history at launch, so the $20 is counted as spend
# SINCE THIS LAUNCH'S BASELINE (captured below). Before each arm: launch only if
# delta_spend + 2 x cap <= 20.00 (the arm's own cost-cap poller kills at 2 x cap).
set -u
EVAL="$HOME/code_projects/IA-tooling/dev-workflow-kit/evals"
DB="$HOME/.local/share/opencode/opencode.db"
BUDGET=20.00
LOG="$EVAL/2026-11-20/logs/rg4-full"
export EVAL_TIMEOUT_SECS=1800
# v2 (restart): the v1 pattern 'eval-2026-11-1%' missed this launch's 'eval-2026-11-20-' titles
# (guard blind). Pattern now covers 2026-11-1x AND 2026-11-2x. BASE pinned to the v1 launch baseline.
spend() {
  sqlite3 -readonly "$DB" "SELECT ifnull(round(SUM(cost),4),0) FROM session WHERE title LIKE 'eval-2026-11-1%' OR title LIKE 'eval-2026-11-2%' OR title LIKE 'panel-%' OR parent_id IN (SELECT id FROM session WHERE title LIKE 'eval-2026-11-1%' OR title LIKE 'eval-2026-11-2%' OR title LIKE 'panel-%');"
}
delta() { awk -v s="$(spend)" -v b="$BASE" 'BEGIN{printf "%.4f", s-b}'; }
BASE=125.0677
# arms already completed under v1 (q51): skipped here, never relaunched (no duplicate titles)
SKIP=" glm-low q51 | glm-high q51 | dsflash-default q51 "
echo "[$(date +%T)] v2 driver: BASE=\$$BASE (v1 launch baseline) ; current delta=\$$(delta) ; budget \$$BUDGET"

# queue: "cap name model variant"   variant '-' = default. Cheap first, strong last.
QUEUE=(
"0.10 glm-low ai-gateway-misc/fw-glm-5.3-flash low"
"0.10 glm-high ai-gateway-misc/fw-glm-5.3-flash high"
"0.10 dsflash-default ai-gateway-misc/fw-deepseek-v4.1-flash -"
"0.10 1017-low fireworks-ai/accounts/fireworks/models/deepseek-v4p1-flash-1017 low"
"0.10 1017-medium fireworks-ai/accounts/fireworks/models/deepseek-v4p1-flash-1017 medium"
"0.10 1017-high fireworks-ai/accounts/fireworks/models/deepseek-v4p1-flash-1017 high"
"0.10 minimax-low fireworks-ai/accounts/fireworks/models/minimax-m3p1-flash low"
"0.10 minimax-medium fireworks-ai/accounts/fireworks/models/minimax-m3p1-flash medium"
"0.30 qwen-medium fireworks-ai/accounts/fireworks/models/qwen3p8-2p4t-a95b medium"
"0.30 hydrogen-high github-copilot/gemini-4-hydrogen high"
"0.30 hydrogen-medium github-copilot/gemini-4-hydrogen medium"
"0.30 argon-high github-copilot/gemini-4-argon high"
"0.30 gem38-medium github-copilot/gemini-3.8-flash medium"
"0.30 muse-medium fireworks-ai/accounts/fireworks/models/muse-spark-open medium"
"0.30 kimi-medium fireworks-ai/accounts/fireworks/models/kimi-k3p1-pro medium"
"0.30 terra-medium github-copilot/gpt-6.1-terra medium"
"1.00 qwen-xhigh fireworks-ai/accounts/fireworks/models/qwen3p8-2p4t-a95b xhigh"
"1.00 sonnet-high github-copilot/claude-sonnet-5.5 high"
"1.50 carbon-high github-copilot/gemini-4-carbon high"
)

for tag in q51 q52; do
  for item in "${QUEUE[@]}"; do
    read -r cap name model variant <<<"$item"
    case "$SKIP" in *" $name $tag "*) echo "skip (done in v1): $name $tag"; continue;; esac
    d=$(delta)
    ok=$(awk -v d="$d" -v c="$cap" -v b="$BUDGET" 'BEGIN{print (d+2*c<=b)?1:0}')
    if [ "$ok" != 1 ]; then
      echo "BUDGET-GUARD stop before [$name $tag]: delta=\$$d (need +2x\$$cap <= \$$BUDGET)"
      echo "DRIVER STOPPED (guard)"; exit 0
    fi
    v=""; [ "$variant" != "-" ] && v="$variant"
    runname="IV4-$(echo "$model" | tr '/. ' '---')${v:+-$v}-$tag"
    echo "[$(date +%T)] LAUNCH $name $tag cap=\$$cap delta-before=\$$d"
    EVAL_ARM_CAP="$cap" bash "$EVAL/run-eval-v4.sh" IV4 "$model" "$v" "$tag" > "$LOG/$runname.log" 2>&1
    st=$?
    echo "[$(date +%T)] EXIT $name $tag status=$st delta-after=\$$(delta)"
  done
done
echo "[$(date +%T)] DRIVER DONE delta-spend=\$$(delta)"
