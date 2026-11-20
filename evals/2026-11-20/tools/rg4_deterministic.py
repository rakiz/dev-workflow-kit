#!/usr/bin/env python3
"""Extract the RG4 deterministic layer (suite, probes a/b/c'/d, own-tests-on-pristine)
from the drive.sh outputs in probes/<run>.txt. One TSV row per run. Read-only."""
import re, sys, pathlib
base = pathlib.Path(__file__).resolve().parent.parent
rows = []
for f in sorted((base / "probes").glob("*.txt")):
    t = f.read_text(errors="replace")
    run = f.name[:-4]
    def sect(name):
        m = re.search(r"--- %s:\n(.*?)(?=\n--- |\n[A-Z_]+=|\Z)" % re.escape(name), t, re.S)
        return m.group(1).strip().splitlines() if m else []
    suite = "green" if re.search(r"SUITE_EXIT=0", t) and re.search(r"^OK$", t, re.M) else "red"
    a = re.search(r"merchant\.distinct=(\d+)", t)
    a = a.group(1) if a else "NA"
    b = "IDENTICAL" if "REPORTS-IDENTICAL" in t else ("DIFFER" if "REPORTS-DIFFER" in t else "NA")
    g = re.search(r"generated_from=(\d+)", t)
    g = g.group(1) if g else "NA"
    c = [l for l in sect("probe c") if l.strip().isdigit()]
    c = c[-1] if c else "NA"
    dexit = re.search(r"exit=(\d+)", t)
    dexit = dexit.group(1) if dexit else "NA"
    dstate = ("INTACT" if "PREVIOUS-OUTPUT-AND-STATE-INTACT" in t else
              "CHANGED" if "PREVIOUS-OUTPUT-OR-STATE-CHANGED" in t else "NA")
    m = re.search(r"Ran (\d+) tests.*?\n(OK|FAILED \(([^)]*)\))", t.split("[tail]")[-1] if "[tail]" in t else "", re.S)
    ran = fail = "NA"
    if "[tail]" in t:
        tail = t.split("[tail]")[1]
        r = re.search(r"Ran (\d+) tests", tail)
        ran = r.group(1) if r else "NA"
        fm = re.search(r"FAILED \(([^)]*)\)", tail)
        if fm:
            nums = dict((k, int(v)) for k, v in re.findall(r"(\w+)=(\d+)", fm.group(1)))
            fail = str(nums.get("failures", 0) + nums.get("errors", 0))
        elif re.search(r"^\s*OK$", tail, re.M):
            fail = "0"
    rows.append([run, suite, a, b, g, c, dexit, dstate, ran, fail])
hdr = ["run_dir", "suite", "probe_a_distinct", "probe_b", "probe_b_gen_from",
       "probe_c_rules_opens", "probe_d_exit", "probe_d_state", "own_tests_ran",
       "own_tests_fail_on_pristine"]
out = "\n".join("\t".join(map(str, r)) for r in [hdr] + rows)
print(out)
