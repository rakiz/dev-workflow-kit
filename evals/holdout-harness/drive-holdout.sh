#!/usr/bin/env bash
# drive-holdout.sh — held-out campaign driver (HOLDOUT-SPEC §5.5-§5.6, §7.1, §7.5). Adapts run-campaign.py.
#   drive-holdout.sh --self-check            preflight (no live call) + campaign file + run-campaign --self-check
#   drive-holdout.sh --self-check-stub       same, with ONE zero-cost stub arm (no model call; exercises admission)
#   drive-holdout.sh --launch-mandatory      preflight --live, then launch the mandatory block   (owner go only)
#   optional 2nd arg --prices-accepted: accept an ai-gateway-misc price drift vs the last launch (run-campaign gate)
# Default is --self-check. Campaign files go to evals-keys/holdout-campaigns/ (private, with run logs).
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
EVALS="$(cd "$HERE/.." && pwd)"
REPO="$(cd "$HERE/../../.." && pwd)"
MODE="${1:---self-check}"
PA="${2:-}"
if [ -n "$PA" ] && [ "$PA" != --prices-accepted ]; then echo "usage: drive-holdout.sh [mode] [--prices-accepted]" >&2; exit 2; fi
DATE="$(date +%F)"
SUFFIX="${HOLDOUT_CAMPAIGN_SUFFIX:-}"   # relaunch id (arms are single-use: a new suffix means new titles)
OUT="$REPO/evals-keys/holdout-campaigns"; mkdir -p "$OUT"

write_campaign() {   # $1 = file, $2 = stub|mandatory
  python3 -B - "$1" "$2" "$DATE" "$SUFFIX" <<'PY'
import json, sys
path, mode, date, suffix = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4]
benches = {
    "HO2": {"runner": "run-eval-v6.sh", "task": "HO2", "title_token": "HO2-SP2"},
    "HOD": {"runner": "run-eval-v6.sh", "task": "HOD", "title_token": "HOD-US2"},
}
if mode == "stub":
    arms = [{"bench": "HO2", "model": "stub/zero-cost", "cap": 0.01, "attempts": 1, "timeout": 900}]
    cid, budget = "holdout-stub-self-check", 0.05
else:
    # §14.3 repair block (opus-HO2 dropped); caps per run, the arm is killed at 2x cap (M13)
    arms = [
        {"bench": "HO2", "model": "github-copilot/claude-haiku-5.5", "cap": 0.06, "attempts": 4, "timeout": 900},
        {"bench": "HO2", "model": "ai-gateway-misc/fw-glm-5.3-flash", "variant": "high", "cap": 0.06, "attempts": 4, "timeout": 900},
        {"bench": "HO2", "model": "fireworks-ai/accounts/fireworks/models/minimax-m3p1-flash", "variant": "xhigh", "cap": 0.20, "attempts": 4, "timeout": 900},
        {"bench": "HOD", "model": "github-copilot/claude-haiku-5.5", "variant": "medium", "cap": 0.08, "attempts": 4, "timeout": 900},
        {"bench": "HOD", "model": "fireworks-ai/accounts/fireworks/models/deepseek-v4p1-flash-1017", "variant": "high", "cap": 0.40, "attempts": 2, "timeout": 900},
    ]
    cid, budget = "holdout-mandatory-" + date + suffix, 10.00
doc = {"id": cid, "date": date, "budget_usd": budget, "parallelism": 1, "timeout_default": 900,
       "benches": benches, "arms": arms}
json.dump(doc, open(path, "w"), indent=2)
print("wrote", path)
PY
}

# egress (owner amendment): one CA per campaign for TLS termination + metering; no credential file
CAMP_ID="holdout-mandatory-$DATE$SUFFIX"
export HOLDOUT_CAMP_DIR="$HOME/.local/state/holdout-campaigns/$CAMP_ID"
PROVIDER_HOSTS=(ai-gateway.corp.mongodb.com api.fireworks.ai api.githubcopilot.com)

prepare_route() {   # launch: the campaign CA (refuses on failure)
  "$HERE/holdout-ca.sh" "$HOLDOUT_CAMP_DIR" "${PROVIDER_HOSTS[@]}"
}

case "$MODE" in
  --self-check|--self-check-stub)
    if [ "$MODE" = --self-check-stub ]; then
      F="$OUT/holdout-stub-$DATE.json"; write_campaign "$F" stub
    else
      F="$OUT/holdout-$DATE$SUFFIX.json"; write_campaign "$F" mandatory
    fi
    "$HERE/preflight.sh" && HOLDOUT_PREFLIGHT_OK=1 || { echo "preflight FAILED: no arm may run (§5.5)" >&2; exit 1; }
    if [ "$MODE" = --self-check ]; then prepare_route; fi
    python3 -B "$EVALS/run-campaign.py" "$F" --self-check $PA
    ;;
  --launch-mandatory)
    F="$OUT/holdout-$DATE$SUFFIX.json"; write_campaign "$F" mandatory
    prepare_route
    "$HERE/preflight.sh" --live || { echo "preflight --live FAILED: campaign aborted (§5.5)" >&2; exit 1; }
    HOLDOUT_PREFLIGHT_OK=1 python3 -B "$EVALS/run-campaign.py" "$F" $PA
    ;;
  *) echo "usage: drive-holdout.sh [--self-check|--self-check-stub|--launch-mandatory]" >&2; exit 2 ;;
esac
