#!/usr/bin/env bash
# scripts/release.sh — pre-release gate for the kit. Checks, then guides.
#
#   scripts/release.sh [--version X.Y.Z]
#
# What it does:
#   1. refuses unless the work tree is clean, except the two known owner
#      leftovers (evals/COMPARATORS.md, evals/preflight.sh) — a release is cut
#      from committed state only;
#   2. runs the gates: init.sh --self-check, roster/build.sh --check,
#      scripts/smoke.sh;
#   3. prints the release steps for VERSION, CHANGELOG and the tag, with the
#      values to use. It writes no release files itself: no VERSION bump, no
#      CHANGELOG edit, no commit, no tag, and NEVER a push. The maintainer runs
#      those steps (see the deviation note in docs/plans/workflow-v2.1.md §8 P1).
#
# Exit 0 when every gate passes (guidance printed); 1 on any refusal or failed gate.

set -u

KIT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$KIT_DIR" || exit 1

NEXT=""
if [[ "${1:-}" == "--version" ]]; then
  NEXT="${2:-}"
  [[ "$NEXT" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]] || { echo "release.sh: --version expects X.Y.Z" >&2; exit 1; }
elif [[ $# -gt 0 ]]; then
  echo "usage: scripts/release.sh [--version X.Y.Z]" >&2
  exit 1
fi

TMP="$(mktemp -d "${TMPDIR:-/tmp}/dwk-release.XXXXXX")"
trap 'rm -rf "$TMP"' EXIT

CUR="$(tr -d '[:space:]' < VERSION)"
FAILED=0

echo "== 1. tree state"
# porcelain lines: "XY path". Everything except the two known leftovers refuses.
dirty="$(git status --porcelain | grep -v -e ' evals/COMPARATORS.md$' -e ' evals/preflight.sh$' || true)"
if [[ -n "$dirty" ]]; then
  echo "  REFUSED: the work tree has uncommitted changes (commit or stash them first):" >&2
  printf '%s\n' "$dirty" | sed 's/^/    /' >&2
  echo "release.sh: NOT ready — commit or stash the changes above, then re-run (gates skipped)."
  exit 1
else
  echo "  ok    clean (apart from the known evals/ leftovers)"
fi

echo "== 2. gates"
if bash -c "'$KIT_DIR/init.sh' --self-check" >"$TMP/self.out" 2>&1; then
  echo "  ok    init.sh --self-check"
else
  echo "  FAIL  init.sh --self-check" >&2; sed 's/^/        /' "$TMP/self.out" >&2; FAILED=1
fi
if "$KIT_DIR/roster/build.sh" --check >"$TMP/build.out" 2>&1; then
  echo "  ok    roster/build.sh --check"
else
  echo "  FAIL  roster/build.sh --check" >&2; sed 's/^/        /' "$TMP/build.out" >&2; FAILED=1
fi
if "$KIT_DIR/scripts/smoke.sh" >"$TMP/smoke.out" 2>&1; then
  echo "  ok    scripts/smoke.sh ($(tail -1 "$TMP/smoke.out"))"
else
  echo "  FAIL  scripts/smoke.sh" >&2; tail -20 "$TMP/smoke.out" | sed 's/^/        /' >&2; FAILED=1
fi
if [[ $FAILED -ne 0 ]]; then
  echo ""
  echo "release.sh: NOT ready — fix the refusals/failures above, then re-run."
  exit 1
fi

echo "== 3. release steps (not executed here)"
echo "  current VERSION: $CUR"
if git rev-parse -q --verify "refs/tags/v$CUR" >/dev/null; then
  echo "  note  tag v$CUR already exists — a new release needs a new VERSION"
fi
if [[ -n "$NEXT" ]]; then
  if git rev-parse -q --verify "refs/tags/v$NEXT" >/dev/null; then
    echo "  REFUSED: tag v$NEXT already exists" >&2
    exit 1
  fi
  target="$NEXT"
else
  target="X.Y.Z"
fi
cat <<EOF
  1. VERSION: set it to $target (one line, no other change)
  2. CHANGELOG.md: add a "## [$target] - <date>" section above the previous
     release (Security / Added / Changed / Fixed as applicable)
  3. commit the release: one commit with VERSION + CHANGELOG.md
     (commit message: "release: v$target")
  4. re-run this script on the committed tree (it must pass clean)
  5. tag the release commit:  git tag -a v$target -m "dev-workflow-kit v$target"
  6. push: MAINTAINER ONLY, with its own explicit authorization for that one push:
     git push origin HEAD v$target
  Rollback before the push: git tag -d v$target && git reset --soft HEAD~1 (never after a push).

release.sh: all gates passed. Nothing was changed — the steps above are yours to run.
EOF
exit 0
