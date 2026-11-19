#!/usr/bin/env bash
# Runs one bench-v3-redesign eval: run-eval-v4.sh <IV2|D1> <model> [variant] [run_tag]
# Redesign-generation tasks (BENCH-V3-DESIGN §3/§4 + proposal v2; uncommitted night session):
#   IV2 = I-v2 impl task          — fixture reportgen-eval-repo-i3 (code RG3)
#   D1  = D design authoring task — fixture syncfeat-brief-d1 + snaputil.py (code D1)
# Both fixtures ship as plain files (no .git); the script copies one to a
# fresh temp work dir. The historical runners run-eval.sh / run-eval-v2.sh
# are frozen records — do not extend them. Requires opencode.
#
# Per-arm cost cap (BENCH-V3-DESIGN §5.8), via the environment variable
# EVAL_ARM_CAP (USD) or the EVAL_TIER preset (cheap|mid|strong ->
# 0.05|0.30|1.00); EVAL_ARM_CAP overrides EVAL_TIER, and one of the two
# MUST be set explicitly — the script aborts with a usage error if neither
# is (fail closed, no implicit default). A
# background poller reads the opencode DB every 5 minutes; when the arm's
# accumulated cost exceeds 2x the cap the arm is killed (same kill path as
# the wall-clock watchdog), the run dir records arm-killed-costcap, and the
# script exits non-zero. Arm cost = parent + ALL child sessions (delegation
# rule): children roll up via session.parent_id where the DB allows.
# A preflight check aborts BEFORE launching an arm if sqlite3 / the DB /
# the session table are unusable — the campaign must not start without
# caps active (BENCH-V3-DESIGN §5.8, §7.6).
# An optional 4th positional arg RUN_TAG is appended to the title token
# (e.g. r2 -> "...-<model>-<variant>-r2") so §5.4 re-run arms never
# collide with run 1 in cost queries. Default: empty (no tag).
set -euo pipefail

if [ $# -lt 2 ]; then
  echo "usage: run-eval-v3.sh <IV2|D1> <model> [variant] [run_tag]" >&2
  echo "  run_tag            optional token appended to the session title" >&2
  echo "                     (e.g. r2) so §5.4 re-run arms never collide with" >&2
  echo "                     run 1 in cost queries; default: none" >&2
  echo "  EVAL_TIER=<tier>   cheap|mid|strong -> cap 0.05|0.30|1.00 USD" >&2
  echo "  EVAL_ARM_CAP=<usd> per-arm cost cap in USD; overrides EVAL_TIER;" >&2
  echo "                     the arm is killed when its DB cost (parent +" >&2
  echo "                     children) exceeds 2x the cap" >&2
  echo "  One of EVAL_TIER or EVAL_ARM_CAP is REQUIRED — the script aborts" >&2
  echo "  with a usage error if neither is set (no implicit default cap)." >&2
  exit 1
fi
TASK=$1; MODEL=$2; VARIANT=${3:-}; RUN_TAG=${4:-}
EVAL_DIR="$(cd "$(dirname "$0")" && pwd)"
WORK="${TMPDIR:-/tmp}/bench-v3-$$"
TIMEOUT_SECS="${EVAL_TIMEOUT_SECS:-900}"   # 15-minute wall-clock watchdog per arm (BENCH-V3-DESIGN §5.8); EVAL_TIMEOUT_SECS overrides (deviation must be recorded)
# Fail closed on tier (BENCH-V3-DESIGN §5.8): an explicit per-arm cap is
# mandatory — defaulting to a tier would let an unconfigured launch run
# uncapped if the poller degrades. Either EVAL_TIER or EVAL_ARM_CAP must
# be set, or the launch aborts here.
if [ -z "${EVAL_TIER:-}" ] && [ -z "${EVAL_ARM_CAP:-}" ]; then
  echo "error: no per-arm cost cap configured — set EVAL_TIER (cheap|mid|strong)" >&2
  echo "or EVAL_ARM_CAP (<usd>) explicitly; the campaign must not start without" >&2
  echo "an explicit cap (BENCH-V3-DESIGN §5.8)" >&2
  exit 1
fi
case "${EVAL_TIER:-}" in
  cheap)  TIER_CAP="0.05" ;;
  mid)    TIER_CAP="0.30" ;;
  strong) TIER_CAP="1.00" ;;
  "")     TIER_CAP="" ;;   # EVAL_ARM_CAP is set explicitly; it overrides below
  *) echo "unknown EVAL_TIER: ${EVAL_TIER} (expected cheap|mid|strong)" >&2; exit 1 ;;
