#!/usr/bin/env bash
# Étape 1 phase 3 driver (re-pilot). Fail-closed budget: phase-3 spend counted from the
# opencode DB BEFORE each launch; an arm launches only if spend + 2 x cap <= 5.00 USD.
set -u
EVAL="$HOME/code_projects/IA-tooling/dev-workflow-kit/evals"
DB="$HOME/.local/share/opencode/opencode.db"
BUDGET=5.00; CAP=1.00; export EVAL_ARM_CAP=$CAP EVAL_TIMEOUT_SECS=1800
LOG="$EVAL/2026-11-19/logs/phase3"
spend() {
  sqlite3 -readonly "$DB" "SELECT ifnull(round(SUM(cost),4),0) FROM session WHERE title LIKE 'eval-2026-11-19-IV2-RG4-%' OR title LIKE 'eval-2026-11-19-T4V3-%' OR parent_id IN (SELECT id FROM session WHERE title LIKE 'eval-2026-11-19-IV2-RG4-%' OR title LIKE 'eval-2026-11-19-T4V3-%');"
}
# queue: "script task model variant tag"  (variant '-' = default)
QUEUE=(
"run-eval-v4.sh IV4 github-copilot/claude-haiku-5.5 - r41"
"run-eval-v4.sh IV4 github-copilot/claude-haiku-5.5 - r42"
"run-eval-v4.sh IV4 fireworks-ai/accounts/fireworks/models/minimax-m3p1-flash xhigh r41"
"run-eval-v4.sh IV4 fireworks-ai/accounts/fireworks/models/minimax-m3p1-flash xhigh r42"
"run-eval-v4.sh IV4 github-copilot/claude-haiku-5.5 high r41"
"run-eval-v4.sh IV4 github-copilot/claude-haiku-5.5 high r42"
"run-eval-v5.sh T4V3 fireworks-ai/accounts/fireworks/models/minimax-m3p1-flash xhigh r43"
"run-eval-v5.sh T4V3 fireworks-ai/accounts/fireworks/models/minimax-m3p1-flash xhigh r43b"
"run-eval-v5.sh T4V3 github-copilot/claude-sonnet-5.5 high r43"
"run-eval-v5.sh T4V3 github-copilot/claude-sonnet-5.5 high r43b"
"run-eval-v4.sh IV4 github-copilot/claude-opus-5.5 - r41"
"run-eval-v4.sh IV4 github-copilot/claude-opus-5.5 - r42"
)
for item in "${QUEUE[@]}"; do
  read -r script task model variant tag <<<"$item"
  s=$(spend); ok=$(awk -v s="$s" -v c="$CAP" -v b="$BUDGET" 'BEGIN{print (s+2*c<=b)?1:0}')
  if [ "$ok" != 1 ]; then echo "BUDGET-GUARD stop before [$item]: phase-3 spend=\$$s (need +2x\$$CAP <= \$$BUDGET)"; break; fi
  v=""; [ "$variant" != "-" ] && v="$variant"
  name="$task-$(echo "$model" | tr '/. ' '---')${v:+-$v}-$tag"
  echo "[$(date +%T)] LAUNCH $name (phase-3 spend before=\$$s)"
  bash "$EVAL/$script" "$task" "$model" "$v" "$tag" > "$LOG/$name.log" 2>&1
  echo "[$(date +%T)] EXIT $name status=$? spend-after=\$$(spend)"
done
echo "[$(date +%T)] DRIVER DONE phase-3 spend=\$$(spend)"
