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
#      must not let it dodge pruning);
#   5-6. the R1 baseline scenarios and the usage component (global, opt-in);
#   7. the pre-commit hook baseline (hook/pre-commit): recorded by a plain
#      install, a kit-owned hook is overwritten by --update, also from a kit
#      copy without .git; a previous kit version's hook (no baseline) is
#      upgraded through git history when the kit checkout has it;
#   8. a user's own pre-commit hook is never overwritten: --update parks the
#      kit's hook as pre-commit.dev-workflow-kit;
#   9. a lock key whose path runs through a symlinked directory is refused:
#      the key is pruned, the file outside the project is left untouched;
#  10. the /dwk placeholder rewrite keeps `|`, `&` and `\` in paths literal;
#  11. a symlinked .opencode refuses the whole install (non-zero, nothing
#      written outside); a symlinked CONVENTIONS.md reports no stale verdict.

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
check "global install" "$INIT" --global </dev/null
check "global --update (1)" "$INIT" --update --global </dev/null
check "global --update (2)" "$INIT" --update --global </dev/null
check "global --doctor clean" "$INIT" --doctor --global </dev/null
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
check "project install" "$INIT" --companions=off "$P" </dev/null
check "project --update (1)" "$INIT" --update "$P" </dev/null
check "project --update (2)" "$INIT" --update "$P" </dev/null
check "project --doctor clean" "$INIT" --doctor "$P" </dev/null
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
    "hook/pre-commit|hook"
    "hook/pre-commit.sh|none"
    "hook/../x|none"
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
check "nl: install" env OPENCODE_CONFIG_DIR="$N" "$INIT" --global </dev/null
jq --arg k $'agent/zz\n../../escape.md' '.files += {($k): {body_sha256: "x"}}' "$N/.dev-workflow-kit-lock.json" > "$TMP_ROOT/lock.new" \
  && mv "$TMP_ROOT/lock.new" "$N/.dev-workflow-kit-lock.json"
check "nl: planted key present before update" bash -c "jq -e '.files | has(\"agent/zz\n../../escape.md\")' '$N/.dev-workflow-kit-lock.json' >/dev/null"
tree_hash() { (cd "$N" && find . -type f -not -name '.dev-workflow-kit-lock.json' -not -path './dev-workflow-kit-backup/*' | sort | xargs cat | shasum | cut -d' ' -f1); }
before="$(tree_hash)"
check "nl: --update" env OPENCODE_CONFIG_DIR="$N" "$INIT" --update --global </dev/null
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
check "r1: install" env OPENCODE_CONFIG_DIR="$R" "$INIT" --global </dev/null
# (a) diverged body: exactly one -prev kept, body = kit, prev holds the edit
echo "# local edit" >> "$R/agent/cheap-code.md"
check "r1: --update overwrites diverged body" env OPENCODE_CONFIG_DIR="$R" "$INIT" --update --global </dev/null
n_prev="$(find "$R" -name "cheap-code.md.dev-workflow-kit-prev" | wc -l | tr -d " ")"
[[ "$n_prev" == 1 ]] && ok "r1: exactly one -prev kept" || bad "r1: -prev count is $n_prev (want 1)"
grep -q "# local edit" "$R/agent/cheap-code.md.dev-workflow-kit-prev" && ok "r1: -prev holds the local edit" || bad "r1: -prev lacks the local edit"
grep -q "# local edit" "$R/agent/cheap-code.md" && bad "r1: body still holds the local edit" || ok "r1: body no longer holds the local edit"
# (b) stale sibling: a parked -new whose body now equals the kit is removed
echo "stale" > "$R/agent/cheap-review.md.dev-workflow-kit-new"
check "r1: --update prunes stale sibling" env OPENCODE_CONFIG_DIR="$R" "$INIT" --update --global </dev/null
[[ ! -e "$R/agent/cheap-review.md.dev-workflow-kit-new" ]] && ok "r1: stale -new sibling removed" || bad "r1: stale -new sibling survived"
# (c) baseline refresh: body equals kit, lock baseline is wrong -> counts as current, baseline fixed
L="$R/.dev-workflow-kit-lock.json"
jq '.files["agent/cheap-mech.md"].body_sha256 = "0"' "$L" > "$TMP_ROOT/l.json" && mv "$TMP_ROOT/l.json" "$L"
check "r1: --update (baseline stale)" env OPENCODE_CONFIG_DIR="$R" "$INIT" --update --global </dev/null
base="$(jq -r '.files["agent/cheap-mech.md"].body_sha256' "$L")"
[[ "$base" != "0" ]] && ok "r1: stale baseline refreshed" || bad "r1: baseline still 0"


