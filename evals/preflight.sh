#!/usr/bin/env bash
# preflight.sh — fail-closed launch gate (AUTONOMOUS-RUN.md §8, rule R1).
# A failure here is not advice — no launch.
# Usage: preflight.sh --dir <dir> --budget <usd> --caps <c1,c2,...> \
#                     --title-fragment <frag> [--path <p>]...
# Checks: (a) every --path under --dir; (b) sqlite3 + DB readable, no session
# matching --title-fragment (required, R1(a)) with time_updated within 300 s;
# (c) budget > 2 x sum(caps) (strict). NOTE: run-campaign.py admission also
# counts current spend + already-reserved caps against the budget
# (spent + reserved + 2*cap <= budget); preflight is the pre-launch static half
# (spend = reserved = 0). Exits 0 on PASS, 1 naming the failed check.
# Deps: bash, sqlite3, awk, realpath.
set -euo pipefail

DB="${OPENCODE_DB:-$HOME/.local/share/opencode/opencode.db}"
LIVE_WINDOW_S=300
DIR=""; BUDGET=""; CAPS=""; FRAG=""; PATHS=()
fail() { echo "FAIL: $*" >&2; exit 1; }
pass() { echo "PASS: preflight ok (dir=$DIR budget=$BUDGET caps=$CAPS reservation=$RES)"; exit 0; }

while [ $# -gt 0 ]; do
  case "$1" in
    --dir)            [ $# -ge 2 ] || fail "missing value for $1"; DIR="$2";;
    --budget)         [ $# -ge 2 ] || fail "missing value for $1"; BUDGET="$2";;
    --caps)           [ $# -ge 2 ] || fail "missing value for $1"; CAPS="$2";;
    --title-fragment) [ $# -ge 2 ] || fail "missing value for $1"; FRAG="$2";;
    --path)           [ $# -ge 2 ] || fail "missing value for $1"; PATHS+=("$2");;
    -h|--help)        awk 'NR>=2 && NR<=12' "$0"; exit 0;;
    *)                fail "unknown argument: $1";;
  esac
  shift 2
done

# --title-fragment is mandatory (R1(a)): a silent no-op live-session guard is
# exactly the bug class this script exists to kill.
[ -n "$FRAG" ] || fail "usage: --title-fragment is required (R1(a))"

# (a) --dir present; every --path under it (realpath, no symlink invention).
[ -n "$DIR" ] || fail "check (a): --dir is required"
[ -d "$DIR" ] || fail "check (a): --dir is not a directory: $DIR"
CDIR=$(realpath "$DIR")
canon() {  # realpath a path that may not exist yet (resolve deepest ancestor).
  local p=$1 dir base
  if [ -e "$p" ]; then realpath "$p"; return 0; fi
  dir=$(dirname "$p"); base=$(basename "$p")
  while [ ! -d "$dir" ] && [ "$dir" != "/" ]; do
    base="$(basename "$dir")/$base"; dir=$(dirname "$dir")
  done
  printf '%s/%s\n' "$(realpath "$dir")" "$base"
}
for p in ${PATHS[@]+"${PATHS[@]}"}; do
  CP=$(canon "$p") || fail "check (a): cannot canonicalize path: $p"
  case "$CP" in
    "$CDIR"|"$CDIR"/*) : ;;
    *) fail "check (a): path not under --dir: $p -> $CP (dir $CDIR)";;
  esac
done

# (b) sqlite3 + DB readable; live-session guard on --title-fragment.
command -v sqlite3 >/dev/null 2>&1 || fail "check (b): sqlite3 not on PATH"
[ -r "$DB" ] || fail "check (b): opencode DB not readable at $DB"
sqlite3 -readonly "$DB" "PRAGMA schema_version;" >/dev/null 2>&1 \
  || fail "check (b): cannot read opencode DB at $DB"
if [ -n "$FRAG" ]; then
  esc=${FRAG//\'/\'\'}
  n=$(sqlite3 -readonly "$DB" \
    "SELECT COUNT(*) FROM session WHERE title LIKE '%$esc%' AND time_updated >= (strftime('%s','now')-$LIVE_WINDOW_S)*1000;" \
    2>/dev/null) || fail "check (b): session query failed"
  [ "$n" = "0" ] || fail "check (b): live session on the same target (title~'$FRAG', within ${LIVE_WINDOW_S}s): $n"
fi

# (c) budget > 2 x sum(caps) (strict: must exceed the reservation).
[ -n "$BUDGET" ] || fail "check (c): --budget is required"
[ -n "$CAPS" ] || fail "check (c): --caps is required"
RES=$(awk -v b="$BUDGET" -v c="$CAPS" 'BEGIN{
  if (b !~ /^[0-9]+([.][0-9]+)?$/) { print "FAIL: check (c): --budget not numeric: " b > "/dev/stderr"; exit 1 }
  n=split(c, a, ","); s=0
  for (i=1;i<=n;i++) {
    if (a[i]=="") continue
    if (a[i] !~ /^[0-9]+([.][0-9]+)?$/) { print "FAIL: check (c): cap not numeric: " a[i] > "/dev/stderr"; exit 1 }
    s+=a[i]
  }
  if (b+0 <= 2*s) { printf "FAIL: check (c): budget %s <= 2 x sum(caps)=%s (strict: budget must exceed the reservation)\n", b, 2*s > "/dev/stderr"; exit 1 }
  printf "%s", 2*s
  exit 0
}') || exit 1

pass
