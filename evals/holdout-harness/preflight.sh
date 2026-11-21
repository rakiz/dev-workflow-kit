#!/usr/bin/env bash
# preflight.sh [--live] — fail-closed isolation preflight (HOLDOUT-SPEC §5.5 assertions 1-7; pass-through egress).
#   Non-live (default): no provider traffic, no model call. Live-only checks are UNTESTED-LIVE.
#   --live: adds A6 (one trivial run, ~$0.001 on the cheapest arm) and the live A8 (a GET to the real provider
#           through the proxy with a bogus key; no model call). Run only on the owner's authorisation.
# Every denial assertion carries a control: the same read must SUCCEED outside the sandbox.
# Exit 1 if any assertion FAILs: no arm may run.
set -uo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
REPO="$(cd "$HERE/../../.." && pwd)"
LIVE=0; [ "${1:-}" = "--live" ] && LIVE=1
TMPBASE="$(cd "${TMPDIR:-/tmp}" && pwd -P)"; TMPBASE="${TMPBASE%/}"
ARM="eval-$(date +%F)-HO2-PREFLIGHT-$$"
PORT="${HOLDOUT_PROXY_PORT:-18765}"; UP_PORT=18901
GLOBAL_OC_DB="$HOME/.local/share/opencode/opencode.db"
HOST_AUTH="$HOME/.local/share/opencode/auth.json"
CAMP="$TMPBASE/holdout-camp-preflight-$$"; UPCA="$TMPBASE/holdout-upca-preflight-$$"
FAILS=0
say() { printf '%s %s\n' "$1" "$2"; [ "$1" = "FAIL" ] && FAILS=$((FAILS+1)); return 0; }
PIDS=()
cleanup() {
  for p in "${PIDS[@]:-}"; do kill "$p" 2>/dev/null; done
  for t in "$ARM" "${ARMLIVE:-}"; do
    [ -n "$t" ] || continue
    for d in holdout-work holdout-xdg holdout-cfg holdout-tmp holdout-home; do rm -rf "$TMPBASE/$d/$t"; done
  done
  rm -rf "$CAMP" "$UPCA" 2>/dev/null
}
trap cleanup EXIT

if [ "$LIVE" = 1 ]; then
  export ARM_MODEL="${HOLDOUT_LIVE_MODEL:-ai-gateway-misc/fw-deepseek-v4.1-flash}"
else
  export ARM_MODEL="github-copilot/preflight-stub"
fi
LIVE_HOST="$(python3 -B "$HERE/holdout-provider.py" meta --model "$ARM_MODEL" | python3 -c 'import json,sys;print(json.load(sys.stdin)["host"])')"
HOSTS=(api.invalid.example api.test.invalid)
[ "$LIVE" = 1 ] && HOSTS+=("$LIVE_HOST")

"$HERE/holdout-ca.sh" "$CAMP" "${HOSTS[@]}" >/dev/null || { say FAIL "setup: campaign CA"; exit 1; }
"$HERE/holdout-ca.sh" "$UPCA" upstream-ca api.test.invalid >/dev/null || { say FAIL "setup: upstream CA"; exit 1; }
export HOLDOUT_CAMP_DIR="$CAMP"
"$HERE/holdout-arm.sh" prepare "$ARM" "$REPO/dev-workflow-kit/evals/heldout-impl-sp1" "$PORT" >/dev/null || { say FAIL "setup: arm prepare failed"; exit 1; }
eval "$("$HERE/holdout-arm.sh" paths "$ARM")"
trap 'cleanup' EXIT

python3 -B "$HERE/holdout-stub-upstream.py" --port "$UP_PORT" --cert "$UPCA/api.test.invalid.pem" \
  --key "$UPCA/api.test.invalid.key" --header Authorization --expect "Bearer BOGUS-IN-ARM" >/dev/null 2>&1 &
PIDS+=($!)
ALLOW="$(IFS=,; echo "${HOSTS[*]}")"
python3 -B "$HERE/holdout-proxy.py" --port "$PORT" --allow "$ALLOW" --campaign-dir "$CAMP" \
  --metrics "$ARM_TMP/proxy.json" --cap-bytes 100000000 \
  --upstream-override "api.test.invalid=127.0.0.1:$UP_PORT" --upstream-ca "$UPCA/ca.pem" >/dev/null 2>"$ARM_TMP/proxy.err" &
PIDS+=($!)
sleep 1
kill -0 "${PIDS[1]}" 2>/dev/null || { say FAIL "setup: proxy refused to start (fail closed): $(cat "$ARM_TMP/proxy.err")"; exit 1; }
export PROXY_PORT="$PORT"
X() { "$HERE/holdout-arm.sh" exec "$ARM" -- "$@"; }
meter() { python3 -B -c "import json;m=json.load(open('$ARM_TMP/proxy.json'));print(m['$1'])" 2>/dev/null || echo 0; }
meter_live() { python3 -B -c "import json;m=json.load(open('$ARM_TMP/proxy-live.json'));print(m['$1'])" 2>/dev/null || echo 0; }