echo "== 6. usage component (global, opt-in)"
U1="$TMP_ROOT/config-usage-on"; U0="$TMP_ROOT/config-usage-off"
mkdir -p "$U1" "$U0"
check "usage: install default" env OPENCODE_CONFIG_DIR="$U1" "$INIT" --global </dev/null
check "usage: install --no-usage" env OPENCODE_CONFIG_DIR="$U0" "$INIT" --global --no-usage </dev/null
[[ "$(jq -c .usage_enabled "$U1/.dev-workflow-kit-lock.json")" == true ]] && ok "usage: default records true" || bad "usage: default not recorded as true"
[[ "$(jq -c .usage_enabled "$U0/.dev-workflow-kit-lock.json")" == false ]] && ok "usage: --no-usage records false" || bad "usage: --no-usage not recorded as false"
[[ -f "$U1/plugin/dwk-usage.js" && -f "$U1/command/dwk.md" && -f "$U1/dwk/stats.mjs" ]] && ok "usage: three files installed when on" || bad "usage: files missing when on"
[[ ! -e "$U0/plugin/dwk-usage.js" ]] && ok "usage: no files when off" || bad "usage: files present when off"
check "usage: --update --global --no-usage removes it" env OPENCODE_CONFIG_DIR="$U1" "$INIT" --update --global --no-usage </dev/null
[[ ! -e "$U1/plugin/dwk-usage.js" && "$(jq -c .usage_enabled "$U1/.dev-workflow-kit-lock.json")" == false ]] && ok "usage: removed + recorded false" || bad "usage: removal not applied"
check "usage: doctor clean (usage off)" env OPENCODE_CONFIG_DIR="$U1" "$INIT" --doctor --global </dev/null

# the stats script: prune and a render over a fixture JSONL
STATS="$KIT_DIR/dwk/stats.mjs"
F="$TMP_ROOT/usage"; mkdir -p "$F"
echo "{\"t\":\"msg\",\"ts\":\"$(date -u +%Y-%m-%dT%H:%M:%SZ)\",\"msg_id\":\"m1\",\"session\":\"s1\",\"agent\":\"build\",\"provider\":\"p\",\"model\":\"m\",\"tokens\":{\"in\":1,\"out\":1,\"reasoning\":0,\"cache_read\":0,\"cache_write\":0},\"cost\":0.5}" > "$F/$(date -u +%Y-%m).jsonl"
echo "{\"t\":\"msg\"}" > "$F/2024-01.jsonl"
check "usage: stats renders a fixture" bash -c "node '$STATS' month --data '$F' | grep -q '\$0.5000'"
check "usage: prune removes a 2024 file" bash -c "node '$STATS' --prune --data '$F' | grep -q 'pruned 2024-01' && test ! -e '$F/2024-01.jsonl'"
check "usage: context telemetry selftest" node "$KIT_DIR/dwk/usage-selftest.mjs"

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


echo "== 7. pre-commit hook baseline (M1)"
# 7a: a plain install records the baseline; a kit-owned hook (deployed bytes ==
# baseline, older than the kit) is overwritten by --update.
A="$TMP_ROOT/project-hook-baseline"
mkdir -p "$A" && git -C "$A" init -q
LA="$A/.opencode/.dev-workflow-kit-lock.json"
check "baseline: install" "$INIT" --companions=off "$A" </dev/null
KH="$(shasum -a 256 "$KIT_DIR/workflow/hooks/pre-commit.sh" | awk '{print $1}')"
[[ "$(jq -r '.files["hook/pre-commit"].body_sha256 // ""' "$LA")" == "$KH" ]] \
  && ok "baseline: fresh install records the kit hook hash" || bad "baseline: no hook baseline after a fresh install"
printf '# hook of an older kit\n' >> "$A/.git/hooks/pre-commit"
DH="$(shasum -a 256 "$A/.git/hooks/pre-commit" | awk '{print $1}')"
jq --arg h "$DH" '.files["hook/pre-commit"].body_sha256 = $h' "$LA" > "$TMP_ROOT/la.json" && mv "$TMP_ROOT/la.json" "$LA"
check "baseline: --update" "$INIT" --update "$A" </dev/null
if cmp -s "$KIT_DIR/workflow/hooks/pre-commit.sh" "$A/.git/hooks/pre-commit"; then ok "baseline: kit-owned hook overwritten"; else bad "baseline: kit-owned hook NOT overwritten"; fi
[[ -e "$A/.git/hooks/pre-commit.dev-workflow-kit" ]] && bad "baseline: a sibling was parked" || ok "baseline: no sibling parked"

