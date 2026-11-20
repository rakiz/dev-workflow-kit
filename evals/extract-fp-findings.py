#!/usr/bin/env python3
"""Extract per-run findings and false positives (FP) from the scorer panel logs.

Output: <DAY>/fp-findings.tsv (numeric counts only, no rubric text).
The campaign day is argv[1], else $EVAL_DAY, else 2026-11-16.

Sources (read-only, private repo, NOT copied):
  ../../evals-keys/score-logs/<DAY>/panel/panel-<scorer>-<bench>*.log
  Each scorer log carries one line per scored run: run_id, score, breakdown,
  flag. Status-table echoes (bench column = IR/DR2) are skipped. A line whose
  score field is not a number (or the composite "N/3+bonus-FP") is not a
  reading at all (aggregate-panel.py:155-160 rejects it too).
  *-killed.log files are skipped: a costcap-killed session has no
  trustworthy final block (aggregate-panel.py:176-182).

Official cross-checks (a number is published only if it agrees with them),
all read from <DAY>/:
  grid2-run-scores.tsv   run_id -> bench, model, effort, status
                         (the run -> cell map and the DNF filter: only
                         status=scored runs feed a mean)
  panel-scores.csv       cell -> n_scores, flag (unofficial / arb-only /
                         divergent)
  grid2-scores.csv       cell -> the published (official) cell score

  The cross-check is CELL-level, not per-run: the mean of a cell's counted
  readings' own scores is compared with the published cell score. The ledger's
  per-run score column is NOT compared: it holds the first pass's per-run
  verdict (a scorer that is not among the panel readers - for 42 of the 85
  runs it lies outside the readers' score range), so comparing it would flag
  ordinary scorer disagreement as an error.

Readable layouts (anything else is unreadable and records nothing):
  IR   findings = seeded hits (x/3, or a D1+D2 list) + bonus
       bonus    = the +N after "/3" (e.g. 2/3+1), else the sum of +N tokens
  DR2  findings = categories credited (cats=N, cats=a,b,c, "(N);" ,
       "cat N/10", "N/10 categories", "N+M-K" (minimax: cats+proof-3*FP),
       "Ncat+Nproof-NFP" (glm))
  FP   explicit tokens only: "fp=N" / "fp N" / "FP=N", "-N fp", "N FP",
       "no FP" (= 0), plus the composite "base/3+bonus-FP" score form whose
       "-N" suffix IS the FP count (aggregate-panel.py:155-160; the sonnet
       IR sessions emit it that way). An absent FP mention is NOT zero: it
       stays empty. The two composite DR2 forms are only read when they
       re-compute the line's own score (cats+proof-3*FP == score), so a
       misread form records nothing instead of a wrong number.

Scorer policy (owner ruling 2026-11-20, consistent with aggregate-panel.py):
  - One reading per (run, scorer). Candidates are every readable line of
    every non-killed panel log for that run. The SELECTED reading is:
      1. the candidate from the LATER campaign round (the highest round
         number in the log name) - a re-scoring supersedes the earlier
         round, and the official panel scores (panel-scores.csv) keep the
         last value of a run for the same reason, so a reading taken from
         another round would no longer be comparable with the record;
      2. inside that round, the candidate whose breakdown carries an
         explicit FP token - a reading that states its false positives
         beats one that stays silent;
      3. inside that round, the later line.
    Every DISTINCT candidate is kept as a row; the superseded ones carry
    qual=superseded and never enter a mean (nothing is silently dropped).
  - Self-family readings are kept as rows but counted=no (glm never scores
    glm/fw-glm, 1017 never scores deepseek-v4p1-flash-1017, minimax never
    scores minimax, sonnet never scores claude-*).
  - Readings of runs the ledger does not record as scored are kept as rows
    but counted=no (qual=unscored): a DNF or unknown run feeds no mean.
  - Mean row per run = mean of the counted readings; spread = max - min.
    A mean is shown even when scorers disagree; the spread is kept here.

Cell qualification (why a cell's mean may or may not be published). The mean
row's qual column carries it:
  - official: the cell's panel score has 2+ independent scores
    (panel-scores.csv n_scores >= 2), so the published cell score IS a panel
    mean and the readings belong to it.
  - unofficial: the cell has fewer than 2 independent scores. The published
    cell score is then NOT a panel mean, so the reading is published only
    with an explicit "unofficial" marker, never as an official panel mean.
  - contradicts: the mean of the counted readings' own scores differs from
    the published cell score (grid2-scores.csv) by AT LEAST the bench's
    divergence threshold (IR 1, DR2 2; aggregate-panel.py:26-27,413 - the
    same ">=" rule the panel uses for its divergent flag). The readings then
    claim a different result than the official record and the mean is not
    published at all (findings, FP and score are cleared).
  - none: no counted reading (nothing to publish).
  Reading rows carry their own qual: self (self-family), unofficial (the
  cell is unofficial), superseded (a distinct candidate that lost the
  selection), unscored (the run is not a scored run of the ledger).

Columns: run_id, bench, row_kind (reading|mean), scorer, findings, fp,
  score, counted, qual, n_readers, n_findings, n_fp, score_spread,
  findings_spread, fp_spread, evidence.
  score = the reading's own score, or the mean of the counted readings'
  scores (mean rows) - the number the qualification is checked against.
  score_spread = the readers' score spread on the run (max - min): the
  project's own divergence measure (aggregate-panel.py:409), compared with the
  bench's threshold (IR 1, DR2 2) to mark scorer disagreement.
  evidence = "<log file>:<line>" (reading rows only).
"""

