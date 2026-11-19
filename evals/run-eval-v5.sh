#!/usr/bin/env bash
# Runs one legacy-bench eval with bench-v3 cost discipline: run-eval-v5.sh <T3|T4V2|T4V3> <model> [variant] [run_tag]
# T3 = impl-review (fixture synccli-eval-repo, v1 bench — its 2-commit history recreated)
# T4V2 = design-review (fixture synccli-eval-repo-v2, v2 bench — archived prompt, unchanged)
# T4V3 = design-review DR-v3 (same fixture; proposal + prototype conformance, Étape 1)
# Same fail-closed cap machinery as run-eval-v4.sh (EVAL_TIER/EVAL_ARM_CAP required,
# poller kills at 2x cap, wall-clock watchdog). The historical runners
# run-eval.sh / run-eval-v2.sh stay frozen — this script exists so the
# matrix-completion campaign can run legacy tasks WITH caps (§5.8).
set -euo pipefail

if [ $# -lt 2 ]; then
  echo "usage: run-eval-v5.sh <T3|T4V2|T4V3> <model> [variant] [run_tag]" >&2
  echo "  EVAL_TIER or EVAL_ARM_CAP required (same semantics as run-eval-v4.sh)" >&2
  exit 1
fi
TASK=$1; MODEL=$2; VARIANT=${3:-}; RUN_TAG=${4:-}
EVAL_DIR="$(cd "$(dirname "$0")" && pwd)"
WORK="${TMPDIR:-/tmp}/bench-v3-legacy-$$"
TIMEOUT_SECS="${EVAL_TIMEOUT_SECS:-900}"
if [ -z "${EVAL_TIER:-}" ] && [ -z "${EVAL_ARM_CAP:-}" ]; then
  echo "error: no per-arm cost cap configured — set EVAL_TIER (cheap|mid|strong) or EVAL_ARM_CAP" >&2
  exit 1
fi
case "${EVAL_TIER:-}" in
  cheap)  TIER_CAP="0.05" ;;
  mid)    TIER_CAP="0.30" ;;
  strong) TIER_CAP="1.00" ;;
  "")     TIER_CAP="" ;;
  *) echo "unknown EVAL_TIER: ${EVAL_TIER:-}" >&2; exit 1 ;;
esac
EVAL_ARM_CAP="${EVAL_ARM_CAP:-$TIER_CAP}"
OC_DB="${HOME}/.local/share/opencode/opencode.db"

case $TASK in
  T1)
    FIXTURE=synccli-eval-repo
    PROMPT="Read GOAL.md and README.md in this repo. You are the orchestrator: produce an execution plan in ordered tasks. For each task: objective, files to create/modify, the pipeline agent that must do it (impl, review, explore, design-review), risks, verifiable acceptance criterion. Apply NO modifications: text-only response."
    ;;
  T3)
    FIXTURE=synccli-eval-repo
    PROMPT="Review the LAST commit of this repo (git show HEAD). List only real defects (bugs, data loss, corrupted state, misleading API contract) each with a severity (major/minor). No style nits. Text response."
    ;;
  T4V2)
    FIXTURE=synccli-eval-repo-v2
    PROMPT="Read DESIGN.md. Critique this approach BEFORE code is written: major risks, wrong assumptions, what will break under real load, decisions to change first. Concrete and brief."
    ;;
  T4V3)
    # DR-v3 (Étape 1, F4): asks for BOTH proposal review and prototype conformance,
    # reported separately by the scorer. Fixture = DR2 fixture (unchanged).
    FIXTURE=synccli-eval-repo-v2
    PROMPT="Read DESIGN.md and the accompanying prototype (syncd.py, state.py). Identify BOTH: flaws in the proposed approach itself, AND places where the prototype fails to implement the design's guarantees. State true findings and keep speculative claims clearly labeled."
    ;;
  *) echo "unknown task: $TASK (expected T1, T3, T4V2 or T4V3)" >&2; exit 1 ;;
esac

TAG="$(echo "$MODEL" | tr '/. ' '---')${VARIANT:+-$VARIANT}${RUN_TAG:+-$RUN_TAG}"
TITLE="eval-$(date +%F)-${TASK}-${TAG}"

# Preflight (same as v4)
command -v sqlite3 >/dev/null 2>&1 || { echo "preflight: sqlite3 missing" >&2; exit 1; }
[ -f "$OC_DB" ] || { echo "preflight: DB missing" >&2; exit 1; }
sqlite3 "$OC_DB" "SELECT cost, parent_id FROM session LIMIT 1;" >/dev/null 2>&1 \
  || { echo "preflight: session table lacks cost/parent_id" >&2; exit 1; }

cp -R "$EVAL_DIR/$FIXTURE" "$WORK"

