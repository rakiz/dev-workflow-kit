#!/usr/bin/env bash
# selftest-sandbox.sh — direct /bin/cat checks against every path §5.5 says must be denied, from inside
# an arm's sandbox, each with an outside-the-sandbox control. No model call. Exit 1 on any mismatch.
set -uo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
REPO="$(cd "$HERE/../../.." && pwd)"
A="eval-$(date +%F)-HO2-SBTEST-A-$$"; B="eval-$(date +%F)-HO2-SBTEST-B-$$"
export ARM_MODEL="github-copilot/sbtest"
TMPBASE="$(cd "${TMPDIR:-/tmp}" && pwd -P)"; TMPBASE="${TMPBASE%/}"
export HOLDOUT_CAMP_DIR="$TMPBASE/holdout-camp-sbtest-$$"
"$HERE/holdout-ca.sh" "$HOLDOUT_CAMP_DIR" api.fireworks.ai >/dev/null
"$HERE/holdout-arm.sh" prepare "$A" "$REPO/dev-workflow-kit/evals/heldout-impl-sp2" 18766 >/dev/null
"$HERE/holdout-arm.sh" prepare "$B" "$REPO/dev-workflow-kit/evals/heldout-impl-sp2" 18767 >/dev/null
eval "$("$HERE/holdout-arm.sh" paths "$A")"; B_WORK="$(dirname "$ARM_WORK")/$B"
B_DATA="$(dirname "$ARM_DATA")/$B"
echo sibling-secret > "$B_DATA/opencode/opencode.db"   # control: the file must exist and be readable outside
trap 'rm -rf "$HOLDOUT_CAMP_DIR" "$(dirname "$ARM_WORK")/$A" "$(dirname "$ARM_WORK")/$B" "$(dirname "$ARM_DATA")/$A" "$(dirname "$ARM_DATA")/$B" "$(dirname "$ARM_CFG")/$A" "$(dirname "$ARM_CFG")/$B" "$(dirname "$ARM_TMP")/$A" "$(dirname "$ARM_TMP")/$B" "$(dirname "$ARM_HOME")/$A" "$(dirname "$ARM_HOME")/$B"' EXIT
export PROXY_PORT=18766
X() { "$HERE/holdout-arm.sh" exec "$A" -- "$@"; }
FAILS=0
expect_deny() {   # label, path  (must FAIL inside, SUCCEED outside)
  if X /bin/cat "$2" >/dev/null 2>&1 || ! /bin/cat "$2" >/dev/null 2>&1; then
    echo "FAIL deny: $1 ($2)"; FAILS=$((FAILS+1))
  else echo "PASS deny: $1"; fi
}
expect_allow() {  # label, path (must SUCCEED inside)
  if X /bin/cat "$2" >/dev/null 2>&1; then echo "PASS allow: $1"; else echo "FAIL allow: $1 ($2)"; FAILS=$((FAILS+1)); fi
}
expect_deny "private answer key"            "$REPO/evals-keys/HOLDOUT-KEY-HO2.md"
expect_deny "private key HOD"               "$REPO/evals-keys/HOLDOUT-KEY-HOD.md"
expect_deny "reference-fixed tree (M12)"    "$REPO/evals-keys/ho2-ref-a/planio.py"
expect_deny "reference-fixed tree B"        "$REPO/evals-keys/ho2-ref-b/planio.py"
expect_deny "repaired US1 tree (M12)"       "$REPO/evals-keys/us1-repaired/chunkstore.py"
expect_deny "source fixture location"       "$REPO/dev-workflow-kit/evals/heldout-impl-sp2/plan.py"
expect_deny "global opencode DB"            "$HOME/.local/share/opencode/opencode.db"
expect_deny "host credential auth.json (M10)" "$HOME/.local/share/opencode/auth.json"
expect_deny "global opencode config"        "$HOME/.config/opencode/opencode.jsonc"
expect_deny "campaign CA private key (OPEN-1)" "$HOLDOUT_CAMP_DIR/ca.key"
expect_deny "sibling arm work dir (M9)"     "$B_WORK/plan.py"
expect_deny "sibling arm data dir (M9)"     "$B_DATA/opencode/opencode.db"
expect_allow "own work dir"                 "$ARM_WORK/plan.py"
expect_allow "own config (read-only)"       "$ARM_CFG/opencode/opencode.json"
expect_allow "campaign CA certificate (public, in arm cfg)" "$ARM_CFG/ca.pem"
expect_allow "arm's own auth.json copy (owner amendment)" "$ARM_DATA/opencode/auth.json"
# the arm env must trust the campaign CA for both runtimes (OPEN-1: Bun/Node coverage)
envout="$(X /usr/bin/env)"
if grep -q "^NODE_EXTRA_CA_CERTS=$ARM_CFG/ca.pem$" <<<"$envout" && grep -q "^SSL_CERT_FILE=$ARM_CFG/ca.pem$" <<<"$envout" && grep -q "^HTTPS_PROXY=http://127.0.0.1:" <<<"$envout"; then
  echo "PASS arm env: NODE_EXTRA_CA_CERTS + SSL_CERT_FILE = campaign CA, HTTPS_PROXY = local proxy"
else echo "FAIL arm env missing CA/proxy vars"; FAILS=$((FAILS+1)); fi
# write rights: own work dir yes; the config dir must stay read-only
if X /bin/sh -c "echo w > '$ARM_WORK/probe.txt'" >/dev/null 2>&1; then echo "PASS write own work dir"; else echo "FAIL write own work dir"; FAILS=$((FAILS+1)); fi
if X /bin/sh -c "echo w > '$ARM_CFG/opencode/probe.txt'" >/dev/null 2>&1; then echo "FAIL config dir writable (must be read-only)"; FAILS=$((FAILS+1)); else echo "PASS config dir read-only"; fi
# network: only the local proxy port
if X /usr/bin/curl -sS -m 8 -o /dev/null http://1.1.1.1/ >/dev/null 2>&1; then echo "FAIL direct IP egress allowed"; FAILS=$((FAILS+1)); else echo "PASS direct IP egress denied"; fi
echo "SANDBOX-SELFTEST fails=$FAILS"
exit $([ "$FAILS" = 0 ] && echo 0 || echo 1)
