#!/usr/bin/env bash
# roster/build.sh — generate the roster artifacts derived from roster/models.json.
#
#   ./roster/build.sh           regenerate the committed artifacts in place
#   ./roster/build.sh --check   regenerate into a temp dir and compare with the
#                               committed files; exit 1 + a diff summary on drift
#
# Generated (committed, reviewable diffs):
#   roster/MODELS.md          the text between the markers
#                             <!-- BEGIN GENERATED: roster --> and
#                             <!-- END GENERATED: roster -->. Everything outside
#                             the markers is hand-written rationale and is never
#                             touched.
#   roster/injected-preview.md  per global agent: the model:/variant:/# Model
#                             family: lines init.sh injects at install time.
#   review rung prompts       the text between the markers
#                             <!-- BEGIN GENERATED: review-checklist --> and
#                             <!-- END GENERATED: review-checklist -->, spliced
#                             with roster/fragments/review-checklist.md. Listed
#                             in REVIEW_TARGETS below. The role-specific lines
#                             (escalation targets, intro, verdict) stay outside
#                             the markers and are hand-written.
#
# Single source: roster/models.json and roster/fragments/. Needs bash + jq
# (already required by init.sh). This script never writes outside the kit and
# never calls the network. init.sh --global refuses to deploy while --check fails.

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SRC_JSON="$ROOT/roster/models.json"
GLOBAL_DIR="$ROOT/roster/global-agent"
MODELS_MD="$ROOT/roster/MODELS.md"
PREVIEW_MD="$ROOT/roster/injected-preview.md"
BEGIN_MARK='<!-- BEGIN GENERATED: roster -->'
END_MARK='<!-- END GENERATED: roster -->'
FRAGMENT="$ROOT/roster/fragments/review-checklist.md"
REV_BEGIN='<!-- BEGIN GENERATED: review-checklist -->'
REV_END='<!-- END GENERATED: review-checklist -->'
# Review rung prompts that carry the spliced reviewer checklist (repo-relative).
REVIEW_TARGETS=(
  "roster/global-agent/cheap-review.md"
  "roster/global-agent/strong-review.md"
  "roster/global-agent/strong-review-alternative.md"
  "roster/global-agent/strong-review-alternative2.md"
  "workflow/agent/review.md"
)

die() { echo "roster/build.sh: $*" >&2; exit 2; }

command -v jq >/dev/null 2>&1 || die "jq is required"
[[ -f "$SRC_JSON" ]] || die "missing $SRC_JSON"
jq -e 'type == "object"' "$SRC_JSON" >/dev/null 2>&1 || die "$SRC_JSON is not a JSON object"
[[ -f "$FRAGMENT" ]] || die "missing $FRAGMENT"

# Exactly one BEGIN and one END marker in a target file: a missing or duplicated
# marker would make the awk splice drop or duplicate the rest of the file. Fail closed.
check_markers() {
  local file="$1" b e
  [[ -f "$file" ]] || die "missing $file"
  b="$(grep -cF "$2" "$file" 2>/dev/null || true)"
  e="$(grep -cF "$3" "$file" 2>/dev/null || true)"
  [[ "$b" == 1 && "$e" == 1 ]] || die "$file must contain exactly one BEGIN and one END marker (found BEGIN=$b END=$e)"
}
check_markers "$MODELS_MD" "$BEGIN_MARK" "$END_MARK"
for t in "${REVIEW_TARGETS[@]}"; do check_markers "$ROOT/$t" "$REV_BEGIN" "$REV_END"; done