# 1. network: direct outbound fails inside the sandbox; the control succeeds outside it
if ! X /usr/bin/curl -sS -m 10 https://example.com >/dev/null 2>&1 && /usr/bin/curl -sS -m 10 -o /dev/null https://example.com >/dev/null 2>&1; then
  say PASS "A1 curl https://example.com denied inside sandbox (control: reachable outside)"
else say FAIL "A1 curl https://example.com not denied, or control unreachable"; fi

# 2. global opencode DB unreadable inside the sandbox (control: readable outside)
if ! X /usr/bin/sqlite3 "$GLOBAL_OC_DB" 'select 1' >/dev/null 2>&1 && /usr/bin/sqlite3 "$GLOBAL_OC_DB" 'select 1' >/dev/null 2>&1; then
  say PASS "A2 global opencode.db unreadable inside sandbox (control: readable outside)"
else say FAIL "A2 global opencode.db readable inside sandbox, or control unreadable"; fi

# 3. the private answer key unreadable inside the sandbox (control: readable outside)
KEY="$REPO/evals-keys/HOLDOUT-KEY-HO2.md"
if ! X /bin/cat "$KEY" >/dev/null 2>&1 && /bin/cat "$KEY" >/dev/null 2>&1; then
  say PASS "A3 HOLDOUT-KEY-HO2.md unreadable inside sandbox"
else say FAIL "A3 answer key readable inside sandbox, or control missing"; fi

# 4. private reference-fixed tree unreadable inside the sandbox (M12)
REF="$REPO/evals-keys/ho2-ref-a/planio.py"
if ! X /bin/cat "$REF" >/dev/null 2>&1 && /bin/cat "$REF" >/dev/null 2>&1; then
  say PASS "A4 ho2-ref-a/planio.py unreadable inside sandbox"
else say FAIL "A4 reference tree readable inside sandbox, or control missing"; fi

# 5. host auth store and the campaign CA key unreadable inside; the arm's OWN auth.json copy is present (owner amendment)
if ! X /bin/cat "$HOST_AUTH" >/dev/null 2>&1 && /bin/cat "$HOST_AUTH" >/dev/null 2>&1 \
   && ! X /bin/cat "$CAMP/ca.key" >/dev/null 2>&1 && /bin/cat "$CAMP/ca.key" >/dev/null 2>&1 \
   && [ -f "$ARM_DATA/opencode/auth.json" ]; then
  say PASS "A5 host auth.json and campaign CA key unreadable inside sandbox; arm's own auth.json copy present"
else say FAIL "A5 host auth or CA key readable inside sandbox, or the arm auth copy is missing"; fi

# 7. poller liveness: per-arm heartbeat before the first minute; campaign-level kill poller
HB="$ARM_TMP/hb-arm"
"$HERE/holdout-heartbeat.sh" "$HB" 1 & HBP=$!
sleep 3; kill $HBP 2>/dev/null; wait $HBP 2>/dev/null
if [ -s "$HB" ]; then say PASS "A7a per-arm poller heartbeat written"; else say FAIL "A7a per-arm poller heartbeat missing"; fi
if python3 -B "$REPO/dev-workflow-kit/evals/run-campaign.py" --poller-selftest >/dev/null 2>&1; then
  say PASS "A7b campaign-level kill poller heartbeat (run-campaign.py --poller-selftest)"
else say FAIL "A7b campaign-level kill poller heartbeat missing"; fi

# 8s. pass-through egress (owner amendment; non-live, stub upstream)
#   (a) a NON-allowlisted host is refused with 403 by the proxy and counted as denied;
#   (b) an allowlisted host receives the client's own (bogus) auth header AS-IS (the proxy does not rewrite),
#       the stub answers AUTH-OK, and the proxy meter increments.
denied_before=$(meter denied); req_before=$(meter requests); up_before=$(meter bytes_up)
X /usr/bin/curl -sS -o /dev/null -w '%{http_code}' https://evil.example/ >"$ARM_TMP/a8s-deny.code" 2>/dev/null
denied_after=$(meter denied)
if [ "$denied_after" -gt "$denied_before" ]; then   # the proxy's own counter is the evidence of the 403
  a8a=PASS; else a8a=FAIL; fi
body="$(X /usr/bin/curl -sS --cacert "$ARM_CFG/ca.pem" -H "Authorization: Bearer BOGUS-IN-ARM" https://api.test.invalid/ 2>"$ARM_TMP/a8s.err")"; rc8=$?
req_after=$(meter requests); up_after=$(meter bytes_up)
if [ "$rc8" = 0 ] && [ "$body" = "AUTH-OK" ] && [ "$req_after" -gt "$req_before" ] && [ "$up_after" -gt "$up_before" ]; then
  a8b=PASS; else a8b=FAIL; fi
if [ "$a8a" = PASS ] && [ "$a8b" = PASS ]; then
  say PASS "A8s pass-through: non-allowlisted host 403 and metered denied; allowlisted host got the client's auth as-is (AUTH-OK), meter +requests +bytes"
