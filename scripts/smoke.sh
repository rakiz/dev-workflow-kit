#!/usr/bin/env bash
# scripts/smoke.sh — end-to-end smoke test of the kit, in throwaway sandboxes.
#
#   scripts/smoke.sh          run every check; exit 0 when all pass, 1 otherwise
#
# Never touches the real opencode config directory or any real project: the
# global roster runs with OPENCODE_CONFIG_DIR pointed at a fresh temp dir, and
# the project install runs in a fresh git repo. Checks:
#   1. global: fresh install -> --update twice -> --doctor; afterwards exactly
#      16 agents, a lock file, no *.dev-workflow-kit-new/-prev sibling and no
#      backup directory (a clean install must leave none of them behind);
#   2. project: fresh install -> --update twice -> --doctor, same assertions
#      (the workflow agents and skill, no siblings, no backups);
#   3. _lock_key_kind: a table of accepted and refused key shapes, extracted
#      from init.sh (one implementation, not a copy), newline keys included;
#   4. an out-of-pattern key with a newline, planted in the global lock, is
#      pruned by --update and no file is touched (the NUL-separated iteration
#      must not let it dodge pruning).

set -u

KIT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
INIT="$KIT_DIR/init.sh"
PASS=0
FAIL=0
TMP_ROOT="$(mktemp -d "${TMPDIR:-/tmp}/dwk-smoke.XXXXXX")"
trap 'rm -rf "$TMP_ROOT"' EXIT

ok()   { PASS=$((PASS + 1)); echo "  ok    $1"; }
bad()  { FAIL=$((FAIL + 1)); echo "  FAIL  $1" >&2; }
check() { # check DESCRIPTION COMMAND... : run the command, pass when it succeeds
  local desc="$1"; shift
  if "$@" >"$TMP_ROOT/last.out" 2>&1; then ok "$desc"; else bad "$desc"; sed 's/^/        /' "$TMP_ROOT/last.out" | tail -5 >&2; fi
}

# assert_clean_tree ROOT LABEL : no sibling and no backup dir under ROOT.
assert_clean_tree() {
  local root="$1" label="$2" stray
  stray="$(find "$root" \( -name '*.dev-workflow-kit-new' -o -name '*.dev-workflow-kit-prev' -o -name 'dev-workflow-kit-backup' \) 2>/dev/null)"
  if [[ -z "$stray" ]]; then ok "$label: zero siblings, zero backups"; else bad "$label: stray files: $stray"; fi
}

echo "== 1. global roster (sandbox OPENCODE_CONFIG_DIR)"
G="$TMP_ROOT/config"
mkdir -p "$G"
export OPENCODE_CONFIG_DIR="$G"
check "global install" bash -c "'$INIT' --global </dev/null"
check "global --update (1)" bash -c "'$INIT' --update --global </dev/null"
check "global --update (2)" bash -c "'$INIT' --update --global </dev/null"
check "global --doctor clean" bash -c "'$INIT' --doctor --global </dev/null"
agents="$(ls "$G/agent" 2>/dev/null | grep -c '\.md$')"
if [[ "$agents" -eq "$(ls "$KIT_DIR/roster/global-agent" | grep -c '\.md$')" ]]; then
  ok "global: $agents agents installed (== kit roster)"
else
  bad "global: $agents agents installed, kit ships $(ls "$KIT_DIR/roster/global-agent" | grep -c '\.md$')"
fi
[[ -f "$G/.dev-workflow-kit-lock.json" ]] && ok "global: lock file present" || bad "global: lock file missing"
assert_clean_tree "$G" "global"
unset OPENCODE_CONFIG_DIR

