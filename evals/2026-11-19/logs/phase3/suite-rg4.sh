#!/usr/bin/env bash
# RUBRIC-IV2-RG4 suite_green + candidate-test check. Usage: suite-rg4.sh <run-dir>
RUN="$1"; PRI=/Users/sebastien.mendez/code_projects/IA-tooling/dev-workflow-kit/evals/reportgen-eval-repo-i4
S=$(mktemp -d); cp -R "$RUN" "$S/repo"; cd "$S/repo" || exit 1
ls test_*.py | tr '\n' ' '; echo
cp "$PRI/test_reportgen.py" test_reportgen.py      # pristine overlay (scoring step 2)
python3 -B -m unittest test_reportgen >/tmp/sg.out 2>&1; echo "suite_green-exit=$? ($(tail -1 /tmp/sg.out))"
# candidate-added test files (not in pristine)
for f in $(ls test_*.py); do [ -f "$PRI/$f" ] || echo "candidate-test-file: $f"; done
rm -rf "$S"
