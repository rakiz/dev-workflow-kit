#!/usr/bin/env bash
# dev-workflow-kit — install into a target project, or update an existing
# install.
#
# Usage (flags may appear in any position):
#   1. Project mode, from the kit:     ./init.sh [--with-rules] [--update] /path/to/target-project
#   2. Project mode, from the project: /path/to/dev-workflow-kit/init.sh [--with-rules] [--update]
#   3. Global mode:                    ./init.sh [--update] --global
#
# Default (install) behavior:
#   - agent/*.md and skill/: copied if absent; if present and identical to
#     the kit, no-op; if different (local customization), NEVER overwritten
#     — warning and skip.
#   - Model defaults: the kit's models.json is the single source of truth.
#     For each freshly copied agent, init.sh writes its `model:` frontmatter
#     line from models.json (plus a `variant:` reasoning-effort line when
#     models.json defines one for that agent), then (if the opencode CLI is
#     available) checks the model is offered by its provider and proposes a
#     replacement menu otherwise. Warnings only — this step can never fail
#     the install. A replacement model picked through the menu never gets a
#     guessed variant: the step-A variant is left untouched.
#   - dev-workflow.json, TODO.md, SPEC.md, INPROGRESS.md, CHANGELOG.md,
#     CONVENTIONS.md: copied ONLY if they do not exist yet (never overwritten).
#     RULES.md: OPT-IN — copied with --with-rules, or via an interactive y/N
#     prompt when a TTY is available; otherwise skipped (copy
#     templates/RULES.md manually to opt in). CONVENTIONS.cpp.md stays
#     opt-in by manual copy only (no flag). CONVENTIONS.md and RULES.md get
#     a --update baseline (their `## Project rules` prefix hash) in the lock
#     file when copied fresh or still identical.
#   - .git/hooks/pre-commit: installed if absent; if a different hook
#     exists, it is kept and the kit installs itself as
#     pre-commit.dev-workflow-kit (merge by hand).
#   - Lock file: .opencode/.dev-workflow-kit-lock.json records, for each
#     kit-managed file, the kit content last synced (body hash) and the
#     model/variant last injected. Written on every successful sync; commit
#     it. --update (below) reads it to tell untouched files from customized
#     ones.
#
# --update behavior (synchronizes an already-initialized project):
#   - KIT-MANAGED files only: agent/*.md, skill/dev-workflow/SKILL.md, the
#     pre-commit hook, the model:/variant: frontmatter defaults injected
#     from models.json, and the three kit-authored rule/convention files
#     CONVENTIONS.md, RULES.md and CONVENTIONS.cpp.md (see below).
#   - Project-state files (dev-workflow.json, TODO.md, SPEC.md,
#     INPROGRESS.md, CHANGELOG.md) are NEVER touched by --update — not
#     created, not overwritten, not removed — whatever their state. They
#     are pure project-owned content with no kit default to converge
#     toward. --with-rules has no effect combined with --update (a warning
#     says so).
#   - The three rule/convention files follow the same lock-based "ours vs
#     theirs" contract as the agents — kept up to date while used
#     unmodified, frozen with a .dev-workflow-kit-new sibling the moment
#     they are edited — but are never CREATED by --update (an absent
#     RULES.md or CONVENTIONS.cpp.md stays absent). CONVENTIONS.md
#     and RULES.md are compared and replaced only above their
#     `## Project rules` heading (the kit-managed prefix); project-specific
#     rules appended below it are 100% the project's — never touched,
#     never even considered when deciding whether the kit part was
#     customized. CONVENTIONS.cpp.md is synced whole-file (no
#     user-append zone).
#   - A file whose body matches the lock's baseline (untouched since the
#     last sync) is auto-updated to the kit's current version; a locally
#     customized file is NEVER overwritten — the kit's current version is
#     parked next to it as <file>.dev-workflow-kit-new for a manual merge
#     (warning).
#   - Model/variant defaults: refreshed to models.json's current value only
#     when the file's model still equals the lock's recorded (kit-injected)
#     value; a hand-set model is kept as-is (neutral note, not a warning).
#     The `variant:` line follows the identical three-way rule — a hand-set
#     variant is kept and not baselined, even when the model itself is
#     refreshed.
#   - Never prompts: no TTY reads at all (the interactive availability menu
#     is install-time only) — CI-safe, exits 0 unless a hard precondition
#     fails (target not a git repo, never initialized, ...).
#
# --global behavior (session roster into the opencode config directory):
#   - Installs the kit's global roster (global/agent/*.md — the 17 session
#     agents, see MODELS.md for the full 4-tier grid) into
#     ${OPENCODE_CONFIG_DIR:-$HOME/.config/opencode}/agent/ — the opencode
#     user-level agent directory. NOTE: no `.opencode/` level here, unlike
#     project mode — the config directory's `agent/` subdirectory IS the
#     agent directory. OPENCODE_CONFIG_DIR overrides the config directory
#     (created if absent).
#   - Takes NO target positional argument (clean error if one is given) and
#     has NO git-repo requirement (a config directory is not one). Nothing
#     project-specific is touched: no skill, no pre-commit hook, no
#     templates, no rule/convention files.
#   - Models are injected from models.json's "global" section through the
#     same machinery as project mode (step-A injection, step-B availability
#     menu). Project lookups of models.json are untouched.
#   - Lock file: ${OPENCODE_CONFIG_DIR:-$HOME/.config/opencode}/.dev-workflow-kit-lock.json
#     — same schema as the project lock (rel keys "agent/<name>.md"), a
#     separate file, so the two scopes sync independently.
#   - Shadowing warning: an inline `agent` entry of the same name in the
#     config directory's opencode.json(c) shadows the kit-managed file
#     (inline config wins over agent files). The kit detects it (a
#     string-aware JSONC->jq pass) and warns insistently, but NEVER edits
#     the jsonc — removing the inline entries is the user's manual
#     migration step (README, "Global roster").
#   - Combinable with --update: the same lock-driven three-way sync as the
#     project agents, for the roster files only.

KIT_DIR="$(cd "$(dirname "$0")" && pwd)"

WITH_RULES=0
UPDATE=0
GLOBAL_MODE=0
positionals=()
for arg in "$@"; do
  case "$arg" in
    --with-rules) WITH_RULES=1 ;;
    --update) UPDATE=1 ;;
    --global) GLOBAL_MODE=1 ;;
    -*)
      echo "Usage: $0 [--with-rules] [--update] [--global] [/path/to/target-project]" >&2
      exit 1
      ;;
    *) positionals+=("$arg") ;;
  esac