import csv
import os
import re
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_DAY = "2026-11-16"


def pick_day(argv):
    """The campaign day: argv[1], else $EVAL_DAY, else the default day."""
    if len(argv) > 1 and argv[1].strip():
        return argv[1].strip()
    return (os.environ.get("EVAL_DAY") or DEFAULT_DAY).strip() or DEFAULT_DAY


DAY = pick_day(sys.argv)
DAY_DIR = os.path.join(_HERE, DAY)
PANEL = os.path.normpath(os.path.join(_HERE, "..", "..", "evals-keys", "score-logs", DAY, "panel"))
OUT = os.path.join(DAY_DIR, "fp-findings.tsv")
RUNSCORES = os.path.join(DAY_DIR, "grid2-run-scores.tsv")
PANELSCORES = os.path.join(DAY_DIR, "panel-scores.csv")
GRID = os.path.join(DAY_DIR, "grid2-scores.csv")

LOG_RE = re.compile(r"^panel-(glm|minimax|1017|sonnet)-.*\.log$")
KILLED_RE = re.compile(r"-killed\.log$")
RID_RE = re.compile(r"^(IR|DR2)-\S+$")
SUFFIX_RE = re.compile(r"\.(review|report)\.md$")
COLUMNS = ["run_id", "bench", "row_kind", "scorer", "findings", "fp", "score",
           "counted", "qual", "n_readers", "n_findings", "n_fp",
           "score_spread", "findings_spread", "fp_spread", "evidence"]

# the benches' own divergence thresholds (aggregate-panel.py:26-27,413)
DIVERGENCE_THRESHOLD = {"IR": 1, "DR2": 2}
# grid2-scores.csv column per bench
GRID_COL = {"IR": "IR", "DR2": "DR2"}

# scorer -> run-id substrings that scorer must not score (self-family; sonnet is
# claude-family, so haiku/opus/fable runs are self-family for it too)
SELF_FAMILY = {"glm": ("glm",), "1017": ("1017",), "minimax": ("minimax",),
               "sonnet": ("claude", "haiku", "sonnet", "opus", "fable")}

FP_PATTERNS = [
    re.compile(r"\bfp\s*[=:]?\s*(\d+)", re.I),
    re.compile(r"[-\u2212]\s*(\d+)\s*fp\b", re.I),
    re.compile(r"(?<![\w.])(\d+)\s*fp\b", re.I),
]
NO_FP_RE = re.compile(r"\bno\s+fp\b", re.I)
# composite forms: "2/3+1" (score field), "3/3+1b-5fp" (breakdown)
COMPOSITE_RE = re.compile(r"(\d+)\s*/\s*3((?:\s*[+-]\s*\d+[a-z]*)*)")
SCORE_RE = re.compile(r"^-?\d+(?:\.\d+)?$")
# DR2 composite forms: minimax "cats+proof-3*FP", glm "catscat+proofproof-FP"
DR2_SUM_RE = re.compile(r"^(\d+)\+(\d+)-(\d+)$")
DR2_CAT_RE = re.compile(r"^(\d+)cat\+(\d+)proof-(\d+)fp$", re.I)


def log_round(fname):
    """The campaign round of a panel log = the last integer in its name."""
    stem = fname[:-4] if fname.endswith(".log") else fname
    nums = re.findall(r"\d+", stem)
    return int(nums[-1]) if nums else 0