esac
EVAL_ARM_CAP="${EVAL_ARM_CAP:-$TIER_CAP}"   # per-arm cost cap, USD (EVAL_ARM_CAP overrides EVAL_TIER)
OC_DB="${HOME}/.local/share/opencode/opencode.db"

case $TASK in
  IV2)
    FIXTURE=reportgen-eval-repo-i3; CODE=IV2; FIXCODE=RG3
    PROMPT="Work in this repo copy alone — no subagents, no delegation. Read GOAL.md and do what it asks: implement the requested feature in this repo copy, fix any defects you find with the smallest change that keeps the suite green and the stated invariants holding, add a regression test per fixed defect, and state in your final report any trade-off the brief leaves open, with the choice you made and the cost it accepts. Do not refactor; do not touch unrelated tests."
    ;;
  D1)
    FIXTURE=syncfeat-brief-d1; CODE=D; FIXCODE=D1
    PROMPT="Work in this repo copy alone — no subagents, no delegation. Read BRIEF.md and write the design it asks for to DESIGN-d1.md in this repo copy."
    ;;
  *) echo "unknown task: $TASK (expected IV2 or D1)" >&2; exit 1 ;;
esac

TAG="$(echo "$MODEL" | tr '/. ' '---')${VARIANT:+-$VARIANT}${RUN_TAG:+-$RUN_TAG}"
TITLE="eval-$(date +%F)-${CODE}-${FIXCODE}-${TAG}"

# Preflight (BENCH-V3-DESIGN §5.8/§7.6): cost caps are procedural + tooling;
# the campaign must not start without them active. Abort BEFORE launching
# the arm if the DB cost path cannot work.
if ! command -v sqlite3 >/dev/null 2>&1; then
  echo "preflight: sqlite3 not found in PATH — the cost-cap poller cannot run (BENCH-V3-DESIGN §5.8/§7.6); aborting before launch" >&2
  exit 1
fi
if [ ! -f "$OC_DB" ]; then
  echo "preflight: opencode DB not found at $OC_DB — cost polling impossible (BENCH-V3-DESIGN §5.8/§7.6); aborting before launch" >&2
  exit 1
fi
if ! sqlite3 "$OC_DB" "SELECT 1 FROM session LIMIT 1;" >/dev/null 2>&1; then
  echo "preflight: cannot query the session table in $OC_DB (missing schema or unreadable DB) — aborting before launch (BENCH-V3-DESIGN §5.8/§7.6)" >&2
  exit 1
fi
# Exact cost-query shape: a session table lacking cost/parent_id would make
# the cost-cap poller silently inert (its query fails every cycle and is
# only warned about) — the arm would run uncapped, contradicting §5.8.
if ! sqlite3 "$OC_DB" "SELECT cost, parent_id FROM session LIMIT 1;" >/dev/null 2>&1; then
  echo "preflight: the session table in $OC_DB lacks cost/parent_id columns — the cost-cap poller would be silently inert (BENCH-V3-DESIGN §5.8); aborting before launch" >&2
  exit 1
fi

cp -R "$EVAL_DIR/$FIXTURE" "$WORK"

# NETWORK-ISOLATION note (BENCH-V3-DESIGN §5.8/§7.2 script-spec line-item):
# the fixture is already a fresh plain-file copy; when the harness allows it,
# run the arm with network access restricted to the model provider endpoint
# (sandbox / proxy) so the candidate cannot fetch the public kit repo during
# the run. Insert the isolation wrapper around the opencode invocation below.

