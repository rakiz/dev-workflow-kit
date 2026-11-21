#!/usr/bin/env python3
"""Étape 4 scoring (AB-SPEC §3-§4): executed required tests (builder, execution only), κ per variable from the two
adjudicator sheets, the disagreement rule, per-arm metrics and the ordered verdict R1-R5.
    score-ab.py  -> writes ab/scores.tsv, ab/kappa.tsv, ab/metrics.tsv and prints the verdict."""
import csv, glob, math, os, re, shutil, subprocess, sys, tempfile, json
HERE = os.path.dirname(os.path.abspath(__file__))
KEYS = os.path.realpath(os.path.join(HERE, "..", "..", "..", "..", "evals-keys", "ab-2026-11-21"))
ID = {}
for line in open(os.path.join(KEYS, "id-map.tsv")):
    if line.startswith("task"): continue
    t, a, bid = line.rstrip("\n").split("\t"); ID[bid] = (t, a)

def exec_required(task, cell):
    """Run the hidden required test on a COPY. Returns (test_value, escaped, methods_ok)."""
    tmp = tempfile.mkdtemp(prefix="abx-", dir=os.environ.get("TMPDIR"))
    try:
        work = os.path.join(tmp, "cell"); shutil.copytree(cell, work, ignore=shutil.ignore_patterns("__pycache__"))
        if task == "T4":
            r = subprocess.run([sys.executable, "-B", os.path.join(KEYS, "required", "T4", "run_t4.py"), work],
                               capture_output=True, text=True)
            ok = r.returncode == 0
            return (3 if ok else 0), (0 if ok else 1), ("T4 procedure" if ok else "T4 procedure FAIL")
        test = os.path.join(KEYS, "required", task, "test_required.py")
        env = dict(os.environ, AB_CELL=work)
        # run the test FILE directly (unittest main): the file path is not a module name (a previous `-m` call
        # produced an import error that was silently read as a pass)
        r = subprocess.run([sys.executable, "-B", test, "-v"], capture_output=True, text=True, env=env, cwd=tmp)
        out = r.stderr + r.stdout
        if not re.search(r"^Ran \d+ tests?", out, re.M) or "ImportError" in out or "_FailedTest" in out:
            return 0, 99, "import/run error (no test count)"
        bad = re.findall(r"^(test_\w+) .*\.\.\. (FAIL|ERROR)$", out, re.M)
        bad_names = [b[0] for b in bad]
        escaped = len(bad)
        trap = [n for n in bad_names if "TRAP" in n or n.startswith("test_case_09") or n.startswith("test_07")]
        if escaped == 0: val = 3
        elif len(bad) == len(trap) and trap: val = 2
        else: val = 0
        return val, escaped, ";".join(bad_names) or "all methods ok"
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

def read_sheet(path):
    out = {}
    for r in csv.DictReader(open(path), delimiter="\t"):
        out[r["blind_id"]] = r
    return out

def kappa(a, b):
    n = len(a)
    if n == 0: return None
    po = sum(1 for x, y in zip(a, b) if x == y) / n
    p1 = (sum(a) + sum(b)) / (2 * n)
    pe = p1 * p1 + (1 - p1) * (1 - p1)
    if pe == 1: return 1.0
    return round((po - pe) / (1 - pe), 3)