def norm_score(text):
    """A scorer score as a float, or None. Plain decimals pass through; the
    composite "base/denom(+bonus)(-FP)" form is summed (aggregate-panel.py:
    155-160). Anything else is not a score."""
    s = text.strip()
    if not s or s == "DNF":
        return None
    if SCORE_RE.match(s):
        return float(s)
    m = COMPOSITE_RE.fullmatch(s)
    if m:
        total = float(m.group(1))
        for sign, val in re.findall(r"([+-])\s*(\d+(?:\.\d+)?)", m.group(2)):
            total += float(val) if sign == "+" else -float(val)
        return total
    return None


def composite_parts(text):
    """(seeded, bonus, fp) of a composite "N/3+bonus-FP" string; None when the
    string is not composite. The "-N" suffix is the FP count (sonnet's IR
    convention, aggregate-panel.py:155-160)."""
    m = COMPOSITE_RE.search(text)
    if not m:
        return None
    seeded = int(m.group(1))
    bonus = fp = None
    for sign, val, _suf in re.findall(r"([+-])\s*(\d+)([a-z]*)", m.group(2)):
        if sign == "+":
            bonus = int(val)
        else:
            fp = int(val)
    return seeded, bonus, fp


def fp_from(text):
    """FP count from explicit tokens only; None when the text says nothing."""
    for pat in FP_PATTERNS:
        m = pat.search(text)
        if m:
            return int(m.group(1))
    if NO_FP_RE.search(text):
        return 0
    return None


def ir_reading(score_s, breakdown):
    """(findings, fp) of an IR reading: seeded hits + bonus, and the FP count.
    None findings when the seeded count cannot be read."""
    text = " ".join([score_s, breakdown])
    comp = composite_parts(score_s) or composite_parts(breakdown)
    if comp:
        seeded, cbonus, cfp = comp
    else:
        m = re.search(r"(\d)\s*/\s*3", text)
        if m:
            seeded = int(m.group(1))
        else:
            d = re.match(r"\s*((?:D\d+)(?:\s*[+,]\s*D\d+)*)", breakdown)
            if not d:
                return None, None
            seeded = len(set(re.findall(r"D\d+", d.group(1))))
    b = re.search(r"/\s*3\s*\+\s*(\d+)", text)
    if b:
        bonus = int(b.group(1))
    elif comp and comp[1] is not None:
        bonus = comp[1]
    else:
        bonus = sum(int(x) for x in re.findall(r"(?<![\w/])\+\s*(\d+)", breakdown))
    fp = fp_from(text)
    if fp is None and comp:
        fp = comp[2]
    return seeded + bonus, fp


def dr2_reading(score_s, breakdown):
    """(findings, fp) of a DR2 reading: categories credited, and the FP count.
    None findings when no category count can be read. The composite forms are
    only read when they re-compute the line's own score, so a misread form
    records nothing rather than a wrong number."""
    text = " ".join([score_s, breakdown])
    score = norm_score(score_s)
    findings = None
    m = re.search(r"cats=([\d,]+)", text)
    if m:
        g = m.group(1)
        findings = len(g.split(",")) if "," in g else int(g)
    if findings is None:
        m = re.search(r"\((\d+)\);\s*proof", text) or re.search(r"=(\d+);\s*proof", text)
        if m:
            findings = int(m.group(1))
    if findings is None:
        m = re.search(r"\bcat\s+(\d+)/10\b", text)
        if m:
            findings = int(m.group(1))
    if findings is None:
        m = re.search(r"(\d+)/10 categories", text)
        if m:
            findings = int(m.group(1))
    if findings is None:
        # minimax: "cats+proof-3*FP" - the third number is already weighted
        m = DR2_SUM_RE.match(breakdown.strip())
        if m:
            cats, proof, weighted = (int(x) for x in m.groups())
            if score is not None and cats + proof - weighted == score and weighted % 3 == 0:
                return cats, weighted // 3
    if findings is None:
        # glm: "catscat+proofproof-FP" - the FP count is not weighted
        m = DR2_CAT_RE.match(breakdown.strip())
        if m:
            cats, proof, fp = (int(x) for x in m.groups())
            if score is not None and cats + proof - 3 * fp == score:
                findings = cats
                return findings, fp
    return findings, fp_from(text)


