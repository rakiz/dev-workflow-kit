#!/usr/bin/env python3
"""Aggregate the 2026-11-16 scoring panel into panel-scores.csv.

Sources
  panel/panel-<scorer>-<bench>-<batchN>.log   independent scorer passes (glm,
      1017, minimax); each log ends in the scorer's TSV lines
      (run_id, SCORE, breakdown, flag) - model/harness noise lines around them
      are filtered by shape.
  ../grid2-run-scores.tsv                     pass-1 (haiku) per-run scores.

Mapping
  run_id -> cell (model, effort, bench) via grid2-run-scores.tsv run_ids and
  the artifact naming in runs/ (<BENCH>-<model-slug>-<effort>-<tag>).

Rules
  - Self-family scores are excluded: scorer glm never scores glm/fw-glm-*,
    1017 never scores deepseek-v4p1-flash-1017-*, minimax never scores
    minimax-*, and the haiku pass (grid2-run-scores.tsv) never scores
    claude-* artifacts.
  - Haiku pass values: status=scored rows only (DNF skipped).
  - A run_id seen more than once for the same scorer keeps its LAST value:
    later scorer sessions echo earlier scorers' logs via grep/cat, while the
    genuine score block is always the session's final output.
  - panel_mean = mean of the available independent scores; >= 2 scores is
    official, fewer is flagged unofficial.
  - flag=divergent when panel_spread (max-min) >= 2 for the /8 and /14
    benches (O, D, DR2; I2 is /12 and grouped with them) and >= 1 for IR (/3).
"""

import csv
import re
import sys
from collections import defaultdict
from pathlib import Path

DAY = Path(__file__).resolve().parent / "2026-11-16"
PANEL_DIR = DAY / "panel"
RUNS_DIR = DAY / "runs"
RUN_SCORES_TSV = DAY / "grid2-run-scores.tsv"
OLD_SCORES_CSV = DAY / "grid2-scores.csv"
OUT_CSV = DAY / "panel-scores.csv"

BENCHES = ["O", "IR", "DR2", "I2", "D"]
EFFORTS = ["low", "default", "medium", "high", "xhigh"]
EFFORT_RANK = {e: i for i, e in enumerate(EFFORTS)}
# Divergence threshold by bench: >=2 for /8 (O, D) and /14 (DR2) benches,
# >=1 for /3 (IR). I2 (/12) is grouped with the >=2 bucket.
DIVERGENCE_THRESHOLD = {"O": 2, "D": 2, "DR2": 2, "I2": 2, "IR": 1}

SCORERS = ["haiku", "glm", "sc1017", "minimax", "sonnet"]  # CSV column order
# log-file scorer name -> CSV column
LOG_SCORER_TO_COL = {"glm": "glm", "1017": "sc1017", "minimax": "minimax",
                     "sonnet": "sonnet"}
# scorer column -> family it belongs to (must not score its own family)
SCORER_FAMILY = {"haiku": "claude", "glm": "glm", "sc1017": "1017",
                 "minimax": "minimax", "sonnet": "claude"}

# model-slug (normalized: '_' -> '-') -> canonical model name (grid2-scores.csv)
SLUG_TO_MODEL = {
    "claude-haiku-5-5": "haiku",
    "claude-sonnet-5-5": "sonnet",
    "claude-opus-5-5": "opus",
    "claude-fable-5": "fable",
    "deepseek-v4p1-flash-1017": "1017",
    "fw-deepseek-v4-1-flash": "dsflash",
    "fw-deepseek-v4-pro": "dspro",  # provider-DNF'd model in grid2; panel scored its empty-diff artifacts
    "fw-glm-5-3-flash": "glm",
    "gemini-3-8-flash": "gem38",
    "gemini-4-argon": "argon",
    "gemini-4-carbon": "carbon",
    "gemini-4-hydrogen": "hydrogen",
    "glm": "glm",
    "gpt-6-1-sol": "sol",
    "gpt-6-1-terra": "terra",
    "gpt-6-astra": "astra",
    "haiku": "haiku",
    "hydrogen": "hydrogen",
    "kimi-k3p1-pro": "kimi",
    "minimax-m3p1-flash": "minimax",
    "minimax": "minimax",
    "muse-spark-open": "muse",
    "opus": "opus",
    "qwen": "qwen",
    "qwen3p8-2p4t-a95b": "qwen",
    "sonnet": "sonnet",
    "terra": "terra",
}
CLAUDE_FAMILY = {"haiku", "sonnet", "opus", "fable"}


