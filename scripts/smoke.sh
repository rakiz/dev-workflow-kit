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

echo ""
echo "smoke: $PASS passed, $FAIL failed"
[[ $FAIL -eq 0 ]]