# 7b: a kit copy WITHOUT .git records the baseline too, and overwrites the same way.
GK="$TMP_ROOT/kit-nogit"; mkdir -p "$GK"
if tar -C "$KIT_DIR" --exclude=.git -cf - . | tar -C "$GK" -xf -; then ok "gitless kit: copy without .git"; else bad "gitless kit: copy failed"; fi
[[ -e "$GK/.git" ]] && bad "gitless kit: .git still present" || ok "gitless kit: no .git"
G2="$TMP_ROOT/project-gitless"
mkdir -p "$G2" && git -C "$G2" init -q
check "gitless kit: install" "$GK/init.sh" --companions=off "$G2" </dev/null
LG="$G2/.opencode/.dev-workflow-kit-lock.json"
GKH="$(shasum -a 256 "$GK/workflow/hooks/pre-commit.sh" | awk '{print $1}')"
[[ "$(jq -r '.files["hook/pre-commit"].body_sha256 // ""' "$LG")" == "$GKH" ]] \
  && ok "gitless kit: install records the baseline" || bad "gitless kit: no baseline after install"
printf '# hook of an older kit\n' >> "$G2/.git/hooks/pre-commit"
DH="$(shasum -a 256 "$G2/.git/hooks/pre-commit" | awk '{print $1}')"
jq --arg h "$DH" '.files["hook/pre-commit"].body_sha256 = $h' "$LG" > "$TMP_ROOT/lg.json" && mv "$TMP_ROOT/lg.json" "$LG"
check "gitless kit: --update" "$GK/init.sh" --update "$G2" </dev/null
if cmp -s "$GK/workflow/hooks/pre-commit.sh" "$G2/.git/hooks/pre-commit"; then ok "gitless kit: kit-owned hook overwritten"; else bad "gitless kit: kit-owned hook NOT overwritten"; fi

# 7c: legacy hook (no baseline) matched through git history. Needs the kit
# checkout's history; skipped (not failed) on a kit copy without it.
H="$TMP_ROOT/project-legacy-hook"
KPFX="$(git -C "$KIT_DIR" rev-parse --show-prefix 2>/dev/null)"
if git -C "$KIT_DIR" cat-file -e "b0dc12d:${KPFX}workflow/hooks/pre-commit.sh" 2>/dev/null; then
  mkdir -p "$H" && git -C "$H" init -q
  check "legacy hook: install" "$INIT" --companions=off "$H" </dev/null
  LH="$H/.opencode/.dev-workflow-kit-lock.json"
  jq 'del(.files["hook/pre-commit"])' "$LH" > "$TMP_ROOT/lh.json" && mv "$TMP_ROOT/lh.json" "$LH"
  # b0dc12d: the oldest kit commit that carried workflow/hooks/pre-commit.sh
  # (108 commits back). Its bytes stand in for a hook a previous kit deployed.
  if git -C "$KIT_DIR" show "b0dc12d:${KPFX}workflow/hooks/pre-commit.sh" > "$H/.git/hooks/pre-commit"; then ok "legacy hook: old kit hook deployed (b0dc12d)"; else bad "legacy hook: could not read b0dc12d"; fi
  if cmp -s "$KIT_DIR/workflow/hooks/pre-commit.sh" "$H/.git/hooks/pre-commit"; then
    bad "legacy hook: setup did not differ from the kit hook"
  else
    ok "legacy hook: setup differs from the kit hook"
  fi
  check "legacy hook: --update" "$INIT" --update "$H" </dev/null
  if cmp -s "$KIT_DIR/workflow/hooks/pre-commit.sh" "$H/.git/hooks/pre-commit"; then ok "legacy hook: deployed hook upgraded to the kit hook"; else bad "legacy hook: deployed hook NOT upgraded"; fi
  if [[ -n "$(jq -r '.files["hook/pre-commit"].body_sha256 // ""' "$LH")" ]]; then ok "legacy hook: lock baseline recorded"; else bad "legacy hook: lock baseline missing"; fi
  [[ -e "$H/.git/hooks/pre-commit.dev-workflow-kit" ]] && bad "legacy hook: a sibling was parked" || ok "legacy hook: no sibling parked"
  grep -q "upgraded from a previous kit version" "$TMP_ROOT/last.out" && ok "legacy hook: reported as an update" || bad "legacy hook: upgrade not reported"