# Shared kill path for the watchdog and the cost-cap poller: TERM the
# opencode pid and its direct children, then KILL after a grace period.
# Without job control a background job shares this script's process group,
# so a pgid-based group kill would hit the script itself — kill the pid
# plus its children only.
kill_arm() {
  pkill -TERM -P "$OPENCODE_PID" 2>/dev/null || true
  kill -TERM "$OPENCODE_PID" 2>/dev/null || true
  sleep 5
  pkill -KILL -P "$OPENCODE_PID" 2>/dev/null || true
  kill -KILL "$OPENCODE_PID" 2>/dev/null || true
}

if [ -n "$VARIANT" ]; then
  opencode run --dir "$WORK" --model "$MODEL" --variant "$VARIANT" \
    --title "$TITLE" --auto "$PROMPT" &
else
  opencode run --dir "$WORK" --model "$MODEL" \
    --title "$TITLE" --auto "$PROMPT" &
fi
OPENCODE_PID=$!

# Cost-cap poller (BENCH-V3-DESIGN §5.8): every 5 min, sum the session cost
# for the arm's exact title plus its child sessions (children roll up via
# session.parent_id where the DB allows — delegation rule: arm cost =
# parent + ALL children, never the parent alone). A missing/unreadable DB
# is warned about once and polling continues.
COST_Q="SELECT SUM(cost) FROM session \
WHERE title = '$TITLE' \
   OR parent_id = (SELECT id FROM session WHERE title = '$TITLE');"
(
  db_warned=0
  while :; do
    sleep 300
    if ! cost="$(sqlite3 "$OC_DB" "$COST_Q" 2>/dev/null)"; then
      # Query failed: DB missing/unreadable/corrupt or schema not ready
      # yet. Warn once and keep polling (never kill on a read failure).
      if [ "$db_warned" -eq 0 ]; then
        echo "warn: cannot read $OC_DB — cost polling degraded, continuing" >&2
        db_warned=1
      fi
      continue
    fi
    if [ -z "$cost" ]; then
      continue   # session not in the DB yet (SUM = NULL), normal early
    fi
    if [ "$(awk -v c="$cost" -v cap="$EVAL_ARM_CAP" \
           'BEGIN { print (c + 0 > 2 * cap) ? 1 : 0 }')" = 1 ]; then
      # Record BEFORE killing: kill_arm's TERM unblocks the main wait,
      # whose cleanup kills this watcher — a marker written after the kill
      # would be lost (observed in smoke testing).
      date +%s > "$WORK/arm-killed-costcap"
      kill_arm
      break
    fi
  done
) &
COST_POLLER_PID=$!

# 15-minute wall-clock watchdog — macOS-safe (no timeout/gtimeout
# dependency): a background watcher sleeps for the budget, then, if the arm
# is still running, kills it via kill_arm and records arm-killed-timeout in
# the run dir.
(
  sleep "$TIMEOUT_SECS"
  if kill -0 "$OPENCODE_PID" 2>/dev/null; then
    # Record BEFORE killing (same reason as the cost-cap poller above).
    date +%s > "$WORK/arm-killed-timeout"
    kill_arm
  fi
) &
WATCHDOG_PID=$!

set +e
wait "$OPENCODE_PID"
RUN_STATUS=$?
set -e

# Arm finished (normally or killed): stop both watchers AND their sleep
# children — killing a watcher subshell alone would leave its `sleep`
# grandchild (up to 15 min / 5 min) running for nothing.
for watcher in "$COST_POLLER_PID" "$WATCHDOG_PID"; do
  pkill -TERM -P "$watcher" 2>/dev/null || true
  kill "$watcher" 2>/dev/null || true
done
wait "$COST_POLLER_PID" 2>/dev/null || true
wait "$WATCHDOG_PID" 2>/dev/null || true

if [ -f "$WORK/arm-killed-costcap" ]; then
  echo "arm-killed-costcap: $TITLE cost exceeded 2x EVAL_ARM_CAP (cap \$$EVAL_ARM_CAP); run dir: $WORK" >&2
  exit 125
fi

if [ -f "$WORK/arm-killed-timeout" ]; then
  echo "arm-killed-timeout: $TITLE hit the 15-min watchdog; run dir: $WORK" >&2
  exit 124
fi

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

echo "run dir: $WORK (cost/tokens: sqlite3 ~/.local/share/opencode/opencode.db, session title $TITLE above)"
exit "$RUN_STATUS"