else say FAIL "A8s pass-through: non-allowlisted=$a8a allowlisted=$a8b (rc=$rc8 body=[${body:0:40}])"; fi

# LIVE SETUP (only with --live): a DEDICATED pass-through proxy (no test-CA override: the real host must verify
# against the system store) and a DEDICATED arm whose profile allows that proxy's port. Defined ONCE, before
# A6 and A8-live use it.
if [ "$LIVE" = 1 ]; then
  LIVE_PORT=$((PORT + 1)); LIVE_METER="$ARM_TMP/proxy-live.json"
  python3 -B "$HERE/holdout-proxy.py" --port "$LIVE_PORT" --allow "$LIVE_HOST" --campaign-dir "$CAMP" \
    --metrics "$LIVE_METER" --cap-bytes 100000000 >/dev/null 2>"$ARM_TMP/proxy-live.err" &
  PIDS+=($!); LIVE_PROXY_PID=$!
  sleep 1
  if ! kill -0 "$LIVE_PROXY_PID" 2>/dev/null; then say FAIL "setup: live proxy refused to start: $(cat "$ARM_TMP/proxy-live.err")"; exit 1; fi
  ARMLIVE="$ARM-LIVE"
  "$HERE/holdout-arm.sh" prepare "$ARMLIVE" "$REPO/dev-workflow-kit/evals/heldout-impl-sp1" "$LIVE_PORT" >/dev/null \
    || { say FAIL "setup: live arm prepare failed"; exit 1; }
  eval "$("$HERE/holdout-arm.sh" paths "$ARMLIVE")"
  X2() { "$HERE/holdout-arm.sh" exec "$ARMLIVE" -- "$@"; }
  live_meter() { python3 -B -c "import json;print(json.load(open('$LIVE_METER'))['$1'])" 2>/dev/null || echo 0; }
fi

# 6. trivial opencode run with the per-arm data dir: exit 0, DB written, live proxy metered (LIVE ONLY)
if [ "$LIVE" = 1 ]; then
  req_before=$(live_meter requests)
  X2 opencode run --dir "$ARM_WORK" --model "$ARM_MODEL" --title "$ARMLIVE" --auto "reply with the word ok" >"$ARM_TMP/a6.log" 2>&1; rc=$?
  cp "$ARM_TMP/a6.log" "$HERE/a6-last.log" 2>/dev/null || true
  metered=$(live_meter requests)
  if [ "$rc" = 0 ] && [ -f "$ARM_DATA/opencode/opencode.db" ] && [ "$metered" -gt "$req_before" ]; then
    say PASS "A6 live run exit 0, per-arm DB written, live proxy metered requests=$metered"
  else say FAIL "A6 live run rc=$rc metered=$metered (log: $HERE/a6-last.log)"; fi
else
  say UNTESTED-LIVE "A6 trivial opencode run (needs a provider call; preflight.sh --live, ~\$0.001)"
fi

# A8 (LIVE ONLY): the real provider through the live proxy with a bogus key; a plain GET to the root (no model call).
#   Success: the request reaches the provider (an HTTP status, not 000, not the proxy's own 502), the live proxy
#   meters it, TLS verifies against the campaign CA, and the public trust store does NOT verify the same chain.
if [ "$LIVE" = 1 ]; then
  req_before=$(live_meter requests)
  X2 /usr/bin/curl -sS --cacert "$ARM_CFG/ca.pem" -o "$ARM_TMP/a8-live.body" -w '%{http_code}' \
    -H "Authorization: Bearer BOGUS-IN-ARM" "https://$LIVE_HOST/" >"$ARM_TMP/a8-live.code" 2>"$ARM_TMP/a8-live.err"; rcl=$?
  CODE="$(cat "$ARM_TMP/a8-live.code" 2>/dev/null)"
  sysl=$(env -i /usr/bin/curl -sS -o /dev/null --proxy "http://127.0.0.1:$LIVE_PORT" "https://$LIVE_HOST/" >/dev/null 2>&1; echo $?)
  req_after=$(live_meter requests)
  if [ "$rcl" = 0 ] && [ "$CODE" != "000" ] && [ "$CODE" != "502" ] && [ "$req_after" -gt "$req_before" ] && [ "$sysl" = 60 ]; then
    say PASS "A8 live: $LIVE_HOST reached through the proxy; http=$CODE; metered; system trust rc=60"
  else say FAIL "A8 live: rc=$rcl http=$CODE metered=$req_after system-trust rc=$sysl err=$(head -c 200 "$ARM_TMP/a8-live.err" 2>/dev/null)"; fi
else
  say UNTESTED-LIVE "A8 live provider interception (real host, bogus key; preflight.sh --live)"
fi

echo "PREFLIGHT $([ "$FAILS" = 0 ] && echo PASS || echo FAILED) fails=$FAILS live=$LIVE"
exit $([ "$FAILS" = 0 ] && echo 0 || echo 1)