# The roster names: every *.md in roster/global-agent (the files that install).
# An agent with no models.json entry is rendered as "(no model entry)" — the
# install then warns and skips the injection, so the gap is visible, not fatal.
agent_names() {
  local f
  for f in "$GLOBAL_DIR"/*.md; do
    [[ -e "$f" ]] || continue
    basename "$f" .md
  done
}

# Fields of one global agent entry: model, variant, family_hint (may be "").
entry_field() {
  jq -r --arg a "$1" --arg f "$2" '.global[$a][$f] // ""' "$SRC_JSON"
}

# Project seats (top-level keys except "global" and "prices").
project_seats() {
  jq -r 'to_entries[] | select(.key != "global" and .key != "prices") | .key' "$SRC_JSON"
}

# MODELS.md generated block (between the markers, markers excluded).
render_models_block() {
  local name model variant fam seat
  echo "The block below is generated from \`roster/models.json\` by \`roster/build.sh\` — do not edit it by hand."
  echo
  echo "**Project seats** (\`.opencode/agent/\`, \`init.sh\` project mode):"
  echo
  echo "| Seat | Model | Variant | Family |"
  echo "|---|---|---|---|"
  while IFS= read -r seat; do
    model="$(jq -r --arg a "$seat" '.[$a].model // ""' "$SRC_JSON")"
    variant="$(jq -r --arg a "$seat" '.[$a].variant // "—"' "$SRC_JSON")"
    fam="$(jq -r --arg a "$seat" '.[$a].family_hint // "—"' "$SRC_JSON")"
    echo "| \`$seat\` | \`$model\` | $variant | $fam |"
  done < <(project_seats)
  echo
  echo "**Global roster** (\`roster/global-agent/*.md\`, \`init.sh --global\`):"
  echo
  echo "| Agent | Model | Variant | Family |"
  echo "|---|---|---|---|"
  while IFS= read -r name; do
    model="$(entry_field "$name" model)"
    variant="$(entry_field "$name" variant)"
    fam="$(entry_field "$name" family_hint)"
    if [[ -z "$model" ]]; then
      echo "| \`$name\` | *(no model entry)* | — | — |"
    else
      echo "| \`$name\` | \`$model\` | ${variant:-—} | ${fam:-—} |"
    fi
  done < <(agent_names)
}

# roster/injected-preview.md : the injected lines as installed, per agent.
render_preview() {
  local name model variant fam
  echo "# Injected block preview (generated)"
  echo
  echo "Generated by \`roster/build.sh\` from \`roster/models.json\` (\`global\` section)."
  echo "These are the frontmatter lines \`init.sh --global\` injects into each installed"
  echo "agent (see \`set_agent_model\` in \`init.sh\`). Do not edit; regenerate."
  echo
  while IFS= read -r name; do
    echo "## $name"
    echo
    echo '```yaml'
    model="$(entry_field "$name" model)"
    if [[ -z "$model" ]]; then
      echo "# (no model entry in models.json — install warns and injects nothing)"
    else
      variant="$(entry_field "$name" variant)"
      fam="$(entry_field "$name" family_hint)"
      echo "model: $model"
      [[ -n "$variant" ]] && echo "variant: $variant"
      [[ -n "$fam" ]] && echo "# Model family: $fam."
    fi
    echo '```'
    echo
  done < <(agent_names)
}

# splice SRC BEGIN END BLOCK_FILE OUT : copy SRC to OUT with the text between
# the markers replaced by the content of BLOCK_FILE (markers kept).
splice() {
  awk -v b="$2" -v e="$3" -v blk="$4" '
    $0 == b { print; while ((getline line < blk) > 0) print line; close(blk); skip = 1; next }
    $0 == e { skip = 0 }
    !skip { print }
  ' "$1" > "$5"
}

# generate OUT_DIR : write every generated artifact into OUT_DIR under the names
# listed by artifact_pairs (MODELS.md is rebuilt from the committed copy,
# replacing only the region between the markers).
generate() {
  local out="$1" block i=0 t
  block="$(mktemp)"
  render_models_block > "$block"
  splice "$MODELS_MD" "$BEGIN_MARK" "$END_MARK" "$block" "$out/MODELS.md"
  rm -f "$block"
  render_preview > "$out/injected-preview.md"
  for t in "${REVIEW_TARGETS[@]}"; do
    splice "$ROOT/$t" "$REV_BEGIN" "$REV_END" "$FRAGMENT" "$out/review-$i.md"
    i=$((i + 1))
  done
}

# artifact_pairs : one "generated-name:committed-path" line per artifact.
artifact_pairs() {
  local i=0 t
  echo "MODELS.md:$MODELS_MD"
  echo "injected-preview.md:$PREVIEW_MD"
  for t in "${REVIEW_TARGETS[@]}"; do
    echo "review-$i.md:$ROOT/$t"
    i=$((i + 1))
  done
}

if [[ "${1:-}" == "--check" ]]; then
  tmp="$(mktemp -d)"
  trap 'rm -rf "$tmp"' EXIT
  generate "$tmp"
  drift=0
  while IFS= read -r pair; do
    gen="$tmp/${pair%%:*}"; committed="${pair#*:}"
    if [[ ! -f "$committed" ]]; then
      echo "drift: ${committed#$ROOT/} is missing (run roster/build.sh)" >&2
      drift=1
    elif ! cmp -s "$gen" "$committed"; then
      summary="$(diff "$committed" "$gen" | awk '/^</{d++} /^>/{a++} END{printf "+%d/-%d lines", a+0, d+0}')" || true
      echo "drift: ${committed#$ROOT/} differs from models.json ($summary)" >&2
      diff -u "$committed" "$gen" | head -40 >&2 || true
      drift=1
    fi
  done < <(artifact_pairs)
  if [[ $drift -ne 0 ]]; then
    echo "roster/build.sh --check: FAILED — run roster/build.sh and commit the result." >&2
    exit 1
  fi
  echo "roster/build.sh --check: OK — generated roster artifacts match models.json"
  exit 0
fi

[[ $# -eq 0 ]] || die "unknown argument: $1 (usage: build.sh [--check])"
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT
generate "$tmp"
cp "$tmp/MODELS.md" "$MODELS_MD"
cp "$tmp/injected-preview.md" "$PREVIEW_MD"
i=0
for t in "${REVIEW_TARGETS[@]}"; do
  cp "$tmp/review-$i.md" "$ROOT/$t"
  i=$((i + 1))
done
echo "roster/build.sh: wrote ${MODELS_MD#$ROOT/}, ${PREVIEW_MD#$ROOT/} and ${#REVIEW_TARGETS[@]} review prompt(s)"
