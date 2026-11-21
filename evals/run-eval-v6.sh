#!/usr/bin/env bash
# run-eval-v6.sh <HO2|HOD> <model> [variant] [run_tag] — held-out arm runner (HOLDOUT-SPEC §5.5-§5.6, §7).
# Copies v4's cap / watchdog / report machinery, plus the isolation layer:
#   * the fixture is copied OUTSIDE the sandbox, then the arm runs under sandbox-exec (holdout-harness/);
#   * per-arm XDG_DATA_HOME / XDG_CONFIG_HOME / HOME / TMPDIR (no auth.json; minimal config, MCP off);
#   * all provider traffic goes through the local CONNECT proxy (metered; the only network route).
# Fail closed: EVAL_ARM_CAP is mandatory, and HOLDOUT_PREFLIGHT_OK=1 must be set by drive-holdout.sh
# after preflight.sh passed. Usage errors exit 1. Per-arm timeouts: EVAL_TIMEOUT_SECS (M13).
set -euo pipefail
if [ $# -lt 2 ]; then
  echo "usage: run-eval-v6.sh <HO2|HOD> <model> [variant] [run_tag]" >&2
  echo "  EVAL_ARM_CAP=<usd> REQUIRED; the arm is killed at 2x cap (M13)" >&2
  exit 1
fi
TASK=$1; MODEL=$2; VARIANT=${3:-}; RUN_TAG=${4:-}
EVAL_DIR="$(cd "$(dirname "$0")" && pwd)"
HARNESS="$EVAL_DIR/holdout-harness"
TIMEOUT_SECS="${EVAL_TIMEOUT_SECS:-900}"
[ -n "${EVAL_ARM_CAP:-}" ] || { echo "error: EVAL_ARM_CAP (<usd>) must be set explicitly" >&2; exit 1; }
[ "${HOLDOUT_PREFLIGHT_OK:-0}" = 1 ] || { echo "error: HOLDOUT_PREFLIGHT_OK=1 required (run preflight.sh first; fail closed)" >&2; exit 1; }
EVAL_ARM_CAP_NUM="$EVAL_ARM_CAP"
case $TASK in
  HO2) FIXTURE="$EVAL_DIR/heldout-impl-sp1"; CODE=HO2; FIXCODE=SP1
       PROMPT="Work in this repo copy alone — no subagents, no delegation. Read GOAL.md and do what it asks: implement the requested feature in this repo copy, fix any defects you find with the smallest change that keeps the suite green and the stated invariants holding, add a regression test per fixed defect, and state in your final report any trade-off the brief leaves open, with the choice you made and the cost it accepts. Do not refactor; do not touch unrelated tests." ;;
  HOD) FIXTURE="$EVAL_DIR/heldout-design-us1"; CODE=HOD; FIXCODE=US1
       PROMPT="Work in this repo copy alone — no subagents, no delegation. Read BRIEF.md and write the design it asks for to DESIGN-us1.md in this repo copy." ;;
  *) echo "unknown task: $TASK (expected HO2 or HOD)" >&2; exit 1 ;;
esac
TAG="$(echo "$MODEL" | tr '/. ' '---')${VARIANT:+-$VARIANT}${RUN_TAG:+-$RUN_TAG}"
TITLE="eval-$(date +%F)-${CODE}-${FIXCODE}-${TAG}"
export ARM_MODEL="$MODEL"
# egress: pass-through TLS termination + metering (owner amendment); campaign CA dir set by drive-holdout.sh
: "${HOLDOUT_CAMP_DIR:?HOLDOUT_CAMP_DIR must be set (campaign CA dir, drive-holdout.sh)}"
export HOLDOUT_CAMP_DIR
ARM_HOST="$(python3 -B "$HARNESS/holdout-provider.py" meta --model "$MODEL" | python3 -c 'import json,sys;print(json.load(sys.stdin)["host"])')"
[ -n "$VARIANT" ] && VARIANT_ARGS=(--variant "$VARIANT") || VARIANT_ARGS=()

# free local port for this arm's proxy
PORT="$(python3 -B -c 'import socket;s=socket.socket();s.bind(("127.0.0.1",0));print(s.getsockname()[1]);s.close()')"
"$HARNESS/holdout-arm.sh" prepare "$TITLE" "$FIXTURE" "$PORT"
eval "$("$HARNESS/holdout-arm.sh" paths "$TITLE")"
PROXY_CAP_BYTES="${HOLDOUT_BYTE_CAP:-200000000}"
python3 -B "$HARNESS/holdout-proxy.py" --port "$PORT" --allow "$ARM_HOST" --campaign-dir "$HOLDOUT_CAMP_DIR" \
  --metrics "$ARM_TMP/proxy.json" --cap-bytes "$PROXY_CAP_BYTES" &