def norm(s):
    return s.replace("_", "-")


def model_family(model):
    if model in CLAUDE_FAMILY:
        return "claude"
    if model in ("glm", "1017", "minimax"):
        return model
    return model


def load_run_score_tsv():
    """run_id -> (bench, model, effort) for every row with a model;
    plus pass-1 (haiku) scores per cell from status=scored rows."""
    id_map = {}
    haiku_cells = defaultdict(list)
    with open(RUN_SCORES_TSV, encoding="utf-8") as f:
        reader = csv.DictReader(f, delimiter="\t")
        for row in reader:
            run_id = (row.get("run_id") or "").strip()
            model = (row.get("model") or "").strip()
            bench = (row.get("bench") or "").strip()
            effort = (row.get("effort") or "").strip()
            status = (row.get("status") or "").strip()
            score = (row.get("score") or "").strip()
            if not run_id or not model:
                continue
            id_map[norm(run_id)] = (bench, model, effort)
            if status == "scored" and bench in BENCHES:
                if model_family(model) == "claude":
                    continue  # haiku pass never scores claude-* artifacts
                try:
                    haiku_cells[(model, effort, bench)].append(float(score))
                except ValueError:
                    pass
    return id_map, haiku_cells


def load_runs_artifacts():
    """Set of (bench, rest) from runs/ artifact basenames, and the
    (bench, rest) -> (slug, effort) parse of the same."""
    artifacts = set()
    parsed = {}
    for p in RUNS_DIR.iterdir():
        m = re.match(r"^(O|IR|DR2|I2|D)-(.+?)\.(plan|design|report|critique)\.md$|"
                     r"^(O|IR|DR2|I2|D)-(.+?)\.diff$", p.name)
        if not m:
            continue
        bench, rest = (m.group(1), m.group(2)) if m.group(1) else (m.group(4), m.group(5))
        key = (bench, norm(rest))
        artifacts.add(key)
        parts = rest.split("-")
        if len(parts) >= 3 and parts[-2] in EFFORT_RANK:
            parsed[key] = ("-".join(parts[:-2]), parts[-2])
    return artifacts, parsed


RUN_ID_RE = re.compile(r"^(O|IR|DR2|I2|IV2|D)-[A-Za-z0-9][A-Za-z0-9._-]*\t")
SCORE_RE = re.compile(r"^-?\d+(?:\.\d+)?$|^DNF$")
# sonnet IR sessions emit the /3 bench as 'base/3+bonus-FP' (e.g. '2/3+1-1');
# the panel IR convention (values >3 exist in panel-scores.csv) is
# base + bonus - FP. Plain decimals and DNF pass through unchanged.
IR_COMPOSITE_RE = re.compile(r"^(-?\d+(?:\.\d+)?)/(\d+)((?:[+-]\d+(?:\.\d+)?)*)$")


def normalize_score(score):
    if score == "DNF" or SCORE_RE.match(score):
        return score
    m = IR_COMPOSITE_RE.match(score)
    if m:
        total = float(m.group(1))
        for sign, val in re.findall(r"([+-])(\d+(?:\.\d+)?)", m.group(3)):
            total += float(val) if sign == "+" else -float(val)
        return total
    return None