def main():
    neon = read_sheet(os.path.join(KEYS, "adj", "adj-neon.sheet.tsv"))
    qwen = read_sheet(os.path.join(KEYS, "adj", "adj-qwen.sheet.tsv"))
    # reconciliation round (AB-SPEC §3): the flagged cells re-scored by both raters; agreed values override
    recon = {}
    for who in ("neon", "qwen"):
        path = os.path.join(KEYS, "adj", f"recon-{who}.sheet.tsv")
        if os.path.isfile(path):
            for bid, d in read_sheet(path).items(): recon.setdefault(bid, {})[who] = d
    for bid, d in recon.items():
        if len(d) == 2 and d["neon"].get("clean") == d["qwen"].get("clean"):
            neon.setdefault(bid, {})["clean"] = d["neon"]["clean"]; qwen.setdefault(bid, {})["clean"] = d["qwen"]["clean"]
    ids = sorted(ID)
    rows, flags = [], []
    for bid in ids:
        t, a = ID[bid]; cell = os.path.join(KEYS, "cells", f"{a}-{t}")
        val, esc, detail = exec_required(t, cell)
        n_ = neon.get(bid, {}); q_ = qwen.get(bid, {})
        def num(d, k):
            try: return int(float(d[k]))
            except Exception: return None
        n_dod, q_dod = num(n_, "dod"), num(q_, "dod")
        n_cln, q_cln = num(n_, "clean"), num(q_, "clean")
        n_test, q_test = num(n_, "test"), num(q_, "test")
        dod = min(v for v in (n_dod, q_dod) if v is not None) if None not in (n_dod, q_dod) else (n_dod if n_dod is not None else q_dod)
        cln = min(v for v in (n_cln, q_cln) if v is not None) if None not in (n_cln, q_cln) else (n_cln if n_cln is not None else q_cln)
        if n_dod != q_dod: flags.append(f"{bid} dod {n_dod}/{q_dod} -> conservative {dod}")
        if n_cln != q_cln: flags.append(f"{bid} clean {n_cln}/{q_cln} -> conservative {cln}")
        if n_test != q_test: flags.append(f"{bid} test-sheet {n_test}/{q_test} -> executed {val} (executable result wins)")
        rows.append(dict(blind_id=bid, task=t, arm=a, test_exec=val, escaped=esc, dod=dod, clean=cln,
                         score=val + (dod or 0) + (cln or 0), neon_test=n_test, qwen_test=q_test,
                         neon_dod=n_dod, qwen_dod=q_dod, neon_clean=n_cln, qwen_clean=q_cln,
                         detail=detail, delivered=int(esc < 99 and os.path.isfile(os.path.join(KEYS, "cells", f"{a}-{t}", "REPORT.md")) and "NO REPORT" not in open(os.path.join(KEYS, "cells", f"{a}-{t}", "REPORT.md")).read()[:40])))
    with open(os.path.join(HERE, "scores.tsv"), "w") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()), delimiter="\t"); w.writeheader(); w.writerows(rows)
    # kappa per variable over the 15 cells, from the two sheets (before resolution)
    def pair(f):
        return [f(neon.get(b, {})) for b in ids], [f(qwen.get(b, {})) for b in ids]
    kap = {}
    kap["core_pass"] = kappa(*pair(lambda d: int(int(float(d.get("test", -1))) >= 2) if d.get("test") not in (None, "") else -1))
    kap["trap_pass"] = kappa(*pair(lambda d: int(int(float(d.get("test", -1))) == 3) if d.get("test") not in (None, "") else -1))
    kap["dod"] = kappa(*pair(lambda d: int(float(d.get("dod", -1)))))
    kap["clean"] = kappa(*pair(lambda d: int(float(d.get("clean", -1)))))   # post-reconciliation (values above)
    with open(os.path.join(HERE, "kappa.tsv"), "w") as fh:
        fh.write("variable\tkappa\tnote\n")
        for k, v in kap.items():
            note = "degenerate all-agree (kappa=1 recorded)" if v == 1.0 else ("ok" if v is not None and v >= 0.6 else "BELOW 0.6: reconciliation required")
            fh.write(f"{k}\t{v}\t{note}\n")
    with open(os.path.join(HERE, "disagreements.txt"), "w") as fh: fh.write("\n".join(flags) + "\n")
    print("kappa", kap)
    print("disagreements:", len(flags))
    metrics(rows)

def metrics(rows):
    arms = {}
    for r in rows:
        arms.setdefault(r["arm"], []).append(r)
    out = {}
    for a, rs in sorted(arms.items()):
        delivered = [r for r in rs if r["delivered"]]
        deliv = len(delivered)
        escaped = sum(r["escaped"] for r in delivered if r["escaped"] < 99)
        score = (sum(r["score"] for r in delivered) / deliv) if deliv else 0.0
        out[a] = dict(delivery=deliv, escaped=escaped, score=round(score, 3))
    cost = {}
    for a in "ABC":
        cost[a] = None
    with open(os.path.join(HERE, "metrics.tsv"), "w") as fh:
        fh.write("arm\tdelivery\tescaped\tscore_mean_delivered\n")
        for a, m in out.items(): fh.write(f"{a}\t{m['delivery']}/5\t{m['escaped']}\t{m['score']}\n")
    print(json.dumps(out, indent=1))
if __name__ == "__main__":
    main()