def read_log(path, scorer, fname, cands):
    """Every readable reading line of one panel log -> candidates[(run, scorer)]."""
    rnd = log_round(fname)
    with open(path, encoding="utf-8", errors="replace") as fh:
        for lineno, line in enumerate(fh, 1):
            fields = line.rstrip("\n").split("\t")
            if len(fields) < 3:
                continue
            rid = SUFFIX_RE.sub("", fields[0].strip())
            if not RID_RE.match(rid) or fields[1].strip() in ("IR", "DR2"):
                continue
            score_s = fields[1].strip()
            score = norm_score(score_s)
            if score is None:
                continue          # not a score: not a reading (aggregate-panel)
            bench = rid.split("-", 1)[0]
            breakdown = fields[2]
            if bench == "IR":
                findings, fp = ir_reading(score_s, breakdown)
            else:
                findings, fp = dr2_reading(score_s, breakdown)
            if findings is None and fp is None:
                continue
            cands.setdefault((rid, scorer), []).append({
                "run_id": rid, "bench": bench, "scorer": scorer,
                "findings": findings, "fp": fp, "score": score,
                "has_fp": fp is not None, "round": rnd, "line": lineno,
                "evidence": f"{fname}:{lineno}"})


def select(cands):
    """The selected reading of one (run, scorer) + the superseded ones.
    Rule (stated in the docstring): the later campaign round, then the
    explicit FP token inside that round, then the later line. Nothing is
    dropped: every distinct candidate is kept."""
    seen, distinct = {}, []
    for c in sorted(cands, key=lambda c: (c["round"], c["line"])):
        sig = (c["findings"], c["fp"], c["score"])
        if sig in seen:
            seen[sig]["evidence"] = c["evidence"]   # latest statement wins
            seen[sig]["round"], seen[sig]["line"] = c["round"], c["line"]
            continue
        seen[sig] = c
        distinct.append(c)
    latest = max(c["round"] for c in distinct)
    pool = [c for c in distinct if c["round"] == latest]
    best = max(pool, key=lambda c: (c["has_fp"], c["line"]))
    return best, [c for c in distinct if c is not best]


def fmt(x):
    return "" if x is None else (str(x) if isinstance(x, int) else f"{x:.2f}")


def load_official():
    """(run_id -> row), (cell -> n_scores/flag), (cell -> published score)."""
    runs = {}
    with open(RUNSCORES, encoding="utf-8", newline="") as fh:
        for r in csv.DictReader(fh, delimiter="\t"):
            runs[r["run_id"].strip()] = r
    panel = {}
    with open(PANELSCORES, encoding="utf-8", newline="") as fh:
        for r in csv.DictReader(fh):
            panel[(r["model"].strip(), r["effort"].strip(), r["bench"].strip())] = r
    published = {}
    with open(GRID, encoding="utf-8", newline="") as fh:
        for r in csv.DictReader(fh):
            model, eff = r["model"].strip(), r["effort"].strip()
            for bench, col in GRID_COL.items():
                v = (r.get(col) or "").strip().rstrip("*~")
                try:
                    published[(model, eff, bench)] = float(v)
                except ValueError:
                    pass
    return runs, panel, published


def mean_row(run_id, bench, recs):
    """The run's mean over the counted readings + its qualification."""
    counted = [r for r in recs if r["counted"] == "yes"]
    f = [r["findings"] for r in counted if r["findings"] is not None]
    p = [r["fp"] for r in counted if r["fp"] is not None]
    s = [r["score"] for r in counted if r["score"] is not None]
    scorers = "+".join(sorted({r["scorer"] for r in counted}))
    return {"run_id": run_id, "bench": bench, "row_kind": "mean",
            "scorer": scorers or "none",
            "findings": fmt(sum(f) / len(f)) if f else "",
            "fp": fmt(sum(p) / len(p)) if p else "",
            "score": fmt(sum(s) / len(s)) if s else "",
            "counted": "", "qual": "", "n_readers": len(counted),
            "n_findings": len(f), "n_fp": len(p),
            "score_spread": (max(s) - min(s)) if s else "",
            "findings_spread": (max(f) - min(f)) if f else "",
            "fp_spread": (max(p) - min(p)) if p else "", "evidence": ""}