echo "== 2. project install (fresh git repo)"
P="$TMP_ROOT/project"
mkdir -p "$P" && git -C "$P" init -q
check "project install" bash -c "'$INIT' --companions=off '$P' </dev/null"
check "project --update (1)" bash -c "'$INIT' --update '$P' </dev/null"
check "project --update (2)" bash -c "'$INIT' --update '$P' </dev/null"
check "project --doctor clean" bash -c "'$INIT' --doctor '$P' </dev/null"
[[ -f "$P/.opencode/.dev-workflow-kit-lock.json" ]] && ok "project: lock file present" || bad "project: lock file missing"
assert_clean_tree "$P" "project"

echo "== 3. _lock_key_kind table"
# Extract the function from init.sh so the table tests the real code.
FN="$TMP_ROOT/lock_key_kind.sh"
awk '/^_lock_key_kind\(\) \{/{p=1} p{print} p && /^\}/{exit}' "$INIT" > "$FN"
if [[ ! -s "$FN" ]]; then
  bad "could not extract _lock_key_kind from init.sh"
else
  # shellcheck disable=SC1090
  source "$FN"
  nl=$'\n'
  table=(
    "agent/cheap-code.md|agent"
    "agent/deep.md|agent"
    "skill/dev-workflow/SKILL.md|skill"
    "skill/pr-review/x/y.md|skill"
    "CONVENTIONS.md|rules"
    "RULES.go.md|rules"
    "agent/../x.md|none"
    "agent/a/b.md|none"
    "/etc/passwd|none"
    "agent/x.md${nl}|none"
    "agent/zz${nl}../../escape.md|none"
    "agent/ghost${nl}name.md|none"
    "skill/../../x|none"
    "agent/|none"
    "foo.md|none"
    "|none"
  )
  for row in "${table[@]}"; do
    key="${row%|*}"; want="${row##*|}"
    got="$(_lock_key_kind "$key")"
    label="$(printf '%s' "$key" | tr '\n' '~')"
    if [[ "$got" == "$want" ]]; then ok "kind '$label' -> $want"; else bad "kind '$label': want $want, got $got"; fi
  done
fi

echo "== 4. out-of-pattern newline key is pruned, no file touched"
N="$TMP_ROOT/config-nl"
mkdir -p "$N"
check "nl: install" bash -c "OPENCODE_CONFIG_DIR='$N' '$INIT' --global </dev/null"
jq --arg k $'agent/zz\n../../escape.md' '.files += {($k): {body_sha256: "x"}}' "$N/.dev-workflow-kit-lock.json" > "$TMP_ROOT/lock.new" \
  && mv "$TMP_ROOT/lock.new" "$N/.dev-workflow-kit-lock.json"
check "nl: planted key present before update" bash -c "jq -e '.files | has(\"agent/zz\n../../escape.md\")' '$N/.dev-workflow-kit-lock.json' >/dev/null"
tree_hash() { (cd "$N" && find . -type f -not -name '.dev-workflow-kit-lock.json' -not -path './dev-workflow-kit-backup/*' | sort | xargs cat | shasum | cut -d' ' -f1); }
before="$(tree_hash)"
check "nl: --update" bash -c "OPENCODE_CONFIG_DIR='$N' '$INIT' --update --global </dev/null"
check "nl: planted key pruned from lock" bash -c "! jq -e '.files | has(\"agent/zz\n../../escape.md\")' '$N/.dev-workflow-kit-lock.json' >/dev/null"
after="$(tree_hash)"
[[ "$before" == "$after" ]] && ok "nl: no agent file changed" || bad "nl: agent files changed"
# a prune legitimately archives the entry: expect lock-entries.jsonl, no siblings
if find "$N" -name "*.dev-workflow-kit-new" -o -name "*.dev-workflow-kit-prev" | grep -q .; then bad "nl: stray siblings"; else ok "nl: zero siblings"; fi
# the archive must hold the planted key itself, not just some entry
arch="$(find "$N" -name lock-entries.jsonl | head -1)"
if [[ -n "$arch" ]] && jq -e --arg k $'agent/zz
../../escape.md' 'select(.key == $k)' "$arch" >/dev/null 2>&1; then ok "nl: archive holds the planted key"; else bad "nl: archive lacks the planted key"; fi