def extract_panel_scores():
    """(scorer, bench, run_id) -> float | 'DNF', last occurrence wins.

    Sonnet arbitration sessions run on a 2x-cap watchdog: a costcap-killed
    session has no trustworthy final block, so its log is renamed
    *-killed.log and excluded here by the filename pattern.
    """
    scores = {}
    for log in sorted(PANEL_DIR.glob("panel-*.log")):
        m = re.match(r"^panel-(glm|1017|minimax|sonnet)-([A-Z0-9]+)-"
                     r"([A-Za-z0-9]+)\.log$", log.name)
        if not m:
            continue
        scorer, bench = m.group(1), m.group(2)
        for line in log.read_text(encoding="utf-8", errors="replace").splitlines():
            if not RUN_ID_RE.match(line):
                continue
            fields = line.split("\t")
            if len(fields) < 3:
                continue
            val = normalize_score(fields[1].strip())
            if val is None:
                continue
            run_id = norm(fields[0].strip())
            scores[(scorer, bench, run_id)] = (
                "DNF" if val == "DNF" else float(val))
    return scores


class Mapper:
    def __init__(self, id_map, artifacts, artifacts_parsed):
        self.id_map = id_map
        self.artifacts = artifacts
        self.artifacts_parsed = artifacts_parsed
        self.warnings = []

    def resolve(self, run_id, where):
        """run_id -> (model, effort, bench) or None (with a warning)."""
        if run_id in self.id_map:
            bench, model, effort = self.id_map[run_id]
            return model, effort, bench
        m = re.match(r"^(O|IR|DR2|I2|D)-(.+)$", run_id)
        if not m:
            return None
        bench, rest = m.group(1), m.group(2)
        if re.search(r"\.(md|diff|review|plan|report|critique)$", rest):
            self.warnings.append(f"skipped artifact-filename line: {run_id} ({where})")
            return None  # artifact-filename junk, not a run_id
        parts = rest.split("-")
        if len(parts) < 3 or parts[-2] not in EFFORT_RANK:
            self.warnings.append(f"unparsed run_id {run_id!r} ({where})")
            return None
        slug = "-".join(parts[:-2])
        effort = parts[-2]
        model = SLUG_TO_MODEL.get(slug)
        if model is None:
            self.warnings.append(f"unknown model slug {slug!r} ({run_id}, {where})")
            return None
        if (bench, rest) not in self.artifacts:
            self.warnings.append(f"run_id not in runs/ artifacts: {run_id} ({where})")
        return model, effort, bench


def fmt(v):
    if v is None:
        return ""
    s = f"{v:.2f}"
    return s.rstrip("0").rstrip(".") if "." in s else s