PROXY_PID=$!
sleep 1
kill -0 "$PROXY_PID" 2>/dev/null || { echo "error: proxy refused to start (fail closed) for $TITLE" >&2; exit 1; }
export PROXY_PORT="$PORT"

kill_arm() {
  pkill -TERM -P "$OPENCODE_PID" 2>/dev/null || true
  kill -TERM "$OPENCODE_PID" 2>/dev/null || true
  sleep 5
  pkill -KILL -P "$OPENCODE_PID" 2>/dev/null || true
  kill -KILL "$OPENCODE_PID" 2>/dev/null || true
}

"$HARNESS/holdout-arm.sh" exec "$TITLE" -- opencode run --dir "$ARM_WORK" --model "$MODEL" \
  ${VARIANT_ARGS[@]+"${VARIANT_ARGS[@]}"} --title "$TITLE" --auto "$PROMPT" &
OPENCODE_PID=$!
OC_DB="$ARM_DATA/opencode/opencode.db"

# per-arm cost poller (5 min; liveness heartbeat written at start and every cycle — M13/MINOR 6)
COST_Q="SELECT SUM(cost) FROM session WHERE title = '$TITLE' OR parent_id = (SELECT id FROM session WHERE title = '$TITLE');"
(
  date +%s > "$ARM_TMP/hb-cost"
  while :; do
    sleep 300
    date +%s > "$ARM_TMP/hb-cost"
    cost="$(sqlite3 "$OC_DB" "$COST_Q" 2>/dev/null)" || continue
    [ -z "$cost" ] && continue
    if [ "$(awk -v c="$cost" -v cap="$EVAL_ARM_CAP_NUM" 'BEGIN { print (c + 0 > 2 * cap) ? 1 : 0 }')" = 1 ]; then
      date +%s > "$ARM_TMP/arm-killed-costcap"
      kill_arm
      break
    fi
  done
) &
COST_POLLER_PID=$!

# wall-clock watchdog (M13: >= 1800 s sonnet/opus HOD, >= 900 s otherwise; set by the campaign)
(
  sleep "$TIMEOUT_SECS"
  if kill -0 "$OPENCODE_PID" 2>/dev/null; then
    date +%s > "$ARM_TMP/arm-killed-timeout"
    kill_arm
  fi
) &
WATCHDOG_PID=$!

set +e
wait "$OPENCODE_PID"; RUN_STATUS=$?
set -e
for watcher in "$COST_POLLER_PID" "$WATCHDOG_PID"; do
  pkill -TERM -P "$watcher" 2>/dev/null || true
  kill "$watcher" 2>/dev/null || true
done
wait "$COST_POLLER_PID" 2>/dev/null || true
wait "$WATCHDOG_PID" 2>/dev/null || true
kill "$PROXY_PID" 2>/dev/null || true

if [ -f "$ARM_TMP/arm-killed-costcap" ]; then
  echo "arm-killed-costcap: $TITLE cost exceeded 2x EVAL_ARM_CAP" >&2; exit 125
fi
if [ -f "$ARM_TMP/arm-killed-timeout" ]; then
  echo "arm-killed-timeout: $TITLE hit the watchdog" >&2; exit 124
fi

# final report from the PER-ARM DB (keyed by exact title, never a table scan)
REPORT_SESSION="$(sqlite3 -readonly "$OC_DB" "SELECT id FROM session WHERE title = '$TITLE' ORDER BY time_created DESC LIMIT 1;" 2>/dev/null || true)"
REPORT_MSG=""
if [ -n "$REPORT_SESSION" ]; then
  REPORT_MSG="$(sqlite3 -readonly "$OC_DB" \
    "SELECT m.id FROM message m WHERE m.session_id = '$REPORT_SESSION' \
  AND json_extract(m.data,'\$.role') = 'assistant' AND json_extract(m.data,'\$.finish') = 'stop' \
  AND EXISTS (SELECT 1 FROM part p WHERE p.message_id = m.id AND json_extract(p.data,'\$.type') = 'text') \
ORDER BY m.time_created DESC, m.id DESC LIMIT 1;" 2>/dev/null || true)"
fi
if [ -n "$REPORT_MSG" ]; then
  sqlite3 -readonly "$OC_DB" "SELECT json_extract(p.data,'\$.text') FROM part p \
WHERE p.message_id = '$REPORT_MSG' AND json_extract(p.data,'\$.type') = 'text' ORDER BY p.id;" > "$ARM_WORK/final-report.md"
  echo "final report captured: $ARM_WORK/final-report.md (session $TITLE)"
else
  touch "$ARM_WORK/no-report"
  echo "warn: no assistant text for session $TITLE — no-report marker written (DNF re-run signal)" >&2
fi
echo "run dir: $ARM_WORK (per-arm DB: $OC_DB)"
exit "$RUN_STATUS"