echo "== 5. R1 global-mode scenarios (-prev overwrite, stale sibling, baseline refresh)"
R="$TMP_ROOT/config-r1"
mkdir -p "$R"
check "r1: install" bash -c "OPENCODE_CONFIG_DIR='$R' '$INIT' --global </dev/null"
# (a) diverged body: exactly one -prev kept, body = kit, prev holds the edit
echo "# local edit" >> "$R/agent/cheap-code.md"
check "r1: --update overwrites diverged body" bash -c "OPENCODE_CONFIG_DIR='$R' '$INIT' --update --global </dev/null"
n_prev="$(find "$R" -name "cheap-code.md.dev-workflow-kit-prev" | wc -l | tr -d " ")"
[[ "$n_prev" == 1 ]] && ok "r1: exactly one -prev kept" || bad "r1: -prev count is $n_prev (want 1)"
grep -q "# local edit" "$R/agent/cheap-code.md.dev-workflow-kit-prev" && ok "r1: -prev holds the local edit" || bad "r1: -prev lacks the local edit"
grep -q "# local edit" "$R/agent/cheap-code.md" && bad "r1: body still holds the local edit" || ok "r1: body no longer holds the local edit"
# (b) stale sibling: a parked -new whose body now equals the kit is removed
echo "stale" > "$R/agent/cheap-review.md.dev-workflow-kit-new"
check "r1: --update prunes stale sibling" bash -c "OPENCODE_CONFIG_DIR='$R' '$INIT' --update --global </dev/null"
[[ ! -e "$R/agent/cheap-review.md.dev-workflow-kit-new" ]] && ok "r1: stale -new sibling removed" || bad "r1: stale -new sibling survived"
# (c) baseline refresh: body equals kit, lock baseline is wrong -> counts as current, baseline fixed
L="$R/.dev-workflow-kit-lock.json"
jq '.files["agent/cheap-mech.md"].body_sha256 = "0"' "$L" > "$TMP_ROOT/l.json" && mv "$TMP_ROOT/l.json" "$L"
check "r1: --update (baseline stale)" bash -c "OPENCODE_CONFIG_DIR='$R' '$INIT' --update --global </dev/null"
base="$(jq -r '.files["agent/cheap-mech.md"].body_sha256' "$L")"
[[ "$base" != "0" ]] && ok "r1: stale baseline refreshed" || bad "r1: baseline still 0"


echo "== 6. usage component (global, opt-in)"
U1="$TMP_ROOT/config-usage-on"; U0="$TMP_ROOT/config-usage-off"
mkdir -p "$U1" "$U0"
check "usage: install default" bash -c "OPENCODE_CONFIG_DIR='$U1' '$INIT' --global </dev/null"
check "usage: install --no-usage" bash -c "OPENCODE_CONFIG_DIR='$U0' '$INIT' --global --no-usage </dev/null"
[[ "$(jq -c .usage_enabled "$U1/.dev-workflow-kit-lock.json")" == true ]] && ok "usage: default records true" || bad "usage: default not recorded as true"
[[ "$(jq -c .usage_enabled "$U0/.dev-workflow-kit-lock.json")" == false ]] && ok "usage: --no-usage records false" || bad "usage: --no-usage not recorded as false"
[[ -f "$U1/plugin/dwk-usage.js" && -f "$U1/command/dwk.md" && -f "$U1/dwk/stats.mjs" ]] && ok "usage: three files installed when on" || bad "usage: files missing when on"
[[ ! -e "$U0/plugin/dwk-usage.js" ]] && ok "usage: no files when off" || bad "usage: files present when off"
check "usage: --update --global --no-usage removes it" bash -c "OPENCODE_CONFIG_DIR='$U1' '$INIT' --update --global --no-usage </dev/null"
[[ ! -e "$U1/plugin/dwk-usage.js" && "$(jq -c .usage_enabled "$U1/.dev-workflow-kit-lock.json")" == false ]] && ok "usage: removed + recorded false" || bad "usage: removal not applied"
check "usage: doctor clean (usage off)" bash -c "OPENCODE_CONFIG_DIR='$U1' '$INIT' --doctor --global </dev/null"