def main():
    if not os.path.isdir(DAY_DIR):
        sys.exit(f"campaign day dir not found: {DAY_DIR} (day {DAY})")
    for path in (RUNSCORES, PANELSCORES, GRID):
        if not os.path.exists(path):
            sys.exit(f"missing {os.path.basename(path)} in {DAY_DIR} (day {DAY})")
    if not os.path.isdir(PANEL):
        sys.exit(f"private panel dir not found: {PANEL}")
    runs, panel, published = load_official()

    cands = {}
    for fname in sorted(os.listdir(PANEL)):
        m = LOG_RE.match(fname)
        if not m or KILLED_RE.search(fname):
            continue
        read_log(os.path.join(PANEL, fname), m.group(1), fname, cands)

    # ---- readings: one selected per (run, scorer), the rest superseded
    readings = []
    for (rid, scorer), cl in sorted(cands.items()):
        bench = rid.split("-", 1)[0]
        best, others = select(cl)
        run = runs.get(rid)
        self_family = any(t in rid for t in SELF_FAMILY[scorer])
        cell = None
        if run is not None and run.get("model"):
            cell = (run["model"].strip(), run["effort"].strip(), bench)
        unofficial = bool(cell and int(panel.get(cell, {}).get("n_scores") or 0) < 2)
        unscored = run is None or run.get("status") != "scored"
        for c, superseded in [(best, False)] + [(o, True) for o in others]:
            qual = []
            if self_family:
                qual.append("self")
            if unofficial:
                qual.append("unofficial")
            if superseded:
                qual.append("superseded")
            if unscored:
                qual.append("unscored")
            counted = not (self_family or superseded or unscored)
            readings.append({"run_id": rid, "bench": bench, "scorer": scorer,
                             "findings": c["findings"], "fp": c["fp"],
                             "score": c["score"], "counted": "yes" if counted else "no",
                             "qual": ",".join(qual), "evidence": c["evidence"]})

    by_run = {}
    for rec in readings:
        by_run.setdefault(rec["run_id"], []).append(rec)
    means = []
    for run_id in sorted(by_run):
        recs = sorted(by_run[run_id], key=lambda r: r["scorer"])
        means.append(mean_row(run_id, recs[0]["bench"], recs))

    # ---- cell qualification: unofficial / contradicts the published score
    by_cell = {}
    for m in means:
        run = runs.get(m["run_id"])
        if run is None or not run.get("model"):
            continue
        cell = (run["model"].strip(), run["effort"].strip(), m["bench"])
        by_cell.setdefault(cell, []).append(m)
    for cell, ms in sorted(by_cell.items()):
        model, eff, bench = cell
        n_scores = int(panel.get(cell, {}).get("n_scores") or 0)
        pub = published.get(cell)
        thr = DIVERGENCE_THRESHOLD[bench]
        for m in ms:
            m["qual"] = "unofficial" if n_scores < 2 else "official"
        # the readings' own mean score vs the published cell score
        scores = [float(m["score"]) for m in ms if m["score"]]
        if pub is not None and scores:
            mean_score = sum(scores) / len(scores)
            if abs(mean_score - pub) >= thr:      # same ">=" rule as the panel
                for m in ms:
                    m["qual"] = "contradicts"
                    m["findings"] = m["fp"] = m["score"] = ""
                    m["score_spread"] = m["findings_spread"] = m["fp_spread"] = ""

    # ---- rows: readings first (per run), then the run's mean
    rows = []
    for run_id in sorted(by_run):
        recs = sorted(by_run[run_id], key=lambda r: (r["scorer"], r["qual"] != "", r["evidence"]))
        bench = recs[0]["bench"]
        for r in recs:
            rows.append({"run_id": r["run_id"], "bench": bench, "row_kind": "reading",
                         "scorer": r["scorer"], "findings": fmt(r["findings"]),
                         "fp": fmt(r["fp"]), "score": fmt(r["score"]),
                         "counted": r["counted"], "qual": r["qual"],
                         "n_readers": "", "n_findings": "", "n_fp": "",
                         "score_spread": "", "findings_spread": "", "fp_spread": "",
                         "evidence": r["evidence"]})
    rows.extend(means)

    with open(OUT, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=COLUMNS, delimiter="\t", lineterminator="\n")
        w.writeheader()
        w.writerows(rows)

    live = [m for m in means if m["qual"] in ("official", "unofficial")]
    print(f"runs with readings: {len(means)}")
    print(f"  published (official):  {sum(1 for m in means if m['qual'] == 'official')}")
    print(f"  published (unofficial):{sum(1 for m in means if m['qual'] == 'unofficial')}")
    print(f"  withheld (contradicts):{sum(1 for m in means if m['qual'] == 'contradicts')}")
    print(f"  withheld (none):        {sum(1 for m in means if m['qual'] == 'none')}")
    print(f"  findings resolved: {sum(1 for m in live if m['findings'])}")
    print(f"  FP resolved:       {sum(1 for m in live if m['fp'])}")
    print(f"  runs whose readers disagree beyond the bench threshold: "
          f"{sum(1 for m in live if float(m['score_spread'] or 0) >= DIVERGENCE_THRESHOLD[m['bench']])}")
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