def write_grid2_official(rows):
    """Fold official panel values into grid2-scores.csv.

    Official cell value = panel mean (self-family scores already excluded at
    ingestion; sonnet counts only where it arbitrated non-claude artifacts).
    The previous single-scorer value is preserved verbatim in the new
    old_single_scorer column. Idempotent: on re-run, old_single_scorer keeps
    its existing value instead of absorbing the panel value. Fail-closed:
    exits non-zero if any official panel cell is missing from grid2-scores.csv
    (reported as panel-only, since grid2 tracks rostered models only).
    """
    col_for_bench = {"O": "O8", "IR": "IR", "DR2": "DR2", "I2": "I2", "D": "D"}
    path = OLD_SCORES_CSV
    with open(path, encoding="utf-8", newline="") as f:
        raw = list(csv.reader(f))
    fieldnames = raw[0]
    # the committed file has unquoted commas inside notes (ragged rows):
    # re-join any overflow fields into the notes column
    notes_i = fieldnames.index("notes")
    grid_rows = []
    for r in raw[1:]:
        if len(r) > len(fieldnames):
            r = r[:notes_i] + [",".join(r[notes_i:])] + r[len(fieldnames):]
        grid_rows.append(dict(zip(fieldnames, r)))
    # one old_*_single_scorer column per bench column: the previous
    # single-scorer value, preserved verbatim (incl. '*' markers)
    for col in col_for_bench.values():
        old_col = "old_%s_single_scorer" % col
        if old_col not in fieldnames:
            fieldnames = fieldnames + [old_col]
            for row in grid_rows:
                row[old_col] = row.get(col, "")

    panel_official = {(r["model"], r["effort"], r["bench"]): r
                      for r in rows if r["n_scores"] >= 2 and r["_mean"] is not None}
    replaced = kept = 0
    panel_only = []
    for row in grid_rows:
        model, effort = row["model"].strip(), row["effort"].strip()
        for bench, col in col_for_bench.items():
            old_col = "old_%s_single_scorer" % col
            old_raw = (row.get(old_col) or (row.get(col) or "")).strip()
            cell = (model, effort, bench)
            if cell in panel_official:
                r = panel_official[cell]
                new = fmt(r["_mean"])
                if (row.get(col) or "").strip() != new:
                    replaced += 1
                else:
                    kept += 1
                row[col] = new
                row[old_col] = old_raw
            elif old_raw not in ("", "not measured", "DNF"):
                # no official panel value: keep the old single-scorer value
                kept += 1
                row[old_col] = old_raw
    # official panel cells with no grid2 row at all
    grid_cells = {(r["model"].strip(), r["effort"].strip(), b)
                  for r in grid_rows for b in col_for_bench}
    for cell in sorted(panel_official):
        if cell not in grid_cells:
            panel_only.append(cell)

    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(grid_rows)
    return replaced, kept, panel_only


def reconcile_grid2_panel(rows):
    """Both directions, fail-closed:
    (1) panel -> grid: every official panel cell value == grid2 bench value;
    (2) grid -> panel: every numeric grid2 bench value == its panel mean, or
        is an unchanged old value (no official panel data for the cell).
    Returns list of failure strings."""
    col_for_bench = {"O": "O8", "IR": "IR", "DR2": "DR2", "I2": "I2", "D": "D"}
    with open(OLD_SCORES_CSV, encoding="utf-8") as f:
        grid = {(r["model"].strip(), r["effort"].strip()): r
                for r in csv.DictReader(f)}
    fails = []
    official = {(r["model"], r["effort"], r["bench"]): r
                for r in rows if r["n_scores"] >= 2 and r["_mean"] is not None}
    # (1) panel -> grid
    for (model, effort, bench), r in sorted(official.items()):
        row = grid.get((model, effort))
        if row is None:
            continue  # panel-only cell (reported by write_grid2_official)
        want, got = fmt(r["_mean"]), (row[col_for_bench[bench]] or "").strip()
        if got != want:
            fails.append(f"panel->grid mismatch {model}/{effort}/{bench}: "
                         f"panel {want} != grid2 {got!r}")
    # (2) grid -> panel
    for (model, effort), row in sorted(grid.items()):
        for bench, col in col_for_bench.items():
            got = (row.get(col) or "").strip()
            if got in ("", "not measured", "DNF"):
                continue
            cell = (model, effort, bench)
            if cell in official:
                want = fmt(official[cell]["_mean"])
                if got != want:
                    fails.append(f"grid->panel mismatch {model}/{effort}/{bench}: "
                                 f"grid2 {got} != panel {want}")
    return fails