# the stats script: prune and a render over a fixture JSONL
STATS="$KIT_DIR/dwk/stats.mjs"
F="$TMP_ROOT/usage"; mkdir -p "$F"
echo "{\"t\":\"msg\",\"ts\":\"$(date -u +%Y-%m-%dT%H:%M:%SZ)\",\"msg_id\":\"m1\",\"session\":\"s1\",\"agent\":\"build\",\"provider\":\"p\",\"model\":\"m\",\"tokens\":{\"in\":1,\"out\":1,\"reasoning\":0,\"cache_read\":0,\"cache_write\":0},\"cost\":0.5}" > "$F/$(date -u +%Y-%m).jsonl"
echo "{\"t\":\"msg\"}" > "$F/2024-01.jsonl"
check "usage: stats renders a fixture" bash -c "node '$STATS' month --data '$F' | grep -q '\$0.5000'"
check "usage: prune removes a 2024 file" bash -c "node '$STATS' --prune --data '$F' | grep -q 'pruned 2024-01' && test ! -e '$F/2024-01.jsonl'"

# recorder + stats labelling: a zero-spend turn writes no msg record (its session
# record is kept); a real cost never gets "est."; only the estimate path does.
RU="$TMP_ROOT/recorder"
mkdir -p "$RU"
printf '%s\n' '{"prices":{"p/priced":{"in":1,"out":1,"cache_read":0,"cache_write":0},"p/m0":{"in":null,"out":null}}}' > "$RU/prices.json"
cat > "$RU/feed.mjs" <<JS
import { DwkUsage } from "$KIT_DIR/plugin/dwk-usage.js";
const h = await DwkUsage();
const ev = (info) => h.event({ event: { type: "message.updated", properties: { info } } });
const base = { role: "assistant", sessionID: "ses_1", agent: "build", providerID: "p", time: { completed: Date.now() } };
const tk = (i, o) => ({ input: i, output: o, reasoning: 0, cache: { read: 0, write: 0 } });
await h.event({ event: { type: "session.created", properties: { info: { id: "ses_1", title: "t", directory: "/tmp/p" } } } });
await ev({ ...base, id: "zero", modelID: "m0", cost: 0, tokens: tk(0, 0) });
await ev({ ...base, id: "r1", modelID: "m0", cost: 0.5, tokens: tk(10, 5) });
await ev({ ...base, id: "r2", modelID: "m0", cost: 0.25, tokens: tk(10, 5) });
await ev({ ...base, id: "e1", modelID: "priced", cost: 0, tokens: tk(1000000, 0) });
JS
DWK_USAGE_DIR="$RU/usage" node "$RU/feed.mjs"
if cat "$RU"/usage/*.jsonl | grep -q '"msg_id":"zero"'; then bad "rec: zero-spend message was recorded"; else ok "rec: zero-spend message skipped"; fi
if cat "$RU"/usage/*.jsonl | grep -q '"t":"session"'; then ok "rec: session record kept"; else bad "rec: session record missing"; fi
STATS_OUT="$(node "$KIT_DIR/dwk/stats.mjs" --data "$RU/usage" --models "$RU/prices.json" --by model)"
if printf '%s\n' "$STATS_OUT" | grep '^p/m0 ' | grep -q 'est\.'; then bad "stats: real-cost group wrongly labelled est."; else ok "stats: real-cost group has no est."; fi
if printf '%s\n' "$STATS_OUT" | grep '^p/priced ' | grep -q 'est\. \$1\.0000'; then ok "stats: cost-0-with-price labelled est."; else bad "stats: estimate label missing"; fi

echo "smoke: $PASS passed, $FAIL failed"
[[ $FAIL -eq 0 ]]