else
  echo "  skip  legacy hook (git history): the kit checkout has no git history for b0dc12d"
fi

echo "== 7d. kit as a SUBDIRECTORY of another repo: legacy hook upgrade via history"
if git -C "$KIT_DIR" cat-file -e b0dc12d:workflow/hooks/pre-commit.sh 2>/dev/null; then
  # A synthetic outer repo whose history holds the hook under kit/ (the real
  # subdirectory layout): an old commit with the b0dc12d hook, then the current one.
  W="$TMP_ROOT/outer-repo"; SDIR="$W/kit"
  AUTH=(-c user.name=smoke -c user.email=smoke@example.invalid)
  mkdir -p "$SDIR/workflow/hooks" && git -C "$W" init -q
  git -C "$KIT_DIR" show b0dc12d:workflow/hooks/pre-commit.sh > "$SDIR/workflow/hooks/pre-commit.sh"
  git -C "$W" add kit && git -C "$W" "${AUTH[@]}" commit -qm "old kit hook"
  cp "$KIT_DIR/workflow/hooks/pre-commit.sh" "$SDIR/workflow/hooks/pre-commit.sh"
  git -C "$W" add kit && git -C "$W" "${AUTH[@]}" commit -qm "current kit hook"
  if tar -C "$KIT_DIR" --exclude=.git -cf - . | tar -C "$SDIR" -xf -; then ok "subdir kit: working tree copied in"; else bad "subdir kit: copy failed"; fi
  SD="$TMP_ROOT/project-subdir-kit"
  mkdir -p "$SD" && git -C "$SD" init -q
  check "subdir kit: install" "$SDIR/init.sh" --companions=off "$SD" </dev/null
  LSD="$SD/.opencode/.dev-workflow-kit-lock.json"
  jq 'del(.files["hook/pre-commit"])' "$LSD" > "$TMP_ROOT/lsd.json" && mv "$TMP_ROOT/lsd.json" "$LSD"
  git -C "$KIT_DIR" show b0dc12d:workflow/hooks/pre-commit.sh > "$SD/.git/hooks/pre-commit"
  check "subdir kit: --update" "$SDIR/init.sh" --update "$SD" </dev/null
  if cmp -s "$SDIR/workflow/hooks/pre-commit.sh" "$SD/.git/hooks/pre-commit"; then ok "subdir kit: legacy hook upgraded through the prefixed history"; else bad "subdir kit: legacy hook NOT upgraded (prefix lost?)"; fi
else
  echo "  skip  subdirectory kit (git history): the kit checkout has no git history for b0dc12d"
fi

echo "== 8. pre-commit hook: a user's own hook is never overwritten (M1)"
UH="$TMP_ROOT/project-user-hook"
mkdir -p "$UH" && git -C "$UH" init -q
check "user hook: install" "$INIT" --companions=off "$UH" </dev/null
jq 'del(.files["hook/pre-commit"])' "$UH/.opencode/.dev-workflow-kit-lock.json" > "$TMP_ROOT/uh.json" && mv "$TMP_ROOT/uh.json" "$UH/.opencode/.dev-workflow-kit-lock.json"
printf '#!/bin/sh\n# my own hook\nexit 0\n' > "$UH/.git/hooks/pre-commit"
chmod +x "$UH/.git/hooks/pre-commit"
check "user hook: --update" "$INIT" --update "$UH" </dev/null
grep -q "# my own hook" "$UH/.git/hooks/pre-commit" && ok "user hook: own hook kept" || bad "user hook: own hook overwritten"
[[ -f "$UH/.git/hooks/pre-commit.dev-workflow-kit" ]] && ok "user hook: kit hook parked as sibling" || bad "user hook: kit hook not parked"

echo "== 9. a key through a symlinked directory is refused, never followed (M2)"
S="$TMP_ROOT/project-symlink"
mkdir -p "$S" && git -C "$S" init -q
check "symlink: install" "$INIT" --companions=off "$S" </dev/null
OUT="$TMP_ROOT/outside"; mkdir -p "$OUT"; echo keep > "$OUT/.bashrc"
ln -s "$OUT" "$S/.opencode/skill/x"
SL="$S/.opencode/.dev-workflow-kit-lock.json"
jq '.files["skill/x/.bashrc"] = {body_sha256: "0"}' "$SL" > "$TMP_ROOT/sl.json" && mv "$TMP_ROOT/sl.json" "$SL"
check "symlink: --update" "$INIT" --update "$S" </dev/null
grep -q "path traverses a symlink" "$TMP_ROOT/last.out" && ok "symlink: refusal warning printed" || bad "symlink: no refusal warning"
[[ "$(<"$OUT/.bashrc")" == keep && "$(ls -A "$OUT")" == ".bashrc" ]] && ok "symlink: file outside the project untouched" || bad "symlink: outside file changed"
jq -e '.files | has("skill/x/.bashrc") | not' "$SL" >/dev/null && ok "symlink: planted key pruned" || bad "symlink: planted key survived"

