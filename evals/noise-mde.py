#!/usr/bin/env python3
"""Run-to-run noise and minimum detectable effect (MDE) per bench, from the noise panel.

Input : the noise panel batch TSVs (`*-batch-*.tsv`), header
        run_id, bench, family, score, fp, breakdown, notes
        Default dir: ../../evals-keys/score-logs/2026-11-20/panel-noise (relative to this file).
Output: <DAY>/noise-runs.tsv  per run: score per family + combined (mean of families)
        <DAY>/noise-mde.tsv   per bench x (family | combined): n, mean, sd, range, MDE
        DAY = 2026-11-20 (default output dir: this file's dir / 2026-11-20).

Method (fixed before reading real data, see AGGREGATE-NOISE.md):
  - Four identical runs per bench. sd = sample standard deviation (ddof=1), range = max - min.
  - Combined run score = mean of the family scores of that run (both families).
  - MDE of a gap between two arms of n valid runs each (PROTOCOL: n=2 per cell),
    two-sided alpha 0.05, power 0.80:
        MDE = (t_0.975,df + t_0.80,df) * sd * sqrt(2/n)
    with df = n_runs - 1 of the sd (small-sample t quantiles, table below; the
    pooled df of the 2-vs-2 comparison is smaller, so the MDE is conservative-high).
  - stdlib only. Read-only on inputs. Missing runs are reported, never invented.
"""

import csv
import glob
import math
import os
import re
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
DAY = "2026-11-20"
DEFAULT_PANEL = os.path.normpath(os.path.join(_HERE, "..", "..", "evals-keys", "score-logs", DAY, "panel-noise"))
DEFAULT_OUT = os.path.join(_HERE, DAY)
BENCHES = ["O", "IR", "DR2", "I2-RG4", "D"]
FAMILIES = ["glm", "minimax"]
RUNS_PER_BENCH = 4
N_CELL = 2  # valid runs per arm (PROTOCOL §2 rule 1)

# two-sided 0.975 and one-sided 0.80 Student-t quantiles, df = 1..5
T975 = {1: 12.706, 2: 4.303, 3: 3.182, 4: 2.776, 5: 2.571}
T80 = {1: 1.376, 2: 1.061, 3: 0.978, 4: 0.941, 5: 0.920}
COLUMNS = ["run_id", "bench", "family", "score", "fp", "breakdown", "notes"]


def read_batches(panel_dir):
    """All (run_id, bench, family, score, fp) rows of the batch TSVs, plus any problems."""
    rows, problems = [], []
    files = sorted(glob.glob(os.path.join(panel_dir, "*-batch-*.tsv")))
    if not files:
        sys.exit(f"no batch TSV in {panel_dir}")
    for path in files:
        with open(path, encoding="utf-8", newline="") as fh:
            reader = csv.DictReader(fh, delimiter="\t")
            if reader.fieldnames is None or any(c not in reader.fieldnames for c in ("run_id", "bench", "family", "score")):
                problems.append(f"{os.path.basename(path)}: header missing run_id/bench/family/score")
                continue
            for n, r in enumerate(reader, 2):
                rid = (r.get("run_id") or "").strip()
                if not rid:
                    continue
                try:
                    score = float((r.get("score") or "").strip())
                except ValueError:
                    problems.append(f"{os.path.basename(path)}:{n}: score not numeric for {rid}")
                    continue
                fp_s = (r.get("fp") or "").strip()
                fp = int(fp_s) if re.fullmatch(r"-?\d+", fp_s) else None
                rows.append({"run_id": rid, "bench": r["bench"].strip(), "family": r["family"].strip(),
                             "score": score, "fp": fp, "file": os.path.basename(path)})
    return rows, problems


def sample_sd(xs):
    if len(xs) < 2:
        return None
    m = sum(xs) / len(xs)
    return math.sqrt(sum((x - m) ** 2 for x in xs) / (len(xs) - 1))


