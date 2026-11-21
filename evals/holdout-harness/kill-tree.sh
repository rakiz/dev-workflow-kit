#!/usr/bin/env bash
# kill-tree.sh — fail-closed kill of a process AND all of its descendants (fix for the arbiter overspend).
# Library (source it) + self-test (run it with --self-test). kill_tree ROOT [GRACE]:
#   1) snapshot the whole tree BEFORE signalling (orphans re-parent to 1 and would be invisible afterwards),
#   2) TERM everything in the snapshot, 3) wait GRACE s, 4) KILL every survivor from the union of snapshots,
#   5) verify. Prints TREE-DEAD (n) or TREE-ALIVE:<pids> and returns non-zero if anything survives.
# alive = signal-deliverable AND not a zombie (a zombie answers kill -0 but has already exited)
is_alive() { local st; st="$(ps -o stat= -p "$1" 2>/dev/null)"; [ -n "$st" ] && case "$st" in Z*) return 1;; esac; kill -0 "$1" 2>/dev/null; }
descendants() { local p="$1" c; for c in $(pgrep -P "$p" 2>/dev/null); do descendants "$c"; echo "$c"; done; }
kill_tree() {
  local root="$1" grace="${2:-3}" seen snap p alive
  seen="$( { echo "$root"; descendants "$root"; } | sort -u | tr '\n' ' ')"
  [ -n "$seen" ] && kill -TERM $seen 2>/dev/null
  sleep "$grace"
  snap="$( { echo "$root"; descendants "$root"; echo $seen; } | tr ' ' '\n' | grep -E '^[0-9]+$' | sort -u)"
  alive=""
  for p in $snap; do is_alive "$p" && alive="$alive $p"; done
  [ -n "$alive" ] && kill -KILL $alive 2>/dev/null
  # poll for death (launcher-wrapped processes can take more than a second to exit after SIGKILL)
  local i
  for i in 1 2 3 4 5 6 7 8 9 10; do
    alive=""
    for p in $snap; do is_alive "$p" && alive="$alive $p"; done
    [ -z "$alive" ] && break
    sleep 0.5
  done
  if [ -z "$alive" ]; then echo "TREE-DEAD ($(echo $snap | wc -w | tr -d ' ') processes)"; return 0; fi
  echo "TREE-ALIVE:$alive"; return 1
}
selftest() {
  # zero-cost: a stand-in session that IGNORES TERM, with a child and a grandchild, all ignoring TERM
  sh -c 'trap "" TERM; (trap "" TERM; (trap "" TERM; while :; do sleep 1; done) & while :; do sleep 1; done) & while :; do sleep 1; done' &
  local root=$!; sleep 2
  local before out
  before="$(descendants $root | wc -l | tr -d ' ')"
  out="$(kill_tree "$root" 2)"; echo "descendants before=$before -> $out"
  case "$out" in
    TREE-DEAD*) if pgrep -P "$root" >/dev/null; then echo "SELF-TEST FAIL: children remain"; return 1; fi
                echo "SELF-TEST PASS"; return 0 ;;
    *) echo "SELF-TEST FAIL"; return 1 ;;
  esac
}
if [ "${BASH_SOURCE[0]}" = "$0" ] && [ "${1:-}" = "--self-test" ]; then selftest; exit $?; fi