kill_arm() {
  pkill -TERM -P "$OPENCODE_PID" 2>/dev/null || true
  kill -TERM "$OPENCODE_PID" 2>/dev/null || true
  sleep 5
  pkill -KILL -P "$OPENCODE_PID" 2>/dev/null || true
  kill -KILL "$OPENCODE_PID" 2>/dev/null || true
}

if [ "$TASK" = "T3" ] || [ "$TASK" = "T1" ]; then
  # Recreate the exact 2-commit history the SYNC1 tasks expect (from frozen run-eval.sh)
  git -C "$WORK" init -q
  git -C "$WORK" add -A
  git -C "$WORK" rm -q --cached incremental.py
  git -C "$WORK" -c user.name=eval -c user.email=eval@example.com -c commit.gpgsign=false commit -q -m "Initial synccli"
  git -C "$WORK" add incremental.py
  git -C "$WORK" -c user.name=eval -c user.email=eval@example.com -c commit.gpgsign=false commit -q -m "v0.2: add exclude filter, batch copy and manifest merge"
fi

if [ -n "$VARIANT" ]; then
  opencode run --dir "$WORK" --model "$MODEL" --variant "$VARIANT" \
    --title "$TITLE" --auto "$PROMPT" &
else
  opencode run --dir "$WORK" --model "$MODEL" \
    --title "$TITLE" --auto "$PROMPT" &
fi
OPENCODE_PID=$!

COST_Q="SELECT SUM(cost) FROM session \
WHERE title = '$TITLE' \
   OR parent_id = (SELECT id FROM session WHERE title = '$TITLE');"
(
  while :; do
    sleep 300
    if ! cost="$(sqlite3 "$OC_DB" "$COST_Q" 2>/dev/null)"; then continue; fi
    [ -z "$cost" ] && continue
    if [ "$(awk -v c="$cost" -v cap="$EVAL_ARM_CAP" 'BEGIN { print (c + 0 > 2 * cap) ? 1 : 0 }')" = 1 ]; then
      date +%s > "$WORK/arm-killed-costcap"
      kill_arm
      break
    fi
  done
) &
COST_POLLER_PID=$!

(
  sleep "$TIMEOUT_SECS"
  if kill -0 "$OPENCODE_PID" 2>/dev/null; then
    date +%s > "$WORK/arm-killed-timeout"
    kill_arm
  fi
) &
WATCHDOG_PID=$!

set +e
wait "$OPENCODE_PID"
RUN_STATUS=$?
set -e

for watcher in "$COST_POLLER_PID" "$WATCHDOG_PID"; do
  pkill -TERM -P "$watcher" 2>/dev/null || true
  kill "$watcher" 2>/dev/null || true
done
wait "$COST_POLLER_PID" 2>/dev/null || true
wait "$WATCHDOG_PID" 2>/dev/null || true

[ -f "$WORK/arm-killed-costcap" ] && { echo "arm-killed-costcap: $TITLE (cap \$$EVAL_ARM_CAP); run dir: $WORK" >&2; exit 125; }
[ -f "$WORK/arm-killed-timeout" ] && { echo "arm-killed-timeout: $TITLE; run dir: $WORK" >&2; exit 124; }

# Capture the run's final assistant message into the run dir (PROTOCOL: every
# run dir carries final-report.md, or a no-report marker = DNF re-run signal —
# a missing report is NEVER scored as report-dependent 0). Keyed queries only:
# lookup by exact session title, never a table scan of the large DB.
REPORT_SESSION="$(sqlite3 -readonly "$OC_DB" \
  "SELECT id FROM session WHERE title = '$TITLE' ORDER BY time_created DESC LIMIT 1;")"
REPORT_MSG=""
if [ -n "$REPORT_SESSION" ]; then
  REPORT_MSG="$(sqlite3 -readonly "$OC_DB" \
    "SELECT m.id FROM message m \
WHERE m.session_id = '$REPORT_SESSION' \
  AND json_extract(m.data,'\$.role') = 'assistant' \
  AND json_extract(m.data,'\$.finish') = 'stop' \
  AND EXISTS (SELECT 1 FROM part p WHERE p.message_id = m.id \
      AND json_extract(p.data,'\$.type') = 'text') \
ORDER BY m.time_created DESC, m.id DESC LIMIT 1;")"
fi
if [ -n "$REPORT_MSG" ]; then
  sqlite3 -readonly "$OC_DB" \
    "SELECT json_extract(p.data,'\$.text') FROM part p \
WHERE p.message_id = '$REPORT_MSG' \
  AND json_extract(p.data,'\$.type') = 'text' ORDER BY p.id;" \
    > "$WORK/final-report.md"
  echo "final report captured: $WORK/final-report.md (session $TITLE)"
else
  touch "$WORK/no-report"
  echo "warn: no assistant text found for session $TITLE — no-report marker written (DNF re-run signal)" >&2
fi

echo "run dir: $WORK (cost/tokens: sqlite3 ~/.local/share/opencode/opencode.db, session title $TITLE)"
exit "$RUN_STATUS"
