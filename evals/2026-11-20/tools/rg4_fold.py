#!/usr/bin/env python3
"""RG4 fold: deterministic layer (rg4-deterministic.tsv) + 2-family judgment TSVs
(evals-keys/score-logs/2026-11-20/panel/*-batch-*.tsv) -> per-run totals per
RUBRIC-IV2-RG4 v1 formula, and the per-arm standings CSV.

Formula (RUBRIC-IV2-RG4 §0): suite_green(0/2) + [a,b,d: fix(0/1)+test(0/1)]
+ [c': fix(0/1/2)+test(0/1)+quoted(0/1, only if fix>=1)] + ambiguity(0/1)
+ baseline(0/1) - 3*FP, floor 0.  Reachable max 14.
"""
import csv, glob, os, re, statistics, sys

HERE = os.path.dirname(os.path.abspath(__file__))
EVALS = os.path.dirname(HERE)  # tools/ -> evals/2026-11-20
PANEL = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(EVALS))),
                     "evals-keys", "score-logs", "2026-11-20", "panel")
DET = os.path.join(EVALS, "rg4-deterministic.tsv")

DNF = {  # runs with no scoreable deliverable (PROTOCOL §2.2): not scored, re-run owed
    "IV4-fireworks-ai-accounts-fireworks-models-qwen3p8-2p4t-a95b-xhigh-q51": "no-report marker (no final-report.md)",
    "IV4-fireworks-ai-accounts-fireworks-models-qwen3p8-2p4t-a95b-xhigh-q52": "no-report marker (no final-report.md)",
    "IV4-github-copilot-gemini-4-argon-high-q52": "cost-cap kill (2x cap $0.30) - no final report",
    "IV4-github-copilot-gemini-4-carbon-high-q52": "15-min watchdog timeout - no final report",
}

# run-name -> (model, effort) as used in grid2-scores.csv
ARM_RE = [
    (r"fw-glm-5-3-flash-(low|high)", lambda m: ("glm", m.group(1))),
    (r"fw-deepseek-v4-1-flash", lambda m: ("dsflash", "default")),
    (r"deepseek-v4p1-flash-1017-(low|medium|high)", lambda m: ("1017", m.group(1))),
    (r"minimax-m3p1-flash-(low|medium|xhigh)", lambda m: ("minimax", m.group(1))),
    (r"muse-spark-open-(medium|high)", lambda m: ("muse", m.group(1))),
    (r"kimi-k3p1-pro-(medium|high)", lambda m: ("kimi", m.group(1))),
    (r"qwen3p8-2p4t-a95b-(medium|xhigh)", lambda m: ("qwen", m.group(1))),
    (r"claude-sonnet-5-5-(high|medium)", lambda m: ("sonnet", m.group(1))),
    (r"gemini-3-8-flash-(low|medium|high)", lambda m: ("gem38", m.group(1))),
    (r"gemini-4-argon-(low|medium|high)", lambda m: ("argon", m.group(1))),
    (r"gemini-4-carbon-(low|medium|high)", lambda m: ("carbon", m.group(1))),
    (r"gemini-4-hydrogen-(low|medium|high|xhigh)", lambda m: ("hydrogen", m.group(1))),
    (r"gpt-6-1-terra-(low|medium|high|xhigh)", lambda m: ("terra", m.group(1))),
]


def arm_of(run):
    for pat, f in ARM_RE:
        m = re.search(pat, run)
        if m:
            return f(m)
    raise SystemExit("UNMAPPED RUN " + run)


def det_points(row):
    """Executed-probe points (no judgment). Returns dict of the deterministic fields."""
    suite_green = row["suite"] == "green"
    a_fix = row["probe_a_distinct"] == "3"
    b_fix = row["probe_b"] == "IDENTICAL" and row["probe_b_gen_from"] == "1"
    opens = row["probe_c_rules_opens"]
    c_fix = {"1": 2, "2": 1}.get(opens, 0)
    d_fix = row["probe_d_exit"] == "1" and row["probe_d_state"] == "INTACT"
    return dict(suite=2 if suite_green else 0, a_fix=int(a_fix), b_fix=int(b_fix),
                c_fix=c_fix, d_fix=int(d_fix))


def load_panel():
    out = {}
    for f in sorted(glob.glob(os.path.join(PANEL, "*-batch-*.tsv"))):
        fam = "glm" if os.path.basename(f).startswith("glm") else "haiku"
        with open(f) as fh:
            for r in csv.DictReader(fh, delimiter="\t"):
                key = r["run_dir"]
                for k in ("test_a", "test_b", "test_c", "c_quoted", "test_d", "ambiguity", "baseline"):
                    if r[k] not in ("0", "1"):
                        raise SystemExit(f"{f}: {key} {k}={r[k]!r} not 0/1")
                if not r["FP"].isdigit():
                    raise SystemExit(f"{f}: {key} FP={r['FP']!r} not int")
                out.setdefault(key, {})[fam] = r
    return out


def total(det, j):
    t = det["suite"]
    t += det["a_fix"] + int(j["test_a"]) + det["b_fix"] + int(j["test_b"])
    t += det["d_fix"] + int(j["test_d"])
    t += det["c_fix"] + int(j["test_c"]) + (int(j["c_quoted"]) if det["c_fix"] >= 1 else 0)
    t += int(j["ambiguity"]) + int(j["baseline"]) - 3 * int(j["FP"])
    return max(0, t)


def main():
    det_rows = list(csv.DictReader(open(DET), delimiter="\t"))
    panel = load_panel()
    runs = []
    for row in det_rows:
        run = row["run_dir"]
        model, effort = arm_of(run)
        q = re.search(r"-(q5\d[a-z]?)$", run).group(1)  # q51/q52 (full pilot) + q53/q53b (D1 re-runs)
        rec = dict(run=run, model=model, effort=effort, tag=q)
        if run in DNF:
            rec.update(status="DNF", reason=DNF[run], glm="", haiku="", mean="", spread="", divergent="")
            runs.append(rec); continue
        det = det_points(row)
        readings = {}
        for fam in ("glm", "haiku"):
            j = panel.get(run, {}).get(fam)
            if j is not None:
                readings[fam] = total(det, j)
        # self-family exclusion: glm never scores fw-glm-* runs; haiku never scores claude-* runs
        rec.update(status="scored", det=det,
                   glm=readings.get("glm", ""), haiku=readings.get("haiku", ""))
        vals = list(readings.values())
        rec["mean"] = round(statistics.mean(vals), 2) if vals else ""
        rec["spread"] = (max(vals) - min(vals)) if len(vals) > 1 else ""
        rec["n_readings"] = len(vals)
        rec["divergent"] = "yes" if len(vals) > 1 and rec["spread"] >= 2 else ("no" if len(vals) > 1 else "single")
        rec["fp"] = {f: panel[run][f]["FP"] for f in panel.get(run, {})}
        runs.append(rec)
    return runs


if __name__ == "__main__":
    runs = main()
    w = csv.writer(sys.stdout, delimiter="\t")
    w.writerow(["run", "model", "effort", "tag", "status", "glm", "haiku", "mean", "spread", "n_readings", "divergent", "reason"])
    for r in runs:
        w.writerow([r["run"], r["model"], r["effort"], r["tag"], r["status"], r.get("glm", ""), r.get("haiku", ""),
                    r.get("mean", ""), r.get("spread", ""), r.get("n_readings", ""), r.get("divergent", ""), r.get("reason", "")])
