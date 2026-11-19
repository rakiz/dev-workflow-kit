#!/usr/bin/env bash
# dev-workflow-kit — pre-commit hook
# Requires: git + jq (no fallback without jq, see the kit's README).
# Config: dev-workflow.json at the repo root.
#   - Missing config   -> warning, commit accepted.
#   - Check with empty "cmd" and no "builtin" -> silently skipped.
# Builtins implemented here: companion_md_exists, no_history_comments (opt-in,
# not enabled by the shipped template — see the kit's README).

ROOT="$(git rev-parse --show-toplevel 2>/dev/null)"
if [[ -z "$ROOT" ]]; then
  echo "[dev-workflow-kit] not inside a git repo, hook ignored" >&2
  exit 0
fi

CONFIG="$ROOT/dev-workflow.json"
if [[ ! -f "$CONFIG" ]]; then
  echo "[dev-workflow-kit] no dev-workflow.json at the repo root — checks skipped (commit accepted)" >&2
  exit 0
fi

if ! command -v jq >/dev/null 2>&1; then
  echo "[dev-workflow-kit] 'jq' is required by this hook but not found — install it (e.g. brew install jq) or remove the hook. Commit blocked." >&2
  exit 1
fi

if ! jq empty "$CONFIG" >/dev/null 2>&1; then
  echo "[dev-workflow-kit] dev-workflow.json is invalid JSON — commit blocked." >&2
  exit 1
fi

# NB: '.enabled // true' would be wrong for enabled=false (jq // treats false as null)
COMPANIONS_ENABLED="$(jq -r '.companions.enabled? != false' "$CONFIG")"

failures=0
failed_names=""

record_failure() {
  failures=$((failures + 1))
  if [[ -n "$failed_names" ]]; then failed_names="$failed_names, $1"; else failed_names="$1"; fi
}

# Shared extension-filter helpers for the builtins.
# load_extensions: " ext1 ext2 " string from a check's "extensions" JSON array
# (spaces around each entry, so the membership test is *" $ext "*).
load_extensions() {
  local ext out=" "
  while IFS= read -r ext; do
    [[ -n "$ext" ]] && out="$out$ext "
  done < <(jq -r '.extensions // [] | .[]' <<<"$1")
  printf '%s' "$out"
}

# ext_allowed <exts> <file>: true if the file's basename extension is listed.
ext_allowed() {
  local base="${2##*/}" ext
  if [[ "$base" == *.* ]]; then ext="${base##*.}"; else return 1; fi
  [[ "$1" == *" $ext "* ]]
}

# Builtin companion_md_exists check: for each staged source file (excluding
# deletions) whose extension is listed in "extensions", the same-named .md
# (same folder) must be STAGED (present in the index). A companion present
# on disk but not staged counts as missing: the commit would not include it.
run_companion_check() {
  local check_json="$1"
  local exts companion printed=0 found file
  exts="$(load_extensions "$check_json")"

  # Set of staged files (same source as the loop below, without
  # --diff-filter: the companion may be a plain addition to the index).
  local -a staged_files=()
  while IFS= read -r -d '' file; do
    staged_files+=("$file")
  done < <(git -C "$ROOT" diff --cached --name-only -z)

  while IFS= read -r -d '' file; do
    ext_allowed "$exts" "$file" || continue
    companion="${file%.*}.md"
    found=0
    for f in "${staged_files[@]}"; do
      if [[ "$f" == "$companion" ]]; then found=1; break; fi
    done
    if [[ $found -eq 0 ]]; then
      if [[ $printed -eq 0 ]]; then
        echo "[dev-workflow-kit] .md companions missing from the commit:"
        printed=1
      fi
      if [[ -f "$ROOT/$companion" ]]; then
        echo "  - $file  ->  $companion  (on disk but not staged — consider: git add \"$companion\")"
      else
        echo "  - $file  ->  $companion  (missing)"
      fi
    fi
  done < <(git -C "$ROOT" diff --cached --name-only -z --diff-filter=d)
  [[ $printed -eq 0 ]]
}

