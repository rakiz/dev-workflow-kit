#!/usr/bin/env python3
"""RG4 standings: per-arm table from rg4-run-scores.tsv (fold output) + the 4 arms
already scored on 2026-11-19 (merged from RESULTS.md §7.1; per-run GLM values on
record, haiku arm values NOT on disk -> arm-level only).

Writes evals/2026-11-20/rg4-standings.csv. Arm mean = mean of valid run means.
Spread = max-min over all individual readings of the arm. Divergent = any run with
a family spread >=2, or the two family arm-means differing by >=2.
"""
import csv, os, statistics, sys
HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(os.path.dirname(HERE), "rg4-standings.csv")
RUNS = os.path.join(os.path.dirname(HERE), "rg4-run-scores.tsv")

# existing 2026-11-19 arms (RESULTS.md §7.1): GLM per-run readings, haiku arm value (brief, not on disk)
EXISTING = [
    # model, effort, [(tag, glm)], haiku_arm, panel_mean_published
    ("haiku", "default", [("r41", 11), ("r42", 13)], 11.5, 11.75),
    ("haiku", "high", [("r41", 13), ("r42", 13)], 14, 13.5),
    ("minimax", "xhigh", [("r41b", 14), ("r42", 11)], 13.5, 13.0),
    ("opus", "default", [("r41", 13), ("r42", 13)], 14, 13.5),
]

ARM_ORDER = [("glm", "low"), ("glm", "high"), ("dsflash", "default"), ("1017", "low"), ("1017", "medium"),
             ("1017", "high"), ("minimax", "low"), ("minimax", "medium"), ("qwen", "medium"), ("qwen", "xhigh"),
             ("hydrogen", "high"), ("hydrogen", "medium"), ("argon", "high"), ("carbon", "high"),
             ("gem38", "medium"), ("muse", "medium"), ("kimi", "medium"), ("terra", "medium"), ("sonnet", "high")]


def main():
    rows = list(csv.DictReader(open(RUNS), delimiter="\t"))
    arms = {}
    for r in rows:
        key = (r["model"], r["effort"])
        a = arms.setdefault(key, {"runs": {}, "dnf": []})
        tag = r["tag"]
        if r["status"] == "DNF":
            a["dnf"].append(tag); continue
        g = int(r["glm"]) if r["glm"] else None
        h = int(r["haiku"]) if r["haiku"] else None
        a["runs"][tag] = (g, h)
    out = []
    for m, e in ARM_ORDER:
        a = arms[(m, e)]
        q = {t: a["runs"].get(t) for t in ("q51", "q52")}
        readings, runmeans, divergent_run = [], [], False
        fam = {"glm": [], "haiku": []}
        for t, (g, h) in sorted(a["runs"].items()):
            vals = [v for v in (g, h) if v is not None]
            readings += vals; runmeans.append(statistics.mean(vals))
            if g is not None: fam["glm"].append(g)
            if h is not None: fam["haiku"].append(h)
            if g is not None and h is not None and abs(g - h) >= 2: divergent_run = True
        mean = round(statistics.mean(runmeans), 2) if runmeans else None
        spread = (max(readings) - min(readings)) if len(readings) > 1 else None
        fam_gap = None
        if fam["glm"] and fam["haiku"]:
            fam_gap = round(abs(statistics.mean(fam["glm"]) - statistics.mean(fam["haiku"])), 2)
        div = divergent_run or (fam_gap is not None and fam_gap >= 2)
        nfam = "2 families" if (fam["glm"] and fam["haiku"]) else ("1 family (" + ("glm" if fam["glm"] else "haiku") + " only)" if readings else "none")
        def cell(v, i):
            return "" if v is None or v[i] is None else v[i]
        # "~" suffix = one scorer family only (D6 marker; mirrored in grid2-scores.csv I2-RG4 + the chart label)
        one_fam = not (fam["glm"] and fam["haiku"])
        pm = ("DNF" if mean is None else (f"{mean}~" if one_fam else mean))
        # "*" = single valid run (hollow dot; same convention as grid2-scores.csv)
        if mean is not None and len(runmeans) == 1:
            pm = f"{pm}*"
        out.append(dict(model=m, effort=e, valid_runs=len(runmeans), dnf=";".join(a["dnf"]),
                        q51_glm=cell(q["q51"], 0), q51_haiku=cell(q["q51"], 1),
                        q52_glm=cell(q["q52"], 0), q52_haiku=cell(q["q52"], 1),
                        panel_mean=pm, spread=spread if spread is not None else "",
                        divergent=("yes" if div else "no") if (fam["glm"] and fam["haiku"]) else "n/a (1 family)",
                        families=nfam, source="2026-11-20 RG4 full (q51/q52)" + (" + D1 re-runs (q53/q53b)" if any(t.startswith("q53") for t in a["runs"]) else "")
                        + (" + argon q55/q55b (2026-11-20 closure)" if (m, e) == ("argon", "high") and any(t.startswith("q55") for t in a["runs"]) else "")
                        + (" - I2: 7 DNFs total (watchdog + no-report) at caps up to $2.00/run, economically unmeasurable; ceiling-censored single run" if (m, e) == ("carbon", "high") else "")))
    for m, e, runs, hv, pub in EXISTING:
        readings = [g for _, g in runs] + [hv]
        glm_mean = statistics.mean([g for _, g in runs])
        out.append(dict(model=m, effort=e, valid_runs=len(runs), dnf="",
                        q51_glm=runs[0][1], q51_haiku="arm-only",
                        q52_glm=runs[1][1], q52_haiku="arm-only", panel_mean=pub,
                        spread=max(readings) - min(readings),
                        divergent="no", families="2 families (haiku arm-level, not on disk)",
                        source="2026-11-19 phase 4 (RESULTS §7.1; tags r41/r42 or r41b/r42)"))
    w = csv.DictWriter(open(OUT, "w", newline=""), fieldnames=list(out[0].keys()))
    w.writeheader(); w.writerows(out)
    for o in out:
        print("\t".join(str(o[k]) for k in ["model", "effort", "valid_runs", "q51_glm", "q51_haiku", "q52_glm",
                                             "q52_haiku", "panel_mean", "spread", "divergent", "families", "dnf"]))


if __name__ == "__main__":
    main()