def main():
    id_map, haiku_cells = load_run_score_tsv()
    artifacts, artifacts_parsed = load_runs_artifacts()
    mapper = Mapper(id_map, artifacts, artifacts_parsed)
    panel_scores = extract_panel_scores()

    # cell -> scorer column -> list of run scores
    cell_scores = defaultdict(lambda: defaultdict(list))
    dnf_counts = defaultdict(lambda: defaultdict(int))
    # sonnet scores on claude-* artifacts (self-family): recorded, arb-only
    sonnet_arb_only = {}  # cell -> score value (or "DNF")

    # pass-1 haiku values
    for (model, effort, bench), vals in haiku_cells.items():
        cell_scores[(model, effort, bench)]["haiku"].extend(vals)

    # panel scorer values
    for (scorer, bench, run_id), score in sorted(panel_scores.items()):
        col = LOG_SCORER_TO_COL[scorer]
        cell = mapper.resolve(run_id, f"panel-{scorer}-{bench}")
        if cell is None:
            continue
        model, effort, cell_bench = cell
        if cell_bench != bench:
            mapper.warnings.append(
                f"bench mismatch for {run_id}: log={bench} tsv={cell_bench}")
            continue
        if model_family(model) == SCORER_FAMILY[col]:
            if col == "sonnet":
                # sonnet arbitrates claude-* artifacts too, but its score is
                # arb-only: never in the official mean (self-family exclusion)
                sonnet_arb_only[(model, effort, bench)] = score
                continue
            continue  # self-family exclusion
        key = (model, effort, bench)
        if score == "DNF":
            dnf_counts[key][col] += 1
        else:
            cell_scores[key][col].append(score)

    # build CSV rows
    rows = []
    for (model, effort, bench), by_scorer in sorted(
            cell_scores.items(),
            key=lambda kv: (kv[0][2], kv[0][0], EFFORT_RANK.get(kv[0][1], 99))):
        vals = {}
        for col in SCORERS:
            lst = by_scorer.get(col, [])
            vals[col] = sum(lst) / len(lst) if lst else None
        avail = [vals[c] for c in SCORERS if vals[c] is not None]
        panel_mean = sum(avail) / len(avail) if avail else None
        spread = (max(avail) - min(avail)) if len(avail) >= 2 else None
        flags = []
        if len(avail) < 2:
            flags.append("unofficial")
        if spread is not None and spread >= DIVERGENCE_THRESHOLD[bench]:
            flags.append("divergent")
        if (model, effort, bench) in sonnet_arb_only:
            flags.append("arb-only")  # sonnet self-family score, not in mean
        rows.append({
            "model": model, "effort": effort, "bench": bench,
            "haiku_score": fmt(vals["haiku"]),
            "glm_score": fmt(vals["glm"]),
            "sc1017_score": fmt(vals["sc1017"]),
            "minimax_score": fmt(vals["minimax"]),
            "sonnet_score": fmt(vals["sonnet"]),
            "n_scores": len(avail),
            "panel_mean": fmt(panel_mean),
            "panel_spread": fmt(spread),
            "flag": ",".join(flags),
            "_avail": avail, "_mean": panel_mean, "_spread": spread,
        })

    with open(OUT_CSV, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["model", "effort", "bench", "haiku_score", "glm_score",
                         "sc1017_score", "minimax_score", "sonnet_score",
                         "n_scores", "panel_mean", "panel_spread", "flag"])
        for r in rows:
            writer.writerow([r["model"], r["effort"], r["bench"],
                             r["haiku_score"], r["glm_score"],
                             r["sc1017_score"], r["minimax_score"],
                             r["sonnet_score"], r["n_scores"], r["panel_mean"],
                             r["panel_spread"], r["flag"]])

    # ---------------- summary ----------------
    official = [r for r in rows if r["n_scores"] >= 2]
    divergent = [r for r in rows if "divergent" in r["flag"]]
    print(f"panel-scores.csv written: {len(rows)} cells "
          f"({len(official)} official with >=2 independent scores, "
          f"{len(rows) - len(official)} unofficial)")

    # ---------------- fold official values into grid2-scores.csv ----------
    replaced, kept, panel_only = write_grid2_official(rows)
    print(f"\ngrid2-scores.csv updated: {replaced} cells replaced by the "
          f"official panel mean, {kept} kept (no panel change / no official "
          f"panel data)")
    if panel_only:
        print(f"panel-only official cells with no grid2 row ({len(panel_only)}):")
        for c in panel_only:
            print("   ", c)
    fails = reconcile_grid2_panel(rows)
    if fails:
        print(f"FAIL: reconciliation mismatches ({len(fails)}):")
        for x in fails:
            print("   ", x)
        sys.exit(1)
    print("reconciliation panel->grid2 and grid2->panel: clean")
    print(f"\nDivergent cells (spread >= threshold; -> sonnet arbitration): "
          f"{len(divergent)}")
    for r in divergent:
        print(f"  {r['model']}/{r['effort']}/{r['bench']}: "
              f"scores={r['_avail']} spread={fmt(r['_spread'])}")

    # rank-order changes vs old single-scorer grid2-scores.csv
    old = load_old_scores()
    rank_changes = []
    for bench in BENCHES:
        cells = []
        for r in rows:
            if r["bench"] != bench or r["n_scores"] < 2 or r["_mean"] is None:
                continue
            o = old.get((r["model"], r["effort"], bench))
            if o is None:
                continue
            cells.append((r["model"], r["effort"], o, r["_mean"]))
        for idx, (model, effort, o, new) in enumerate(cells):
            old_rank = 1 + sum(1 for c in cells if c[2] > o)
            new_rank = 1 + sum(1 for c in cells if c[3] > new)
            if old_rank != new_rank:
                rank_changes.append((bench, model, effort, o, new, old_rank, new_rank))
    print(f"\nCells where the panel mean CHANGES the rank order vs "
          f"grid2-scores.csv ({len(rank_changes)}):")
    for bench, model, effort, o, new, orank, nrank in rank_changes:
        print(f"  {bench}: {model}/{effort}: old {fmt(o)} (rank {orank}) -> "
              f"panel {fmt(new)} (rank {nrank})")

    # cells the orchestrator flagged as expected margin flips
    print("\nHinted comparisons (old single-scorer -> panel mean):")
    for model, effort, bench in [
        ("haiku", "medium", "O"), ("haiku", "medium", "D"),
        ("1017", "medium", "D"), ("glm", "high", "O"), ("1017", "high", "O"),
        ("minimax", "xhigh", "DR2"), ("sonnet", "high", "I2"),
        ("gpt-6.2-sol", "high", "I2"),
    ]:
        r = next((x for x in rows
                  if (x["model"], x["effort"], x["bench"]) == (model, effort, bench)),
                 None)
        o = old.get((model, effort, bench))
        if r is None and o is None:
            print(f"  {model}/{effort}/{bench}: no data")
        else:
            detail = (f"scores={r['_avail']}" if r else "not scored by panel")
            print(f"  {model}/{effort}/{bench}: old {fmt(o)} -> "
                  f"panel {fmt(r['_mean']) if r else '-'} ({detail})")

    if mapper.warnings:
        print(f"\nWarnings ({len(mapper.warnings)}):")
        for w in sorted(set(mapper.warnings)):
            print(f"  {w}")
    missing_blocks = [f"{s}/{b}" for s in ("glm", "1017", "minimax", "sonnet")
                      for b in BENCHES
                      if not any(k[0] == s and k[1] == b for k in panel_scores)]
    if missing_blocks:
        print(f"Scorer/bench batches with no extracted score lines: "
              f"{', '.join(missing_blocks)}")


def load_old_scores():
    """(model, effort, bench) -> float from grid2-scores.csv single-scorer values."""
    col_for_bench = {"O": "O8", "IR": "IR", "DR2": "DR2", "I2": "I2", "D": "D"}
    out = {}
    with open(OLD_SCORES_CSV, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            model, effort = row["model"].strip(), row["effort"].strip()
            for bench, col in col_for_bench.items():
                raw = (row.get(col) or "").strip()
                m = re.match(r"^(-?\d+(?:\.\d+)?)", raw)
                if m:
                    out[(model, effort, bench)] = float(m.group(1))
    return out


if __name__ == "__main__":
    sys.exit(main())
