#!/usr/bin/env bash
# run-adj.sh <adj-neon|adj-qwen> <model> — one adjudicator session in the arm sandbox (blind: the keys and the id map
# are outside the sandbox; the bundle is copied in before the profile applies). Cap $2.50, kill at 2x.
set -euo pipefail
NAME="$1"; MODEL="$2"
HERE="$(cd "$(dirname "$0")" && pwd)"; REPO="$(cd "$HERE/../../../.." && pwd)"
HARN="$REPO/dev-workflow-kit/evals/holdout-harness"
KEYS="$REPO/evals-keys/ab-2026-11-21"
CAMP="$HOME/.local/state/holdout-campaigns/holdout-mandatory-2026-11-21-2"
FIX="$KEYS/adj/$NAME"
TITLE="ab-ADJ-$NAME"
export ARM_MODEL="$MODEL" HOLDOUT_CAMP_DIR="$CAMP"
PORT="$(python3 -B -c 'import socket;s=socket.socket();s.bind(("127.0.0.1",0));print(s.getsockname()[1]);s.close()')"
"$HARN/holdout-arm.sh" prepare "$TITLE" "$FIX" "$PORT" >/dev/null
eval "$("$HARN/holdout-arm.sh" paths "$TITLE")"
HOST="$(python3 -B "$HARN/holdout-provider.py" meta --model "$MODEL" | python3 -c 'import json,sys;print(json.load(sys.stdin)["host"])')"
python3 -B "$HARN/holdout-proxy.py" --port "$PORT" --allow "$HOST" --campaign-dir "$CAMP" --metrics "$ARM_TMP/proxy.json" \
  --cap-bytes "${HOLDOUT_BYTE_CAP:-400000000}" >/dev/null 2>"$ARM_TMP/proxy.err" & PX=$!
sleep 1; kill -0 $PX 2>/dev/null || { echo "proxy failed" >&2; exit 1; }
"$HARN/holdout-arm.sh" exec "$TITLE" -- opencode run --dir "$ARM_WORK" --model "$MODEL" --title "$TITLE" --auto \
  "Read PROMPT.md in this directory and follow it exactly." >"$ARM_TMP/session.log" 2>&1 & OP=$!
START=$(date +%s); OC_DB="$ARM_DATA/opencode/opencode.db"
while kill -0 $OP 2>/dev/null; do
  sleep 20
  c="$(sqlite3 "$OC_DB" "SELECT COALESCE(SUM(cost),0) FROM session;" 2>/dev/null || echo 0)"
  if awk -v c="$c" 'BEGIN{exit !(c+0 > 5.00)}'; then echo "adj costcap kill: $c" >&2; pkill -TERM -P $OP 2>/dev/null; kill -TERM $OP 2>/dev/null; break; fi
  if [ $(( $(date +%s) - START )) -gt 1800 ]; then echo "adj wall kill" >&2; pkill -TERM -P $OP 2>/dev/null; kill -TERM $OP 2>/dev/null; break; fi
done
wait $OP 2>/dev/null || true; kill $PX 2>/dev/null || true
if [ -f "$ARM_WORK/sheet.tsv" ]; then cp "$ARM_WORK/sheet.tsv" "$KEYS/adj/$NAME.sheet.tsv"; echo "WROTE $NAME"; else echo "NO-SHEET $NAME"; fi