def mde(sd, n_runs):
    """MDE of a gap between two arms of N_CELL runs (two-sided 0.05, power 0.80)."""
    df = n_runs - 1
    if sd is None or df not in T975:
        return None
    return (T975[df] + T80[df]) * sd * math.sqrt(2.0 / N_CELL)


def fmt(x, nd=2):
    return "" if x is None else f"{x:.{nd}f}"


def main(argv):
    panel_dir = argv[1] if len(argv) > 1 and argv[1] else DEFAULT_PANEL
    out_dir = argv[2] if len(argv) > 2 and argv[2] else DEFAULT_OUT
    if not os.path.isdir(panel_dir):
        sys.exit(f"panel dir not found: {panel_dir}")
    os.makedirs(out_dir, exist_ok=True)
    rows, problems = read_batches(panel_dir)

    # per run: family scores
    by_run = {}
    for r in rows:
        by_run.setdefault((r["bench"], r["run_id"]), {})[r["family"]] = r
    runs_out = []
    for (bench, rid), fams in sorted(by_run.items()):
        scores = [fams[f]["score"] for f in FAMILIES if f in fams]
        comb = sum(scores) / len(scores) if scores else None
        fps = [fams[f]["fp"] for f in FAMILIES if f in fams and fams[f]["fp"] is not None]
        runs_out.append({"run_id": rid, "bench": bench,
                         "glm": fams.get("glm", {}).get("score"), "minimax": fams.get("minimax", {}).get("score"),
                         "combined": comb, "fp_combined": (sum(fps) / len(fps)) if fps else None,
                         "families": ",".join(f for f in FAMILIES if f in fams)})

    runs_path = os.path.join(out_dir, "noise-runs.tsv")
    with open(runs_path, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh, delimiter="\t", lineterminator="\n")
        w.writerow(["run_id", "bench", "glm", "minimax", "combined", "fp_combined", "families"])
        for r in runs_out:
            w.writerow([r["run_id"], r["bench"], fmt(r["glm"], 2), fmt(r["minimax"], 2),
                        fmt(r["combined"], 3), fmt(r["fp_combined"], 2), r["families"]])

    # per bench: family and combined stats
    mde_rows = []
    for bench in BENCHES:
        rs = [r for r in runs_out if r["bench"] == bench]
        for scope in FAMILIES + ["combined"]:
            xs = [r[scope] for r in rs if r[scope] is not None]
            n = len(xs)
            sd = sample_sd(xs)
            note = []
            if n < RUNS_PER_BENCH:
                note.append(f"only {n}/{RUNS_PER_BENCH} runs scored (DNF or missing batch): sd/MDE from {n}")
            if n >= 2 and n - 1 not in T975:
                note.append("df outside table: MDE not computed")
            if scope == "combined":
                single = [r["run_id"] for r in rs if r["families"] != ",".join(FAMILIES)]
                if single:
                    note.append(f"{len(single)} run(s) with one family only (combined = that family's score)")
            mde_rows.append({"bench": bench, "scope": scope, "n_runs": n,
                             "mean": (sum(xs) / n) if n else None, "sd": sd,
                             "range_min": min(xs) if n else None, "range_max": max(xs) if n else None,
                             "range": (max(xs) - min(xs)) if n else None,
                             "mde": mde(sd, n) if n >= 2 else None,
                             "note": "; ".join(note)})
    mde_path = os.path.join(out_dir, "noise-mde.tsv")
    with open(mde_path, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh, delimiter="\t", lineterminator="\n")
        w.writerow(["bench", "scope", "n_runs", "mean", "sd", "range_min", "range_max", "range",
                    "mde_n2", "note"])
        for m in mde_rows:
            w.writerow([m["bench"], m["scope"], m["n_runs"], fmt(m["mean"], 3), fmt(m["sd"], 3),
                        fmt(m["range_min"], 2), fmt(m["range_max"], 2), fmt(m["range"], 2),
                        fmt(m["mde"], 2), m["note"]])

    print(f"batch rows read: {len(rows)}; runs: {len(runs_out)}")
    for p in problems:
        print(f"PROBLEM {p}")
    print(f"wrote {runs_path}")
    print(f"wrote {mde_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