# Builtin no_history_comments check: for each staged file (excluding
# deletions) whose extension is listed in "extensions", scan the ADDED lines
# only (git diff --cached -U0, '+' lines, '+++' header excluded) for markers
# narrating a comment's history rather than current intent. Heuristic on raw
# lines: comment syntax is NOT parsed, so any added line containing a marker
# matches (string literals, prose) — this is why the check is opt-in. Blocks
# like every other check (the hook has no warn-only mode).
run_no_history_comments() {
  local check_json="$1"
  local exts file marker hit lineno content
  exts="$(load_extensions "$check_json")"

  local -a markers=(
    "previously" "used to be" "changed from" "now does" "no longer"
    "old behavior" "old version" "before this change"
  )

  local -a hits=()
  while IFS= read -r -d '' file; do
    ext_allowed "$exts" "$file" || continue
    # Added lines with their new-file line number: each -U0 hunk header's
    # third field ("+12,3") gives the new side's start line; removed lines
    # ('-') do not advance it.
    local added
    added="$(git -C "$ROOT" diff --cached -U0 -- "$file" | awk '
      /^\+\+\+/ || /^---/ { next }
      /^@@ /              { split($3, r, ","); nl = substr(r[1], 2) + 0; next }
      /^\+/               { line = $0; sub(/^\+/, "", line); print nl "\t" line; nl++ }
    ')"
    [[ -z "$added" ]] && continue
    # -w (whole word): "unchanged from" must not match "changed from".
    for marker in "${markers[@]}"; do
      while IFS= read -r hit; do
        [[ -z "$hit" ]] && continue
        lineno="${hit%%$'\t'*}"
        content="${hit#*$'\t'}"
        hits+=("$file"$'\t'"$lineno"$'\t'"$marker"$'\t'"$content")
      done < <(grep -iwF -- "$marker" <<<"$added")
    done
  done < <(git -C "$ROOT" diff --cached --name-only -z --diff-filter=d)

  [[ ${#hits[@]} -eq 0 ]] && return 0
  # Report by file, then ascending line number (hits were collected per marker).
  echo "[dev-workflow-kit] history-narrating comments in ADDED lines (belongs in CHANGELOG.md, not in code):"
  local entry
  while IFS= read -r entry; do
    IFS=$'\t' read -r file lineno marker content <<<"$entry"
    echo "  - $file:$lineno  (matched: \"$marker\")  $content"
  done < <(printf '%s\n' "${hits[@]}" | sort -t$'\t' -k1,1 -k2,2n)
  return 1
}

# jq fails if .precommit is not an object or if .checks is neither an array
# nor absent (e.g. a string) — in that case we block, never silence it.
if ! CHECKS="$(jq -c '.precommit.checks // [] | .[]' "$CONFIG" 2>/dev/null)"; then
  echo "[dev-workflow-kit] dev-workflow.json: '.precommit.checks' is invalid (array of objects expected) — commit blocked." >&2
  exit 1
fi

while IFS= read -r check; do
  [[ -z "$check" ]] && continue
  name="$(jq -r '.name // "unnamed"' <<<"$check")"
  builtin="$(jq -r '.builtin // ""' <<<"$check")"
  cmd="$(jq -r '.cmd // ""' <<<"$check")"

  if [[ "$builtin" == "companion_md_exists" ]]; then
    if [[ "$COMPANIONS_ENABLED" != "true" ]]; then
      echo "[dev-workflow-kit] check '$name': companions.enabled=false, check skipped"
      continue
    fi
    if ! run_companion_check "$check"; then
      record_failure "$name"
    fi
  elif [[ "$builtin" == "no_history_comments" ]]; then
    if ! run_no_history_comments "$check"; then
      record_failure "$name"
    fi
  elif [[ -n "$cmd" ]]; then
    echo "[dev-workflow-kit] check '$name': running..."
    out="$(cd "$ROOT" && sh -c "$cmd" 2>&1)"
    status=$?
    if [[ $status -ne 0 ]]; then
      echo "[dev-workflow-kit] check '$name': FAILED (code $status)"
      [[ -n "$out" ]] && printf '%s\n' "$out"
      record_failure "$name"
    fi
  fi
  # empty cmd without builtin: silently skipped
done <<<"$CHECKS"

if [[ $failures -gt 0 ]]; then
  echo ""
  echo "[dev-workflow-kit] Commit blocked — $failures check(s) failed: $failed_names"
  exit 1
fi

echo "[dev-workflow-kit] All checks pass."
exit 0