echo "== 10. /dwk placeholder rewrite keeps | & \\ literal (m4)"
RF="$TMP_ROOT/render.sh"
extract_fn() { awk -v n="$1" 'index($0, n "() {") == 1 {p=1} p{print} p && /^}/{exit}' "$INIT"; }
extract_fn _sed_escape_repl > "$RF"; extract_fn _dwk_render >> "$RF"
DWK_TPL="$TMP_ROOT/dwk-template.md"
printf '%s\n' 'node "$DWK_STATS" --models "$DWK_MODELS"' > "$DWK_TPL"
FAKE_KIT='/tmp/fake|kit&x\y'
rendered="$(KIT_DIR="$FAKE_KIT" TARGET='/tmp/tgt|a&b' bash -c 'source "$1"; _dwk_render "$2"' _ "$RF" "$DWK_TPL")"
want="node \"/tmp/tgt|a&b/dwk/stats.mjs\" --models \"$FAKE_KIT/roster/models.json\""
if [[ "$rendered" == "$want" ]]; then ok "dwk: paths with | & \\ rendered literally"; else bad "dwk: got '$rendered', want '$want'"; fi

echo "== 11. symlinked .opencode refuses the install; CONVENTIONS symlink verdict"
OL="$TMP_ROOT/project-opencode-link"; OLOUT="$TMP_ROOT/outside-opencode"
mkdir -p "$OL" "$OLOUT" && git -C "$OL" init -q
ln -s "$OLOUT" "$OL/.opencode"
if "$INIT" --companions=off "$OL" </dev/null >"$TMP_ROOT/last.out" 2>&1; then
  bad "opencode link: install exited 0"
else
  ok "opencode link: install exits non-zero"
fi
grep -q "refusing to install/update" "$TMP_ROOT/last.out" && ok "opencode link: clear error printed" || bad "opencode link: no clear error"
[[ -z "$(ls -A "$OLOUT")" ]] && ok "opencode link: nothing written outside the project (no lock)" || bad "opencode link: files written outside"

CV="$TMP_ROOT/project-conv-link"; CVOUT="$TMP_ROOT/outside-conv.md"
mkdir -p "$CV" && git -C "$CV" init -q
check "conv link: install" "$INIT" --companions=off "$CV" </dev/null
echo keep > "$CVOUT"
rm -f "$CV/CONVENTIONS.md" && ln -s "$CVOUT" "$CV/CONVENTIONS.md"
"$INIT" --update "$CV" </dev/null >"$TMP_ROOT/last.out" 2>&1
grep -q "path traverses a symlink" "$TMP_ROOT/last.out" && ok "conv link: refusal warning printed" || bad "conv link: no refusal warning"
if grep -qxF '  = CONVENTIONS.md' "$TMP_ROOT/last.out"; then bad "conv link: stale up-to-date entry printed"; else ok "conv link: no stale up-to-date entry"; fi
[[ "$(<"$CVOUT")" == keep ]] && ok "conv link: outside file untouched" || bad "conv link: outside file changed"

HS="$TMP_ROOT/project-hooks-link"; HSOUT="$TMP_ROOT/outside-hooks"
mkdir -p "$HS" "$HSOUT" && git -C "$HS" init -q
check "hooks link: install" "$INIT" --companions=off "$HS" </dev/null
rm -rf "$HS/.git/hooks" && ln -s "$HSOUT" "$HS/.git/hooks"
"$INIT" --update "$HS" </dev/null >"$TMP_ROOT/last.out" 2>&1
grep -q "pre-commit hook: path traverses a symlink" "$TMP_ROOT/last.out" && ok "hooks link: refusal warning printed" || bad "hooks link: no refusal warning"
[[ -z "$(ls -A "$HSOUT")" ]] && ok "hooks link: nothing written through the symlinked hooks dir" || bad "hooks link: files written outside"

echo "smoke: $PASS passed, $FAIL failed"
[[ $FAIL -eq 0 ]]