done
if [[ ${#positionals[@]} -gt 1 ]]; then
  echo "Usage: $0 [--with-rules] [--update] [--global] [/path/to/target-project]" >&2
  exit 1
fi

# --global is exclusive with the project mode in a single run: it takes no
# target positional (its target is the opencode config directory).
if [[ $GLOBAL_MODE -eq 1 && ${#positionals[@]} -gt 0 ]]; then
  echo "init: --global installs the session roster into the opencode config directory and takes no target argument." >&2
  exit 1
fi

if [[ $GLOBAL_MODE -eq 1 ]]; then
  TARGET="${OPENCODE_CONFIG_DIR:-$HOME/.config/opencode}"
  mkdir -p "$TARGET" 2>/dev/null || { echo "init: cannot create the opencode config directory: '$TARGET'" >&2; exit 1; }
  TARGET="$(cd "$TARGET" 2>/dev/null && pwd)" || { echo "init: opencode config directory not accessible: '${OPENCODE_CONFIG_DIR:-$HOME/.config/opencode}'" >&2; exit 1; }
else
  TARGET="${positionals[0]:-$PWD}"
  TARGET="$(cd "$TARGET" 2>/dev/null && pwd)" || { echo "init: target directory not accessible: '${positionals[0]:-}'" >&2; exit 1; }
  # Project mode only: a config directory is not a git repo, and must not
  # be required to be one.
  if ! git -C "$TARGET" rev-parse --git-dir >/dev/null 2>&1; then
    echo "init: '$TARGET' is not a git repo (run 'git init' first)." >&2
    exit 1
  fi
fi

copied=()
skipped=()
warnings=()
fresh_agents=()
updated_body=()
updated_model=()
up_to_date=()
manual_merge=()
kept_model=()
# Agent source/destination and lock path per mode: in global mode the
# destination IS the opencode config directory (agents land directly in
# $TARGET/agent/, no .opencode/ level) and the lock file sits at its root;
# project mode keeps .opencode/agent/ and .opencode/.dev-workflow-kit-lock.json.
if [[ $GLOBAL_MODE -eq 1 ]]; then
  AGENT_SRC_DIR="$KIT_DIR/global/agent"
  AGENT_DST_DIR="$TARGET/agent"
  LOCK_FILE="$TARGET/.dev-workflow-kit-lock.json"
else
  AGENT_SRC_DIR="$KIT_DIR/agent"
  AGENT_DST_DIR="$TARGET/.opencode/agent"
  LOCK_FILE="$TARGET/.opencode/.dev-workflow-kit-lock.json"
fi

# --with-rules is project-mode-only; say so early rather than silently
# ignoring it in a global run.
if [[ $WITH_RULES -eq 1 && $GLOBAL_MODE -eq 1 ]]; then
  warnings+=("--with-rules has no effect with --global: the opencode config directory has no RULES.md")
elif [[ $WITH_RULES -eq 1 && $UPDATE -eq 1 ]]; then
  warnings+=("--with-rules has no effect with --update: a missing RULES.md is never created in update mode (an existing one is synced either way)")
fi

# _bodies_equal FILE_A FILE_B : compare two files ignoring their `model:`
# and `variant:` frontmatter lines — the shared normalization for every
# kit-vs-target comparison (copy_sync, lock recording, --update).
_bodies_equal() {
  diff <(grep -vE '^(model|variant):' "$1") <(grep -vE '^(model|variant):' "$2") >/dev/null 2>&1
}

# copy_sync SRC DST LABEL : copy if absent; if present and identical to the
# kit, no-op; if present and different, NEVER overwrite (a local
# customization would be destroyed) — warn and skip. The `model:` and
# `variant:` lines are ignored when comparing: init.sh injects them from
# models.json, so installed agents legitimately differ from the kit sources
# on those lines only.
copy_sync() {
  local src="$1" dst="$2" label="$3"
  if [[ -f "$dst" ]] && ! cmp -s "$src" "$dst"; then
    if _bodies_equal "$src" "$dst"; then
      skipped+=("$label (identical)")
    else
      warnings+=("$label differs from the kit version: local customization detected, not overwritten — delete the local file or compare it manually to take the kit update")
    fi
  elif [[ -f "$dst" ]]; then
    skipped+=("$label (identical)")
  else
    mkdir -p "$(dirname "$dst")"
    cp "$src" "$dst"
    copied+=("$label")
  fi
}

# copy_if_absent SRC DST LABEL : never touch an existing file (project-owned)
copy_if_absent() {
  local src="$1" dst="$2" label="$3"
  if [[ -f "$dst" ]]; then
    skipped+=("$label (already exists, kept)")
  else
    mkdir -p "$(dirname "$dst")"
    cp "$src" "$dst"
    copied+=("$label")
  fi
}

# _upsert_fm_key FILE KEY VALUE [AFTER_KEY] : replace the `KEY:` frontmatter
# line, or insert one after the `AFTER_KEY:` line if given (when AFTER_KEY is
# absent, after the opening `---`). Re-running is safe: an existing key is
# replaced, never duplicated.
_upsert_fm_key() {
  local file="$1" key="$2" value="$3" after="${4:-}" tmp
  tmp="$(mktemp)" || return 1
  if grep -q "^${key}:" "$file"; then
    awk -v k="$key:" -v line="$key: $value" '!d && index($0, k) == 1 { print line; d=1; next } { print }' "$file" > "$tmp" || { rm -f "$tmp"; return 1; }
  elif [[ -n "$after" ]] && grep -q "^${after}:" "$file"; then
    awk -v a="$after:" -v line="$key: $value" '!d && index($0, a) == 1 { print; print line; d=1; next } { print }' "$file" > "$tmp" || { rm -f "$tmp"; return 1; }
  else
    awk -v line="$key: $value" '!d && /^---[[:space:]]*$/ { print; print line; d=1; next } { print }' "$file" > "$tmp" || { rm -f "$tmp"; return 1; }
  fi
  mv "$tmp" "$file"
}

# set_agent_model FILE MODEL [VARIANT] : upsert the `model:` frontmatter
# line, then — only when VARIANT is non-empty — upsert a `variant:` line
# right after it (reasoning effort, for models that support it). An empty
# VARIANT never touches any existing `variant:` line: a replacement model
# picked by the user gets no guessed effort.
set_agent_model() {
  local file="$1" model="$2" variant="${3:-}"
  _upsert_fm_key "$file" "model" "$model" || return 1
  if [[ -n "$variant" ]]; then
    _upsert_fm_key "$file" "variant" "$variant" "model" || return 1
  fi
}

# _body_hash FILE : sha256 of the file's content with its `model:`/`variant:`
# frontmatter lines stripped — the same normalization _bodies_equal applies.
# This is the "body" unit every lock baseline and --update comparison uses.
_body_hash() {
  grep -vE '^(model|variant):' "$1" 2>/dev/null | shasum -a 256 | awk '{print $1}'
}

# _fm_value FILE KEY : value of the file's `KEY: value` frontmatter line,
# empty when the key is absent.
_fm_value() {
  sed -n "s/^$2:[[:space:]]*//p" "$1" 2>/dev/null | tail -n 1
}

# _raw_hash FILE : sha256 of the file's raw bytes — the comparison unit for
# the rule/convention files (no `model:`/`variant:` frontmatter to strip,
# so no _body_hash-style normalization).
_raw_hash() {
  shasum -a 256 "$1" 2>/dev/null | awk '{print $1}'
}

# _RULES_MARKER : the heading closing the kit-managed prefix of
# CONVENTIONS.md / RULES.md — everything up to and including it is
# kit-authored, everything below it is the project's own appended rules.
_RULES_MARKER='^## Project rules[[:space:]]*$'

# _rules_prefix_hash FILE : sha256 of FILE's kit-managed prefix — everything
# up to and including the first `## Project rules` heading line — raw bytes,
# no normalization (these templates carry no model:/variant: lines). Empty
# output when the file has no marker line.
_rules_prefix_hash() {
  local n
  n="$(grep -n -m1 -E "$_RULES_MARKER" "$1" 2>/dev/null | cut -d: -f1)"
  [[ -n "$n" ]] || return 0
  head -n "$n" "$1" | shasum -a 256 | awk '{print $1}'
}

# models_json AGENT FIELD : value from the kit's models.json ("" if absent).
# Project mode reads the flat top-level map (role -> {model, ...}); global
# mode (--global) reads the same fields under the "global" section (the
# session roster). Project lookups are untouched by --global.
models_json() {
  local section="."
  [[ $GLOBAL_MODE -eq 1 ]] && section=".global"
  jq -r --arg a "$1" --arg f "$2" "${section}[\$a][\$f] // \"\"" "$KIT_DIR/models.json" 2>/dev/null || true
}

# _jsonc_strip_comments FILE : best-effort JSONC -> JSON on stdout. A
# character-level, string-aware scan that strips `//` line comments, `/* */`
# block comments (multi-line included) and trailing commas before a closing
# `}` or `]` (across newlines too) — the constructs a hand-edited jsonc
# accumulates. A `//` or `/*` inside a JSON string like "https://..." is
# preserved. Still best effort: the shadowing check below only needs a
# parse good enough for real-world jsonc, and jq failures there are caught
# and reported.
_jsonc_strip_comments() {
  awk '
  function flush() { if (pending) { out = out "," pws; pending = 0; pws = "" } }
  BEGIN { in_str = 0; in_block = 0; pending = 0; pws = ""; out = "" }
  {
    if (NR > 1) { if (pending) pws = pws "\n"; else out = out "\n" }
    line = $0
    i = 1
    n = length(line)
    while (i <= n) {
      c = substr(line, i, 1)
      if (in_block) {
        if (substr(line, i, 2) == "*/") { in_block = 0; i += 2 } else i++
        continue
      }
      if (in_str) {
        out = out c
        if (c == "\\") { out = out substr(line, i + 1, 1); i += 2; continue }
        if (c == "\"") in_str = 0
        i++
        continue
      }
      two = substr(line, i, 2)
      if (two == "//") break
      if (two == "/*") { in_block = 1; i += 2; continue }
      if (c == "\"") { flush(); in_str = 1; out = out c; i++; continue }
      if (c == ",") { if (!pending) { pending = 1; pws = "" }; i++; continue }
      if (c == " " || c == "\t" || c == "\r") { if (pending) pws = pws c; else out = out c; i++; continue }
      if (c == "}" || c == "]") { pending = 0; pws = ""; out = out c; i++; continue }
      flush()
      out = out c
      i++
    }
  }
  END { flush(); printf "%s", out }' "$1"
}

# warn_shadowed_agents : global-mode-only check — an inline `agent` entry in
# the config directory's opencode.json(c) shadows the kit-managed agent file
# of the same name (inline config wins over agent files), so the roster
# would silently keep running from the jsonc instead of the kit. Detection
# only: the jsonc is the user's file and is never modified by the kit —
# removing the inline entries is the user's manual migration step.
warn_shadowed_agents() {
  local cfg json src name inline_names
  local names=()
  for src in "$AGENT_SRC_DIR"/*.md; do
    [[ -f "$src" ]] || continue
    names+=("$(basename "$src" .md)")
  done
  [[ ${#names[@]} -gt 0 ]] || return 0
  for cfg in "$TARGET/opencode.jsonc" "$TARGET/opencode.json"; do
    [[ -f "$cfg" ]] || continue
    json="$(_jsonc_strip_comments "$cfg")"
    if ! inline_names="$(jq -r '(.agent // {} | keys[]?)' <<<"$json" 2>/dev/null)"; then
      warnings+=("could not parse $cfg — the inline-agent shadowing check was skipped for it, compare it by hand")
      continue
    fi
    while IFS= read -r name; do
      [[ -n "$name" ]] || continue
      [[ " ${names[*]} " == *" $name "* ]] || continue
      warnings+=("$cfg defines an inline 'agent.$name' entry that SHADOWS the kit-managed agent/$name.md just installed — inline config wins over agent files, so '$name' keeps running from the jsonc, not from the kit. Remove that entry from $cfg to finish the migration (the kit never edits the file itself)")
    done <<<"$inline_names"
  done
}

# --- Lock file ---------------------------------------------------------------
# .opencode/.dev-workflow-kit-lock.json records, for each kit-managed file,
# what the kit last synced into the target. Written by BOTH plain install and
# --update; read by --update. Shape (jq dynamic-key upserts — one level of
# nesting per file, no flat-key gymnastics needed):
#   { "version": 1,
#     "files": {
#       "agent/impl.md": { "body_sha256": "<kit source body hash at sync
#                           time, model:/variant: lines stripped>",
#                          "model": "<model last injected>", "variant": "..." },
#       "skill/dev-workflow/SKILL.md": { "body_sha256": "..." },
#       "CONVENTIONS.md": { "body_sha256": "<kit prefix hash: everything up
#                           to and including the `## Project rules` line>" },
#       "RULES.md": { "body_sha256": "<same prefix-hash rule>" },
#       "CONVENTIONS.cpp.md": { "body_sha256": "<whole-file sha256>" } } }
# body_sha256 = hash of the KIT'S SOURCE content that was last synced (not
# of the target): _body_hash (model:/variant: lines stripped) for agents and
# the skill, raw prefix/file bytes for the three rule/convention files.
# The pre-commit hook has NO entry: sync_hook detects its drift by comparing
# the files directly, so a recorded hash would be dead metadata nothing
# reads. model/variant = what the kit last injected for that agent (recorded
# "" when none; "" is also what a missing entry reads as, which is exactly
# the conservative bootstrap signal for --update: a missing lock, a missing
# entry or a recorded-empty model all mean "cannot prove the user untouched
# it — never overwrite, record the current state as the new baseline"). A
# file preserved as a local customization gets NO body/model update in its
# entry: it was never synced to the current kit content, so there is nothing
# new to baseline.
LOCK_OK=0
LOCK_WARNED=""

# lock_init : make sure the lock file exists and is valid before any lock
# write. Soft-fails (warning + return 1): both modes degrade to conservative
# behavior without a usable lock, they never fail because of it (--update's
# hard jq/shasum precondition is checked separately, before lock_init runs).
lock_init() {
  local tmp
  if [[ -f "$LOCK_FILE" ]]; then
    if jq -e 'type == "object" and (.files | type == "object")' "$LOCK_FILE" >/dev/null 2>&1; then
      LOCK_OK=1
      return 0
    fi
    warnings+=("lock file ${LOCK_FILE#$TARGET/} is not valid JSON — left untouched, no sync baselines recorded (--update will run in conservative bootstrap mode)")
    return 1
  fi
  tmp="$(mktemp)" || { warnings+=("could not create a temp file for the lock file"); return 1; }
  if printf '{ "version": 1, "files": {} }\n' > "$tmp" && mkdir -p "$(dirname "$LOCK_FILE")" && mv "$tmp" "$LOCK_FILE"; then
    LOCK_OK=1
    return 0
  fi
  rm -f "$tmp"
  warnings+=("could not write the lock file ${LOCK_FILE#$TARGET/} — no sync baselines recorded (--update will run in conservative bootstrap mode)")
  return 1
}

# lock_get REL FIELD : value from the lock file, "" when absent (a missing
# lock/entry is the bootstrap signal, never an error).
lock_get() {
  [[ -f "$LOCK_FILE" ]] || return 0
  jq -r --arg f "$1" --arg k "$2" '.files[$f][$k] // ""' "$LOCK_FILE" 2>/dev/null || true
}

# lock_has_model REL : true when REL's entry actually carries a "model" key —
# distinguishes "kit recorded that it injected no model" (key present, empty)
# from "no record at all" (key absent = --update bootstrap signal).
lock_has_model() {
  [[ -f "$LOCK_FILE" ]] || return 1
  jq -e --arg f "$1" '.files[$f] | type == "object" and has("model")' "$LOCK_FILE" >/dev/null 2>&1
}

# lock_set REL FIELD VALUE : upsert one field of REL's entry. No-op unless
# lock_init succeeded (LOCK_OK=1); a jq failure warns once and keeps going —
# lock problems must never fail the install or the update.
lock_set() {
  [[ $LOCK_OK -eq 1 ]] || return 0
  local tmp
  tmp="$(mktemp)" || { [[ -n "$LOCK_WARNED" ]] || { warnings+=("could not create a temp file for the lock file"); LOCK_WARNED=1; }; return 1; }
  if jq --arg f "$1" --arg k "$2" --arg v "$3" '.files[$f][$k] = $v' "$LOCK_FILE" > "$tmp" 2>/dev/null && mv "$tmp" "$LOCK_FILE"; then
    return 0
  fi
  rm -f "$tmp"
  [[ -n "$LOCK_WARNED" ]] || { warnings+=("could not update the lock file ${LOCK_FILE#$TARGET/} — sync baselines may be missing (--update will run conservatively)"); LOCK_WARNED=1; }
  return 1
}

# lock_record_if_synced SRC DST REL HAS_MODEL : install-mode baseline
# recording — when the target's body matches the kit's (freshly copied or
# still identical), record the kit's body hash and the target's current
# model/variant as the lock baseline (model/variant fields only for agents,
# HAS_MODEL=1). Diverged targets get no entry: nothing was synced.
#
# The model/variant record is deliberately guarded: it happens ONLY when the
# kit injected them this run (agent freshly copied, i.e. in fresh_agents —
# the injected default IS the new baseline) or when the lock carries no
# model entry for the agent yet (bootstrap of a pre-lock install — the same
# conservative philosophy as --update's bootstrap: baseline the current
# state). A body-matching agent that already has a lock entry keeps its
# recorded model/variant untouched: the target's current value may be a
# hand-set customization, and recording it would disguise it as the
# kit-injected default — a later --update would then wrongly treat it as
# refreshable and clobber it back to models.json's default.
lock_record_if_synced() {
  local src="$1" dst="$2" rel="$3" has_model="$4" m v name
  [[ -f "$dst" ]] && _bodies_equal "$src" "$dst" || return 0
  lock_set "$rel" body_sha256 "$(_body_hash "$src")"
  [[ $has_model -eq 1 ]] || return 0
  name="${rel#agent/}"; name="${name%.md}"
  if [[ " ${fresh_agents[*]} " != *" $name "* ]] && lock_has_model "$rel"; then
    return 0
  fi
  m="$(_fm_value "$dst" model)"
  v="$(_fm_value "$dst" variant)"
  lock_set "$rel" model "$m"
  lock_set "$rel" variant "$v"
}

# lock_record_rules_if_synced REL : install-mode baseline for one of the
# three rule/convention files (CONVENTIONS.md, RULES.md — CONVENTIONS.
# cpp.md is never copied by install so it never gets one here).
# Records the kit's comparison-unit hash — the `## Project rules` prefix
# hash for marker-bearing files, the whole-file raw hash otherwise — when
# the target's own unit matches the kit's (freshly copied above, or still
# identical). A diverged target gets no entry: nothing was synced.
lock_record_rules_if_synced() {
  local rel="$1" src="$KIT_DIR/templates/$1" dst="$TARGET/$1" kit_hash
  [[ -f "$src" && -f "$dst" ]] || return 0
  if grep -q -E "$_RULES_MARKER" "$src" && grep -q -E "$_RULES_MARKER" "$dst"; then
    kit_hash="$(_rules_prefix_hash "$src")"
    [[ "$(_rules_prefix_hash "$dst")" == "$kit_hash" ]] || return 0
  else
    kit_hash="$(_raw_hash "$src")"
    [[ "$(_raw_hash "$dst")" == "$kit_hash" ]] || return 0
  fi
  lock_set "$rel" body_sha256 "$kit_hash"
}

# sync_hook : pre-commit hook install/sync — shared by install and --update.
# The alt-file mechanism has its own drift detection via file comparison and
# is deliberately NOT lock-tracked (no hooks/pre-commit.sh lock entry: it
# would be dead metadata nothing reads). Fills the shared report arrays.
sync_hook() {
  HOOKS_DIR="$(git -C "$TARGET" rev-parse --git-path hooks)"
  [[ "$HOOKS_DIR" = /* ]] || HOOKS_DIR="$TARGET/$HOOKS_DIR"
  HOOK_DST="$HOOKS_DIR/pre-commit"
  HOOK_SRC="$KIT_DIR/hooks/pre-commit.sh"

  if [[ ! -e "$HOOK_DST" ]]; then
    mkdir -p "$HOOKS_DIR"
    cp "$HOOK_SRC" "$HOOK_DST" && chmod +x "$HOOK_DST"
    copied+=("$(git -C "$TARGET" rev-parse --git-dir)/hooks/pre-commit")
  elif cmp -s "$HOOK_SRC" "$HOOK_DST"; then
    if [[ $UPDATE -eq 1 ]]; then
      up_to_date+=("$(git -C "$TARGET" rev-parse --git-dir)/hooks/pre-commit")
    else
      skipped+=("$(git -C "$TARGET" rev-parse --git-dir)/hooks/pre-commit (identical)")
    fi
  else
    HOOK_ALT="$HOOKS_DIR/pre-commit.dev-workflow-kit"
    if [[ -e "$HOOK_ALT" ]]; then
      warnings+=("a different pre-commit hook exists AND ${HOOK_ALT#$TARGET/} also exists — manual merge required, nothing copied; the kit's hook is NOT active until the merge is done")
    else
      cp "$HOOK_SRC" "$HOOK_ALT" && chmod +x "$HOOK_ALT"
      warnings+=("existing pre-commit hook kept; kit's hook installed as ${HOOK_ALT#$TARGET/} — Git does NOT execute this file (only .git/hooks/pre-commit is executed): the kit's hook stays INACTIVE until you merge the two by hand")
    fi
  fi
}

# --- --update mode -----------------------------------------------------------
# Lock-driven sync of the kit-managed files into an already-initialized
# project. Never touches project-state files, never prompts (no TTY reads),
# CI-safe. See the header comment for the full contract.

# update_agent_model DST REL AGENT : --update model/variant handling for an
# EXISTING agent file (fresh copies inject the default directly). Per agent,
# independent of the body outcome:
#   - no recorded model in the lock (bootstrap: pre---update-era install) →
#     cannot tell a user choice from a kit injection: record the file's
#     CURRENT model/variant as the baseline, touch nothing;
#   - file's model == lock's recorded model (the kit injected it, the user
#     left it) → refresh to models.json's current default (and variant) when
#     they changed;
#   - file's model != lock's record → the user chose it (menu or by hand):
#     kept as-is, neutral note. The lock is NOT updated, so the choice keeps
#     being detected as the user's on later runs (updating the lock would let
#     a future models.json change clobber it).
# The `variant:` line follows the exact same three-way logic, independently:
# a variant is user-customized when it differs from the lock's recorded
# (kit-injected) value — kept as-is and NOT baselined, and never overwritten
# by a refresh (not even when the model itself is refreshed).
update_agent_model() {
  local dst="$1" rel="$2" agent="$3"
  local target_model target_variant lock_model kit_model kit_variant lock_variant
  target_model="$(_fm_value "$dst" model)"
  target_variant="$(_fm_value "$dst" variant)"
  if ! lock_has_model "$rel"; then
    # Bootstrap: no recorded model (pre---update-era install) — cannot tell a
    # user choice from a kit injection, so treat the current value as
    # user-set and just baseline it for future runs.
    lock_set "$rel" model "$target_model"
    lock_set "$rel" variant "$target_variant"
    return
  fi
  lock_model="$(lock_get "$rel" model)"
  if [[ "$target_model" != "$lock_model" ]]; then
    kept_model+=("$rel (model '${target_model:-<none>}' kept — differs from the last kit-injected default: user-configured)")
    return
  fi
  [[ $MODELS_OK -eq 1 ]] || return
  kit_model="$(models_json "$agent" model)"
  kit_variant="$(models_json "$agent" variant)"
  if [[ -z "$kit_model" ]]; then
    return
  fi
  # Three-way state of the variant — the same test the model applies against
  # its own lock field: differing from the lock's recorded value means the
  # user set it, so it is kept and not baselined.
  lock_variant="$(lock_get "$rel" variant)"
  local variant_kept=0
  [[ "$target_variant" != "$lock_variant" ]] && variant_kept=1
  if [[ "$kit_model" != "$target_model" ]]; then
    # Kit changed the model, the user kept the kit-injected one: refresh the
    # model. The variant only rides along when the user hasn't customized it
    # (an empty VARIANT argument leaves any existing `variant:` line alone —
    # same rule as set_agent_model); a customized variant is not baselined.
    local inject_variant="$kit_variant"
    [[ $variant_kept -eq 1 ]] && inject_variant=""
    if set_agent_model "$dst" "$kit_model" "$inject_variant"; then
      updated_model+=("$rel (model: $kit_model${inject_variant:+, variant: $inject_variant})")
      lock_set "$rel" model "$kit_model"
      [[ $variant_kept -eq 1 ]] || lock_set "$rel" variant "$kit_variant"
    else
      warnings+=("could not update the model of $rel")
    fi
    return
  fi
  # Model already equals models.json's default: refresh the variant alone,
  # with the identical three-way condition — the kit's variant changed AND
  # the user hasn't customized the file's. An emptied kit variant leaves any
  # existing `variant:` line in place (same rule as set_agent_model) and
  # only moves the lock baseline.
  if [[ $variant_kept -eq 1 ]]; then
    return
  fi
  if [[ "$kit_variant" != "$lock_variant" ]]; then
    if set_agent_model "$dst" "$kit_model" "$kit_variant"; then
      lock_set "$rel" variant "$kit_variant"
      [[ -n "$kit_variant" ]] && updated_model+=("$rel (variant: $kit_variant)")
    else
      warnings+=("could not update the variant of $rel")
    fi
  fi
}

# _park_sibling SRC SIBLING REL REASON : park the kit's current version next
# to a file that must not be auto-overwritten (local customization or
# conservative bootstrap) — write/refresh the sibling only when its content
# actually changed, and report under "Needs manual merge".
_park_sibling() {
  local src="$1" sibling="$2" rel="$3" reason="$4"
  if [[ ! -f "$sibling" ]]; then
    cp "$src" "$sibling" || warnings+=("could not write ${sibling#$TARGET/}")
    manual_merge+=("$rel $reason — new kit version available at ${sibling#$TARGET/} for manual merge; not applied automatically")
  elif ! cmp -s "$src" "$sibling"; then
    cp "$src" "$sibling"
    manual_merge+=("$rel $reason — new kit version saved to ${sibling#$TARGET/} (previous sibling was stale); not applied automatically")
  else
    manual_merge+=("$rel $reason — new kit version already at ${sibling#$TARGET/} for manual merge; not applied automatically")
  fi
}

# update_body_3way SRC DST REL HASH_CMD : the lock-driven three-way body
# decision shared by --update for an EXISTING target file — untouched since
# the last sync → adopt the kit's current content; customized → frozen
# (sibling parked); no baseline → conservative bootstrap. HASH_CMD names the
# hash function defining the comparison unit (_body_hash for agent files,
# _raw_hash for the rule/convention files). It reports through two globals
# the callers use for their own reporting:
#   BODY_UPDATED=1  the body was replaced with the kit's current content
#   BODY_CURRENT=1  the body was already current, nothing was written
update_body_3way() {
  local src="$1" dst="$2" rel="$3" hash_cmd="$4"
  local kit_hash target_hash lock_hash sibling
  kit_hash="$("$hash_cmd" "$src")"
  target_hash="$("$hash_cmd" "$dst")"
  lock_hash="$(lock_get "$rel" body_sha256)"
  sibling="$dst.dev-workflow-kit-new"
  BODY_UPDATED=0
  BODY_CURRENT=0

  if [[ -n "$lock_hash" ]]; then
    if [[ "$target_hash" == "$lock_hash" && "$kit_hash" == "$target_hash" ]]; then
      # Body untouched since the last sync AND the kit hasn't changed either.
      BODY_CURRENT=1
    elif [[ "$target_hash" == "$lock_hash" ]]; then
      # Body untouched since the last sync, kit changed: safe to adopt the
      # kit's current content. The caller restores the file's own
      # model:/variant: frontmatter after the copy (the kit source carries
      # none); the model refresh may then upsert the new default over it.
      if ! cp "$src" "$dst"; then
        warnings+=("could not update $rel")
        return
      fi
      BODY_UPDATED=1
      lock_set "$rel" body_sha256 "$kit_hash"
    else
      # Body differs from the lock baseline: locally customized since the
      # last sync — never overwritten, no baseline update (still diverged,
      # nothing new to record).
      _park_sibling "$src" "$sibling" "$rel" "was locally customized"
    fi
  else
    # Bootstrap: no recorded baseline (pre---update-era install).
    # Conservative: a body already matching the kit is baselined; a diverged
    # body is left alone with a .dev-workflow-kit-new sibling — never
    # silently clobbered.
    if [[ "$target_hash" == "$kit_hash" ]]; then
      BODY_CURRENT=1
      lock_set "$rel" body_sha256 "$kit_hash"
    else
      _park_sibling "$src" "$sibling" "$rel" "differs from the kit version and no lock baseline exists (install from before --update) — assumed customized"
    fi
  fi
}

# update_sync_managed SRC DST REL HAS_MODEL AGENT : one kit-managed file
# under --update. Body first (update_body_3way), then — for agents — the
# model/variant refresh. Never overwrites a customized body, never prompts.
update_sync_managed() {
  local src="$1" dst="$2" rel="$3" has_model="$4" agent="$5"

  if [[ ! -f "$dst" ]]; then
    # New kit file since the project's last install: plain copy + baseline
    # (+ default model injection, no availability menu — --update never
    # prompts).
    mkdir -p "$(dirname "$dst")"
    if ! cp "$src" "$dst"; then
      warnings+=("could not copy $rel")
      return
    fi
    copied+=("$rel (new in kit)")
    lock_set "$rel" body_sha256 "$(_body_hash "$src")"
    if [[ $has_model -eq 1 && $MODELS_OK -eq 1 ]]; then
      local km kv
      km="$(models_json "$agent" model)"
      kv="$(models_json "$agent" variant)"
      if [[ -n "$km" ]]; then
        if set_agent_model "$dst" "$km" "$kv"; then
          lock_set "$rel" model "$km"
          lock_set "$rel" variant "$kv"
        else
          warnings+=("could not write model into $rel")
        fi
      else
        warnings+=("no model configured in models.json for agent '$agent'")
      fi
    fi
    return
  fi

  # The kit copy wipes the injected frontmatter, so snapshot it first to
  # restore it right after the body update (the model refresh below may
  # then upsert the new default over it).
  local prev_model="" prev_variant=""
  if [[ $has_model -eq 1 ]]; then
    prev_model="$(_fm_value "$dst" model)"
    prev_variant="$(_fm_value "$dst" variant)"
  fi

  update_body_3way "$src" "$dst" "$rel" _body_hash

  if [[ $BODY_UPDATED -eq 1 ]]; then
    updated_body+=("$rel")
    if [[ $has_model -eq 1 && -n "$prev_model" ]] && ! set_agent_model "$dst" "$prev_model" "$prev_variant"; then
      warnings+=("could not restore the model line of $rel after the body update")
    fi
  fi

  # Model/variant default refresh — independent of the body outcome above.
  local n_model_before=${#updated_model[@]}
  if [[ $has_model -eq 1 ]]; then
    update_agent_model "$dst" "$rel" "$agent"
  fi
  # A body-current file lands under "Up to date" only when no model/variant
  # refresh happened for it — a refreshed file is reported under
  # "Updated (model)" and must not also appear here.
  if [[ $BODY_CURRENT -eq 1 && ${#updated_model[@]} -eq $n_model_before ]]; then
    up_to_date+=("$rel")
  fi
}

# --- Rule/convention files under --update ------------------------------------
# CONVENTIONS.md, RULES.md and CONVENTIONS.cpp.md are kit-authored and
# follow the same "ours vs theirs" contract as the agents: kept up to date
# while used unmodified, frozen the moment they are customized. Two
# differences: --update never CREATES them (a declined RULES.md or a never
# manually-copied CONVENTIONS.cpp.md stays absent), and
# CONVENTIONS.md / RULES.md split at their `## Project rules` heading — the
# kit-managed prefix is everything up to and including that heading line,
# the project's own appended rules below it are never touched, never even
# considered when deciding whether the kit part was customized.

# update_convention_split SRC DST REL : `## Project rules`-split sync for
# CONVENTIONS.md / RULES.md. Both files must carry the marker (the caller
# checks): the kit-managed prefix (up to and including the marker line) is
# compared and replaced as a unit, the target's suffix below it is preserved
# byte-for-byte. No model:/variant: frontmatter here — the prefix's raw
# bytes are hashed directly. The lock records the prefix hash only; a
# customized kit part or a missing baseline records nothing (a file is never
# baselined as "matching" content it doesn't).
update_convention_split() {
  local src="$1" dst="$2" rel="$3"
  local kit_hash target_hash lock_hash sibling n_src n_dst tmp
  kit_hash="$(_rules_prefix_hash "$src")"
  target_hash="$(_rules_prefix_hash "$dst")"
  lock_hash="$(lock_get "$rel" body_sha256)"
  sibling="$dst.dev-workflow-kit-new"

  if [[ -n "$lock_hash" ]]; then
    if [[ "$target_hash" == "$lock_hash" && "$kit_hash" == "$target_hash" ]]; then
      # Kit part untouched since the last sync AND the kit hasn't changed:
      # nothing to do (the user's suffix is theirs, never considered).
      up_to_date+=("$rel")
    elif [[ "$target_hash" == "$lock_hash" ]]; then
      # Kit part changed, the user's prefix untouched: replace the prefix
      # with the kit's current one, preserve the suffix byte-for-byte.
      n_src="$(grep -n -m1 -E "$_RULES_MARKER" "$src" | cut -d: -f1)"
      n_dst="$(grep -n -m1 -E "$_RULES_MARKER" "$dst" | cut -d: -f1)"
      tmp="$(mktemp)" || { warnings+=("could not create a temp file to update $rel"); return; }
      if { head -n "$n_src" "$src"; tail -n "+$((n_dst + 1))" "$dst"; } > "$tmp" \
          && cp "$tmp" "$dst"; then
        rm -f "$tmp"
        updated_body+=("$rel")
        lock_set "$rel" body_sha256 "$kit_hash"
      else
        rm -f "$tmp"
        warnings+=("could not update $rel")
      fi
    else
      # The kit-authored part above the marker was edited since the last
      # sync: the file is the project's now — frozen, sibling offered.
      _park_sibling "$src" "$sibling" "$rel" "was locally customized in its kit-authored part (above '## Project rules')"
    fi
  else
    # Bootstrap (no lock entry): conservative — a target whose kit prefix
    # already matches is just baselined; a diverged one is never overwritten
    # and records nothing (it stays flagged as needing attention rather than
    # being baselined as "matching" something it doesn't).
    if [[ "$target_hash" == "$kit_hash" ]]; then
      up_to_date+=("$rel")
      lock_set "$rel" body_sha256 "$kit_hash"
    else
      _park_sibling "$src" "$sibling" "$rel" "differs from the kit version in its kit-authored part (above '## Project rules') and no lock baseline exists (install from before --update) — assumed customized"
    fi
  fi
}

# update_convention_whole SRC DST REL : whole-file sync for
# CONVENTIONS.cpp.md (100% kit-authored, no user-append zone — its
# closing note tells the adopting project to merge it into its own
# CONVENTIONS.md instead) and for a CONVENTIONS.md / RULES.md without a
# `## Project rules` marker (no reliable split point — the whole file is the
# comparison unit). Same three-way logic as the agents' body sync.
update_convention_whole() {
  local src="$1" dst="$2" rel="$3"
  update_body_3way "$src" "$dst" "$rel" _raw_hash
  [[ $BODY_UPDATED -eq 1 ]] && updated_body+=("$rel")
  [[ $BODY_CURRENT -eq 1 ]] && up_to_date+=("$rel")
}

# update_rules_conventions : the --update step for the three kit-authored
# rule/convention files — run after the agent/skill/hook sync, before the
# summary. Only files ALREADY present in the target are synced: --update
# never creates any of them.
update_rules_conventions() {
  local rel src dst
  for rel in CONVENTIONS.md RULES.md CONVENTIONS.cpp.md; do
    src="$KIT_DIR/templates/$rel"
    dst="$TARGET/$rel"
    [[ -f "$dst" && -f "$src" ]] || continue
    if grep -q -E "$_RULES_MARKER" "$src" && grep -q -E "$_RULES_MARKER" "$dst"; then
      update_convention_split "$src" "$dst" "$rel"
    else
      # No reliable split point (old install without the marker, a
      # user-deleted marker, or a kit source missing it): whole-file logic.
      update_convention_whole "$src" "$dst" "$rel"
    fi
  done
}

if [[ $UPDATE -eq 1 ]]; then
  if [[ ! -d "$AGENT_DST_DIR" ]]; then
    if [[ $GLOBAL_MODE -eq 1 ]]; then
      echo "init: --update --global: '$TARGET' has no agent/ directory — run './init.sh --global' first." >&2
    else
      echo "init: --update: '$TARGET' was never initialized with dev-workflow-kit (.opencode/agent/ missing) — run plain init.sh first." >&2
    fi
    exit 1
  fi
  if ! command -v jq >/dev/null 2>&1 || ! command -v shasum >/dev/null 2>&1; then
    echo "init: --update requires jq and shasum (lock-file mechanism)." >&2
    exit 1
  fi
  lock_init || true
  MODELS_OK=1
  [[ -f "$KIT_DIR/models.json" ]] || { MODELS_OK=0; warnings+=("kit models.json not found — model/variant defaults not refreshed"); }

  shopt -s nullglob
  for src in "$AGENT_SRC_DIR"/*.md; do
    name="$(basename "$src" .md)"
    update_sync_managed "$src" "$AGENT_DST_DIR/$(basename "$src")" "agent/$(basename "$src")" 1 "$name"
  done
  shopt -u nullglob
  if [[ $GLOBAL_MODE -eq 1 ]]; then
    # Roster agents only — the config directory has no skill/hook/rules.
    warn_shadowed_agents
  else
    update_sync_managed "$KIT_DIR/skill/dev-workflow/SKILL.md" "$TARGET/.opencode/skill/dev-workflow/SKILL.md" "skill/dev-workflow/SKILL.md" 0 ""
    sync_hook
    # No lock baseline for the hook: sync_hook detects its drift by comparing
    # the files directly, so a recorded hash would be dead metadata.

    # Kit-authored rule/convention files — same "ours vs theirs" sync as the
    # agents, for files that already exist in the target (never created).
    update_rules_conventions
  fi

  echo ""
  echo "=== dev-workflow-kit: update summary for $TARGET ==="
  if [[ ${#updated_body[@]} -gt 0 ]]; then
    echo "Updated (body):"
    printf '  + %s\n' "${updated_body[@]}"
  fi
  if [[ ${#updated_model[@]} -gt 0 ]]; then
    echo "Updated (model):"
    printf '  ~ %s\n' "${updated_model[@]}"
  fi
  if [[ ${#copied[@]} -gt 0 ]]; then
    echo "Installed (new):"
    printf '  + %s\n' "${copied[@]}"
  fi
  if [[ ${#up_to_date[@]} -gt 0 ]]; then
    echo "Up to date:"
    printf '  = %s\n' "${up_to_date[@]}"
  fi
  if [[ ${#kept_model[@]} -gt 0 ]]; then
    echo "Kept (user-configured model):"
    printf '  = %s\n' "${kept_model[@]}"
  fi
  if [[ ${#manual_merge[@]} -gt 0 ]]; then
    echo "Needs manual merge (customization preserved):"
    printf '  ! %s\n' "${manual_merge[@]}"
  fi
  if [[ ${#warnings[@]} -gt 0 ]]; then
    echo "WARNING:"
    printf '  ! %s\n' "${warnings[@]}"
  fi
  if [[ $GLOBAL_MODE -eq 1 ]]; then
    echo "Done. Global roster synced into $TARGET (lock: ${LOCK_FILE#$TARGET/})."
  else
    echo "Done. Project-state files (dev-workflow.json, TODO.md, SPEC.md, INPROGRESS.md, CHANGELOG.md) are never touched by --update. Commit ${LOCK_FILE#$TARGET/} so updates stay deterministic across machines and CI."
  fi
  exit 0
fi

# Agents: synced — project pipeline agents into .opencode/agent/ (project
# mode), or the session roster into the config directory (global mode).
shopt -s nullglob
for src in "$AGENT_SRC_DIR"/*.md; do
  name="$(basename "$src" .md)"
  dst="$AGENT_DST_DIR/$(basename "$src")"
  existed=0; [[ -f "$dst" ]] && existed=1
  copy_sync "$src" "$dst" "agent/$(basename "$src")"
  if [[ $existed -eq 0 && -f "$dst" ]]; then
    fresh_agents+=("$name")
  fi
done
shopt -u nullglob
if [[ $GLOBAL_MODE -eq 0 ]]; then
  copy_sync "$KIT_DIR/skill/dev-workflow/SKILL.md" "$TARGET/.opencode/skill/dev-workflow/SKILL.md" "skill/dev-workflow/SKILL.md"

  # Hook pre-commit (shared with --update; see sync_hook)
  sync_hook

  # Templates + project config: only if absent
  copy_if_absent "$KIT_DIR/templates/dev-workflow.json" "$TARGET/dev-workflow.json" "dev-workflow.json"
  for t in TODO.md SPEC.md INPROGRESS.md CHANGELOG.md CONVENTIONS.md; do
    copy_if_absent "$KIT_DIR/templates/$t" "$TARGET/$t" "$t"
  done

  # RULES.md is opt-in (with a flag/prompt, unlike CONVENTIONS.cpp.md
  # which stays manual-copy-only): --with-rules forces it on; with a TTY an
  # interactive y/N prompt asks (default No); otherwise (CI, piped stdin) it is
  # skipped with a warning. Same copy_if_absent semantics as the other
  # templates: never overwrite.
  if [[ $WITH_RULES -eq 1 ]]; then
    copy_if_absent "$KIT_DIR/templates/RULES.md" "$TARGET/RULES.md" "RULES.md"
  elif [[ -t 0 ]]; then
    read -r -p "Include RULES.md — Power-of-10-inspired safety rules with a justified-deviation protocol? [y/N] " ans
    case "$ans" in
      y|Y|yes|Yes|YES) copy_if_absent "$KIT_DIR/templates/RULES.md" "$TARGET/RULES.md" "RULES.md" ;;
    esac
  else
    warnings+=("RULES.md not installed (no TTY to ask, --with-rules not passed) — pass --with-rules or copy templates/RULES.md manually to opt in")
  fi
fi

# Model defaults + availability check — freshly copied agents only (agents
# kept because of a local customization are the project's property, untouched).
# Every error in this section is a warning; it can never fail the install.
#
# Two decoupled steps:
#   Step A (always, needs only jq + models.json): inject each agent's default
#   model from models.json into the freshly copied file.
#   Step B (only if the opencode CLI is on PATH AND stdin is a TTY): check the
#   injected model is offered by its provider and propose a replacement menu
#   otherwise.
if [[ ${#fresh_agents[@]} -gt 0 ]]; then
  if ! command -v jq >/dev/null 2>&1 || [[ ! -f "$KIT_DIR/models.json" ]]; then
    warnings+=("jq or kit models.json unavailable, skipping model injection and availability check for: ${fresh_agents[*]}")
  else
    if ! command -v opencode >/dev/null 2>&1; then
      warnings+=("opencode CLI not found, skipping model availability check — model defaults from models.json were installed as-is")
    fi
    for agent in "${fresh_agents[@]}"; do
      model="$(models_json "$agent" model)"
      hint="$(models_json "$agent" family_hint)"
      variant="$(models_json "$agent" variant)"
      if [[ -z "$model" ]]; then
        warnings+=("no model configured in models.json for agent '$agent', agent left without injected model")
        continue
      fi
      # Step A: inject the default model (and variant, when one is
      # configured for this agent) — independent of opencode's presence.
      if ! set_agent_model "$AGENT_DST_DIR/$agent.md" "$model" "$variant"; then
        warnings+=("could not write model into agent '$agent'")
        continue
      fi
      # Step B: availability check + replacement menu.
      if ! command -v opencode >/dev/null 2>&1; then
        continue
      fi
      provider="${model%%/*}"
      if ! list="$(opencode models "$provider" 2>/dev/null)"; then
        warnings+=("could not list models for provider '$provider' (agent '$agent') — model '$model' left as configured; see MODELS.md for the role to preserve when picking a replacement")
        continue
      fi
      if grep -qxF "$model" <<<"$list"; then
        echo "  = agent '$agent': model available ($model)"
        continue
      fi
      candidates=()
      while IFS= read -r c; do
        [[ -n "$c" ]] && candidates+=("$c")
      done < <(grep -i -- "$hint" <<<"$list" 2>/dev/null)
      if [[ ${#candidates[@]} -eq 0 ]]; then
        warnings+=("model '$model' for agent '$agent' is not available and no '$hint' alternative found at provider '$provider' — left as configured, fix it manually; see MODELS.md to pick a consistent replacement")
        continue
      fi
      if [[ ! -t 0 ]]; then
        warnings+=("agent '$agent': default model may not be available and no interactive TTY to choose a replacement — check MODELS.md and adjust manually if needed")
        continue
      fi
      echo "Model '$model' configured for agent '$agent' is not available. Choose a replacement:"
      echo "(no reasoning-effort 'variant' is guessed for a replacement model — the variant injected from models.json is left as-is; double check it manually, a different model may use a different effort scale)"
      PS3="Enter choice: "
      select choice in "${candidates[@]}" "keep as configured (may fail at runtime)" "enter a different model manually"; do
        if [[ -z "$choice" ]]; then
          echo "Invalid choice." >&2
          continue
        fi
        case "$choice" in
          "keep as configured (may fail at runtime)")
            # Normalize: never let the menu label leak into the file — an
            # empty choice means "keep the injected models.json default".
            choice=""
            ;;
          "enter a different model manually")
            read -r -p "Model id: " manual
            if [[ -n "$manual" ]]; then choice="$manual"; else choice=""; fi
            ;;
        esac
        break
      done
      if [[ -n "$choice" ]]; then
        if set_agent_model "$AGENT_DST_DIR/$agent.md" "$choice"; then
          echo "  ~ agent '$agent': model replaced with '$choice'"
        else
          warnings+=("could not write chosen model into agent '$agent'")
        fi
      fi
    done
  fi
fi

# Shadowing check (global mode only): an inline `agent` entry in the config
# directory's opencode.json(c) masks the kit-managed files.
if [[ $GLOBAL_MODE -eq 1 ]]; then
  warn_shadowed_agents
fi

# Lock file: record the sync baseline for every kit-managed file whose target
# body matches the kit (freshly copied or still identical) — the reference
# point a future --update compares against. Soft-requires jq + shasum (the
# same tools --update hard-requires); without them, degrade with a warning:
# the next --update will simply bootstrap conservatively. Files preserved as
# local customizations get no entry (nothing was synced), and the hook gets
# no entry either (sync_hook detects its drift by file comparison).
if command -v jq >/dev/null 2>&1 && command -v shasum >/dev/null 2>&1; then
  if lock_init; then
    shopt -s nullglob
    for src in "$AGENT_SRC_DIR"/*.md; do
      lock_record_if_synced "$src" "$AGENT_DST_DIR/$(basename "$src")" "agent/$(basename "$src")" 1
    done
    shopt -u nullglob
    if [[ $GLOBAL_MODE -eq 0 ]]; then
      lock_record_if_synced "$KIT_DIR/skill/dev-workflow/SKILL.md" "$TARGET/.opencode/skill/dev-workflow/SKILL.md" "skill/dev-workflow/SKILL.md" 0
      # CONVENTIONS.md and RULES.md: baseline the kit-managed prefix (the
      # `## Project rules` split) when the freshly copied (or still identical)
      # file matches the kit. CONVENTIONS.cpp.md is never copied by
      # install, so it only ever gets a baseline from a later --update bootstrap.
      lock_record_rules_if_synced "CONVENTIONS.md"
      lock_record_rules_if_synced "RULES.md"
    fi
  fi
else
  warnings+=("jq or shasum unavailable — the lock file was not written; a future --update will bootstrap conservatively")
fi

echo ""
if [[ $GLOBAL_MODE -eq 1 ]]; then
  echo "=== dev-workflow-kit: global roster installed into $TARGET ==="
else
  echo "=== dev-workflow-kit: installed into $TARGET ==="
fi
if [[ ${#copied[@]} -gt 0 ]]; then
  echo "Copied:"
  printf '  + %s\n' "${copied[@]}"
fi
if [[ ${#skipped[@]} -gt 0 ]]; then
  echo "Kept (not overwritten):"
  printf '  = %s\n' "${skipped[@]}"
fi
if [[ ${#warnings[@]} -gt 0 ]]; then
  echo "WARNING:"
  printf '  ! %s\n' "${warnings[@]}"
fi
if [[ $GLOBAL_MODE -eq 1 ]]; then
  echo "Done. Roster agents live in $TARGET/agent/ — if your opencode.json(c) still defines these agents inline, remove those entries (they shadow the kit-managed files; see README.md, Global roster)."
else
  echo "Done. Customize dev-workflow.json (e.g. test cmd) to enable the checks."
fi
