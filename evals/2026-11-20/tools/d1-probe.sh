#!/usr/bin/env bash
# D1 probe layer for one RG4 run dir, in the same section layout as probes/<run>.txt
# (parsed by tools/rg4_deterministic.py). Usage: d1-probe.sh <run-dir> <out-file>
#   suite_green  : candidate code + pristine test_reportgen.py (suite-rg4.sh method)
#   probes a-d   : 2026-11-19/logs/phase3/probes-rg4.sh (executed, unchanged)
#   own pristine : the candidate's test files (except test_legacy_report.py) run on the PRISTINE fixture
set -u
RUN="$(cd "$1" && pwd)"; OUT="$2"
EVAL="$HOME/code_projects/IA-tooling/dev-workflow-kit/evals"
PRI="$EVAL/reportgen-eval-repo-i4"
PROBES="$EVAL/2026-11-19/logs/phase3/probes-rg4.sh"
NAME="$(basename "$RUN")"
S="$(mktemp -d)"
{
  cp -R "$RUN" "$S/cand" && cd "$S/cand" || exit 1
  rm -rf __pycache__
  # suite_green = candidate code under the PRISTINE test_reportgen.py (suite-rg4.sh method, scoring step 2)
  cp "$PRI/test_reportgen.py" test_reportgen.py
  python3 -B -m unittest test_reportgen > "$S/suite.out" 2>&1; SX=$?
  echo "SUITE_EXIT=$SX"; grep -E '^(Ran [0-9]+ tests|OK$|FAILED)' "$S/suite.out"
  echo "===== $NAME ====="
  echo "--- suite_green:"
  echo "SUITE_EXIT=$SX"; grep -E '^(Ran [0-9]+ tests|OK$|FAILED)' "$S/suite.out"
  cd "$S" || exit 1
  bash "$PROBES" "$RUN" > "$S/probes.out" 2>&1
  # map the probes-rg4.sh headers onto the parser's "--- probe x:" sections
  awk '
    /^== probe-a/ { print "--- probe a:"; next }
    /^== probe-b/ { print "--- probe b:"; next }
    /^== probe-c/ { print "--- probe c:"; next }
    /^== probe-d/ { print "--- probe d:"; next }
    /^== / { next }
    /^rules_opens=/ { sub(/^rules_opens=/, ""); print; next }
    /^base-exit=/ { next }   # baseline exit is not probe d
    { print }
  ' "$S/probes.out"
  # own tests on the pristine fixture: candidate test files (not the legacy suite) over the pristine code
  P="$S/pristine"; cp -R "$PRI" "$P"; rm -rf "$P/__pycache__"
  MODS=""
  for f in "$RUN"/test_*.py; do
    b="$(basename "$f")"; [ "$b" = "test_legacy_report.py" ] && continue
    cp "$f" "$P/$b"; MODS="$MODS ${b%.py}"
  done
  cd "$P" || exit 1
  python3 -B -m unittest -v $MODS > "$S/pristine.out" 2>&1; PX=$?
  echo "PRISTINE_TESTS_EXIT=$PX"
  grep -E ' \.\.\. (ok|FAIL|ERROR)$' "$S/pristine.out"
  echo "[tail]"
  grep -E '^Ran [0-9]+ tests|^FAILED|^OK$' "$S/pristine.out"
  echo "WORK=$S"
} > "$OUT"
echo "wrote $OUT"
