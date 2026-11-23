import csv, html, math, os, re
from reasons import REASONS

_HERE = os.path.dirname(os.path.abspath(__file__))
PATH = os.path.join(_HERE, "LEADERBOARD.html")
CSVPATH = os.path.join(_HERE, "2026-11-16", "grid2-scores.csv")  # I2-RG4 + DR-v3 + H4-folded D columns (Etape 1 phase 4)

W, H = 1200, 540
L, R, T, B = 80, 60, 30, 60
X0, X1 = 0.0005, 5.0   # log range in USD (mai-flash sits at ~$0.001/task, fable/astra at ~$4)
Y1 = 0.0

# provider-prefixed model ids for the tooltips (keys = CSV model field)
FULLIDS = {
    "opus": "github-copilot/claude-opus-5.5",
    "sonnet": "github-copilot/claude-sonnet-5.5",
    "haiku": "github-copilot/claude-haiku-5.5",
    "fable": "github-copilot/claude-fable-5",
    "terra": "github-copilot/gpt-6.1-terra",
    "sol": "github-copilot/gpt-6.1-sol",
    "gpt-6.2-sol": "github-copilot/gpt-6.2-sol",
    "astra": "github-copilot/gpt-6-astra",
    "argon": "github-copilot/gemini-4-argon",
    "carbon": "github-copilot/gemini-4-carbon",
    "hydrogen": "github-copilot/gemini-4-hydrogen",
    "gem38": "github-copilot/gemini-3.8-flash",
    "glm": "ai-gateway-misc/fw-glm-5.3-flash",
    "dsflash": "ai-gateway-misc/fw-deepseek-v4.1-flash",
    "1017": "fireworks-ai/accounts/fireworks/models/deepseek-v4p1-flash-1017",
    "minimax": "fireworks-ai/accounts/fireworks/models/minimax-m3p1-flash",
    "qwen": "fireworks-ai/accounts/fireworks/models/qwen3p8-2p4t-a95b",
    "muse": "fireworks-ai/accounts/fireworks/models/muse-spark-open",
    "kimi": "fireworks-ai/accounts/fireworks/models/kimi-k3p1-pro",
    "mai-code-2": "github-copilot/mai-code-2",
    "mai-code-2-flash": "github-copilot/mai-code-2-flash",
}

# roster final seat map: (CSV model, effort) -> [(seat name, deciding bench code)].
# Source of truth: models.json "global" + the roster's "Decided on" citations.
# glm-low left review (documented fallback reviewer for deepseek/gemini-produced
# work); hydrogen-high holds no seat.
SEATS = {
    ("glm", "max"): [("orchestration", "O")],
    ("haiku", "default"): [("cheap-code", "I2-RG4")],
    ("haiku", "medium"): [("cheap-design", "D")],
    ("haiku", "high"): [("strong-code-alternative", "I2-RG4")],
    ("dsflash", "default"): [("cheap-mech", "I2-RG4"), ("explore", "I2-RG4")],
    ("minimax", "medium"): [("cheap-design-review", "DR-v2")],
    ("minimax", "xhigh"): [("cheap-review", "IR"), ("strong-design-review", "DR-v2"), ("strong-code", "I2-RG4")],
    ("opus", "default"): [("deep", "I2-RG4"), ("strong-code-alternative2", "I2-RG4"), ("strong-design-alternative2", "D")],
    ("sonnet", "medium"): [("strong-review", "IR")],
    ("sonnet", "high"): [("strong-design-alternative", "D")],
    ("qwen", "xhigh"): [("strong-review-alternative2", "IR")],
    ("1017", "high"): [("strong-design", "D"), ("strong-review-alternative", "IR")],
    ("argon", "high"): [("strong-design-review-alternative", "DR-v2")],
}

# bench charts: (REASONS key, title, y-max, CSV column, y-axis label, ref line)
BENCHES = [
    ("Orchestration",
     "Orchestration (O, /8): sonnet-high plans best (8); glm-max holds the seat on price (7.33 n=3, stability x3 confirmed, at $0.007 - 20x cheaper than the top scorers)",
     8, "O8", "score on this bench", None, "O"),
    ("Design writing",
     "Design writing (D, /11): 1017-high best (9.81 at $0.12), opus 9.58 at 12x the cost; glm and gem38 cannot write designs",
     11, "D", "score on this bench", None, "D"),
    ("Design review",
     "Design review (DR-v2, /14): minimax-xhigh posts 11.25 with 4 executed proofs and takes the strong rung; opus scores 0 (2 FPs)",
     14, "DR2", "score on this bench", None, "DR-v2"),
    ("Implementation",
     "Implementation (I-v2 RG4 full set, /14; tie rule: gaps under the 1.5 MDE are ties and the cheaper model wins): carbon-high 14 (2 runs) leads; qwen-medium, haiku-high, opus 13.5; minimax-xhigh 13.0 at $0.03",
     14, "I2-RG4", "score on this bench", None, "I2-RG4"),
    ("Code review",
     "Code review (IR, /3+bonus): the 3 seeded defects stop separating at 3 - the bonus axis ranks the top crowd (3.0-4.35); the bottom cluster (2.0-2.5) misses a seeded defect",
     5, "IR", "IR /3 seeded (+bonus up to +2)", (3, "seeded ceiling"), "IR"),
]


RUNOPS = os.path.join(_HERE, "2026-11-16", "run-ops.tsv")  # build-ops.py output (keyed DB + TSV)
GRID_FROM = "2026-11-16"   # costs come from the same campaign as the scores
COLBENCH = {"O8": "O", "IR": "IR", "DR2": "DR2", "I2-RG4": "I2-RG4", "D": "D"}  # CSV column -> run-ops bench


def _load_ops():
    """Per-run ops from run-ops.tsv: bench-specific cost, delivery, latency."""
    cells, model_ops = {}, {}
    for r in csv.DictReader(open(RUNOPS), delimiter="\t"):
        if r["date"] < GRID_FROM:
            continue
        bench, model, eff = r["bench"], r["model"], r["effort"]
        deliv = r["delivered"] == "1"
        cost = float(r["cost_usd"])
        dur = float(r["duration_s"]) if r["duration_s"] else None
        c = cells.setdefault((bench, model, eff), {"n": 0, "d": 0, "tot": 0.0, "valid": [], "dur": [], "tok": []})
        c["n"] += 1; c["tot"] += cost
        m = model_ops.setdefault((model, eff), {"n": 0, "d": 0, "dur": [], "tot": 0.0})
        m["n"] += 1; m["tot"] += cost
        if deliv:
            c["d"] += 1; c["valid"].append(cost)
            if dur is not None:
                c["dur"].append(dur)
            if r.get("tok_total"):
                c["tok"].append({k: float(r["tok_" + k]) for k in ("input", "cache_read", "output", "reasoning", "total")})
            m["d"] += 1
            if dur is not None:
                m["dur"].append(dur)
    return cells, model_ops


CELLS, MODEL_OPS = _load_ops()


def cell_info(bench, model, eff):
    """Bench-specific cost = mean over DELIVERED runs; incl = all spend / delivered."""
    c = CELLS.get((bench, model, eff))
    if not c or not c["valid"]:
        return None
    return {"cost": sum(c["valid"]) / len(c["valid"]), "n": c["n"], "d": c["d"],
            "incl": c["tot"] / c["d"]}


def cell_dur(bench, model, eff):
    """Bench-specific latency of DELIVERED runs: median and range (seconds), or None."""
    c = CELLS.get((bench, model, eff))
    if not c or not c["dur"]:
        return None
    d = sorted(c["dur"])
    med = d[len(d) // 2] if len(d) % 2 else (d[len(d) // 2 - 1] + d[len(d) // 2]) / 2
    return {"med": med, "lo": d[0], "hi": d[-1], "n": len(d)}


def cell_tokens(bench, model, eff):
    """Mean tokens per delivered run (runs with token data), or None."""
    c = CELLS.get((bench, model, eff))
    if not c or not c["tok"]:
        return None
    n = len(c["tok"])
    out = {k: sum(t[k] for t in c["tok"]) / n for k in ("input", "cache_read", "output", "reasoning", "total")}
    out["n"] = n
    return out


def fmt_lat(sec):
    """Seconds below two minutes, minutes above (one unit per tooltip)."""
    return f"{sec:.0f}s" if sec < 120 else f"{sec / 60:.0f} min"


def latency_text(dur):
    if dur is None:
        return "~? (no timing)"
    unit = (lambda v: f"{v:.0f}s") if dur["med"] < 120 else (lambda v: f"{v / 60:.0f} min")
    txt = f"~{unit(dur['med'])} on this bench"
    if dur["n"] > 1 and (dur["lo"] != dur["hi"]):
        txt += f" ({unit(dur['lo'])}–{unit(dur['hi'])})"
    return txt


def ops_for(model, eff):
    """Delivery + latency across ALL benches for one model x effort."""
    m = MODEL_OPS.get((model, eff))
    if not m:
        return None
    dur = m["dur"]
    return {"n": m["n"], "d": m["d"], "tot": m["tot"],
            "dur_mean": sum(dur) / len(dur) if dur else None,
            "dur_min": min(dur) if dur else None, "dur_max": max(dur) if dur else None}


def parse_fp(note, bench):
    """FP count only where the note states it for this bench (else None = net only)."""
    tag = {"IR": "IR", "DR2": "DR2"}.get(bench)
    if not tag:
        return None
    m = re.search(tag + r"[^;]*?(\d+)\s*FP", note)
    return int(m.group(1)) if m else None


FF_PATH = os.path.join(_HERE, "2026-11-16", "fp-findings.tsv")     # extract-fp-findings.py output
RUNSCORES = os.path.join(_HERE, "2026-11-16", "grid2-run-scores.tsv")

# The project's divergence thresholds (aggregate-panel.py:26-27,413): a reader
# spread of at least 1 point on IR, 2 on DR2, is scorer disagreement.
DIVERGENCE_THRESHOLD = {"IR": 1, "DR2": 2}
# The scale the findings are counted on, per bench.
FINDINGS_DENOM = {"IR": "of 3 seeded + bonus", "DR2": "of 10 categories"}


def _load_findings():
    """Cell-level findings and FP for IR/DR2: the mean over the cell's scored runs
    of each run's panel mean (fp-findings.tsv mean rows). `disagree` counts the
    runs whose readers spread beyond the bench's divergence threshold (kept
    visible, never hidden).

    The TSV is a generated file: when it is absent the charts fall back to the
    note-derived FP alone (no crash). Mean rows the extractor withheld (a
    reading that contradicts the official record) are never published."""
    run_cell = {}
    for r in csv.DictReader(open(RUNSCORES), delimiter="\t"):
        if r["status"] == "scored" and r["bench"] in ("IR", "DR2"):
            run_cell[r["run_id"]] = (r["bench"], r["model"], r["effort"])
    try:
        fh = open(FF_PATH, encoding="utf-8", newline="")
    except FileNotFoundError:
        return {}
    acc = {}
    with fh:
        for r in csv.DictReader(fh, delimiter="\t"):
            if r["row_kind"] != "mean" or r["run_id"] not in run_cell:
                continue
            if r.get("qual") in ("contradicts", "none"):
                continue          # withheld by the extractor: not published
            cell = run_cell[r["run_id"]]
            c = acc.setdefault(cell, {"f": [], "p": [], "runs": 0, "disagree": 0,
                                      "readers": 0, "fp_readers": 0, "qual": ""})
            c["runs"] += 1
            c["readers"] += int(r.get("n_readers") or 0)
            c["fp_readers"] += int(r.get("n_fp") or 0)
            c["qual"] = r.get("qual") or c["qual"]
            if r["findings"]:
                c["f"].append(float(r["findings"]))
            if r["fp"]:
                c["p"].append(float(r["fp"]))
            # the readers' score spread, compared with the bench's own
            # divergence threshold (the project's measure, aggregate-panel.py)
            if float(r.get("score_spread") or 0) >= DIVERGENCE_THRESHOLD[cell[0]]:
                c["disagree"] += 1
    out = {}
    for k, c in acc.items():
        out[k] = {"findings": sum(c["f"]) / len(c["f"]) if c["f"] else None,
                  "fp": sum(c["p"]) / len(c["p"]) if c["p"] else None,
                  "runs": c["runs"], "disagree": c["disagree"],
                  "readers": c["readers"], "fp_readers": c["fp_readers"],
                  "qual": c["qual"]}
    return out


def fp_txt(fp, fp_src):
    """An FP count as published: the official record states a whole number, the
    panel mean is a mean of counts (one decimal)."""
    return f"{fp}" if fp_src else f"{fp:.1f}"


def ff_line(meta, bench):
    """The IR/DR2 tooltip line: findings and false positives, each with its
    denominator and its reader count.

    The official record (the FP the CSV note states) always wins over the panel
    FP: a panel FP lower than the official one is never published. The panel
    FP is only shown when the official record states none."""
    ff = meta.get("ff")
    official_fp = meta.get("fp")          # note-derived: the established record
    panel_fp = ff["fp"] if ff else None
    bench = meta.get("bench", bench)      # the data bench (IR/DR2), not the seat code
    denom = FINDINGS_DENOM.get(bench, "")
    findings = ff["findings"] if ff else None
    if official_fp is not None:
        fp, fp_readers, readers = official_fp, "", ""
        fp_src = "official record"
    elif panel_fp is not None:
        fp, fp_readers, readers = panel_fp, ff["fp_readers"], ff["readers"]
        fp_src = ""
    else:
        fp, fp_readers, readers, fp_src = None, "", "", ""
    if findings is not None and fp is not None:
        line = f'findings {findings:.1f} ({denom}) · FP {fp_txt(fp, fp_src)}'
        if fp_src:
            line += f' ({fp_src})'
        elif readers:
            line += f' ({fp_readers}/{readers} readers)'
        if ff and ff["qual"] == "unofficial":
            line += " · unofficial panel (1 scorer)"
        if ff and ff["disagree"]:
            line += f' · scorers disagree on {ff["disagree"]} run(s)'
    elif findings is not None:
        line = f'findings {findings:.1f} ({denom}) · FP not readable per run'
    elif fp is not None:
        line = f'FP {fp_txt(fp, fp_src)}'
        if fp_src:
            line += f' ({fp_src})'
        elif readers:
            line += f' ({fp_readers}/{readers} readers)'
        line += " · findings not recorded per run"
    elif bench in ("IR", "DR2"):
        line = "net score (FP not recorded per run)"
    else:
        line = ""
    return line


CELL_FF = _load_findings()


def parse_cost(c):
    c = c.strip().lstrip("~").strip()
    if not c:
        return None
    if "-" in c:
        a, _, b = c.partition("-")
        try:
            return (float(a) + float(b)) / 2
        except ValueError:
            return None
    try:
        return float(c)
    except ValueError:
        return None


def load_dots(column):
    """One dot per CSV row whose cell in `column` is numeric (a trailing *
    marks a single-valid run). not measured / DNF / cat * render no dot.
    X = bench-specific cost (mean over delivered runs of THAT bench); the CSV
    generic estimate is the labelled fallback."""
    bench = COLBENCH[column]
    pts = []
    for r in csv.DictReader(open(CSVPATH)):
        v = r[column].strip()
        try:
            s = float(v.rstrip("*~"))
        except ValueError:
            continue
        model, eff = r["model"].strip(), r["effort"].strip()
        info = cell_info(bench, model, eff)
        if info:
            cost, cost_src = info["cost"], "bench"
        else:
            cost = parse_cost(r["cost_per_task_est"])
            if cost is None:
                continue
            cost_src = "generic"
        name = model if eff == "default" else f"{model}-{eff}"
        note = r["notes"].strip().lstrip("-").strip()
        # hollow = under-measured: CSV star OR the row's notes say single / 1 valid
        single = v.endswith("*") or bool(re.search(r"\bsingle\b|1 valid|\b1v\b", note, re.I))
        # one_fam = trailing "~": the cell's runs were scored by one scorer family only
        one_fam = v.endswith("~")
        meta = {"bench": bench, "cost_src": cost_src, "info": info,
                "dur": cell_dur(bench, model, eff),
                "ops": ops_for(model, eff), "fp": parse_fp(note, bench),
                "ff": CELL_FF.get((bench, model, eff))}
        # meta["fp"] stays the OFFICIAL record (the FP the CSV note states);
        # the panel FP never overrides it (see ff_line).
        pts.append((name, s, cost, SEATS.get((model, eff), []), single, note, one_fam, meta))
    return pts


def xpos(c):
    lo, hi = math.log10(X0), math.log10(X1)
    return L + (math.log10(c) - lo) / (hi - lo) * (W - L - R)


def ypos(s, ymax):
    return T + (1 - (s - Y1) / (ymax - Y1)) * (H - T - B)


def frontier(pts):
    srt = sorted(pts, key=lambda p: (p[2], -p[1]))
    best, out = -1, []
    for p in srt:
        if p[1] > best:
            out.append(p); best = p[1]
    return out


def svg(title, ymax, pts, bench, ylabel="score on this bench", ref=None):
    key = next(k for k in REASONS if title.startswith(k))
    ref_box = None
    o = [f'<svg width="{W}" height="{H}" viewBox="0 0 {W} {H}" role="img" aria-label="{html.escape(title)}" font-family="system-ui" font-size="12" style="max-width:100%;height:auto">']
    # gridlines + y labels
    step = 1 if ymax <= 14 else 2
    for s in range(0, int(ymax) + 1, step):
        y = ypos(s, ymax)
        o.append(f'<line x1="{L}" x2="{W-R}" y1="{y:.1f}" y2="{y:.1f}" stroke="#e5e7eb"/>')
        o.append(f'<text x="{L-8}" y="{y+4:.1f}" text-anchor="end" fill="#555">{s}</text>')
    # x ticks
    for c, lab in [(0.01, "$0.01"), (0.1, "$0.10"), (1.0, "$1.00")]:
        x = xpos(c)
        o.append(f'<line x1="{x:.1f}" x2="{x:.1f}" y1="{T}" y2="{H-B}" stroke="#f1f5f9"/>')
        o.append(f'<text x="{x:.1f}" y="{H-B+18}" text-anchor="middle" fill="#555">{lab}</text>')
    o.append(f'<line x1="{L}" x2="{W-R}" y1="{H-B}" y2="{H-B}" stroke="#333"/>')
    o.append(f'<line x1="{L}" x2="{L}" y1="{T}" y2="{H-B}" stroke="#333"/>')
    o.append(f'<text x="{(L+W-R)/2:.0f}" y="{H-12}" text-anchor="middle" fill="#333">cost per task (USD, log scale): left = cheaper, right = pricier</text>')
    o.append(f'<text transform="translate(16 {(T+H-B)/2:.0f}) rotate(-90)" text-anchor="middle" fill="#333">{ylabel}</text>')
    if ref is not None:
        v, lab = ref
        y = ypos(v, ymax)
        o.append(f'<line x1="{L}" x2="{W-R}" y1="{y:.1f}" y2="{y:.1f}" stroke="#6b7280" stroke-dasharray="5 4" stroke-width="1.3"/>')
        ref_box = (L + 4, ypos(v, ymax) - 11, L + 4 + len(lab) * 6.9, ypos(v, ymax) + 3)
        o.append(f'<text x="{L+4}" y="{ypos(v, ymax):.1f}" text-anchor="start" fill="#6b7280">{lab}</text>')
    # most attractive quadrant: score >= 70% of max, cost <= 2x the cheapest seated arm
    seated_costs = [c for (_n, _s, c, sd, _sg, _nt, _of, _m) in pts if any(b == bench for _x, b in sd)]
    if seated_costs:
        cheap = min(seated_costs)
        qx1 = min(max(xpos(cheap * 2), L), W - R)
        qy1 = ypos(0.7 * ymax, ymax)
        o.append(f'<rect x="{L}" y="{T}" width="{qx1 - L:.1f}" height="{qy1 - T:.1f}" fill="#ecfdf5" stroke="#86efac" stroke-dasharray="3 3" stroke-width="1"/>')
        o.append(f'<text x="{L + 6}" y="{T + 14}" fill="#166534" font-size="11">most attractive quadrant</text>')
    # frontier
    fr = frontier(pts)
    if len(fr) > 1:
        d = " ".join(f"{xpos(p[2]):.1f},{ypos(p[1], ymax):.1f}" for p in fr)
        o.append(f'<polyline points="{d}" fill="none" stroke="#6b7280" stroke-dasharray="5 4" stroke-width="1.3"/>')
    # points + labels: each label sits next to its own dot; pick the first
    # candidate position whose box does not overlap a placed label.
    # Single tooltip: data-tip only (JS div); no native <title>.
    placed = []
    CH = 6.9  # px per character at 12px
    def box(cx, cy, w, anchor):
        x0 = cx if anchor == "start" else cx - w
        return (x0, cy - 11, x0 + w, cy + 3)
    def overlap(a, b):
        return not (a[2] <= b[0] or b[2] <= a[0] or a[3] <= b[1] or b[3] <= a[1])
    for entry in sorted(pts, key=lambda p: (p[2], -p[1])):
        name, s_, c, seats, single, note, one_fam, meta = entry
        x, y = xpos(c), ypos(s_, ymax)
        # color = seat on THIS bench; fill = measurement investment (single -> hollow)
        here = [f"{n} ({b})" for n, b in seats if b == bench]
        col = "#1d4ed8" if here else "#9ca3af"
        # full model id (provider/model) + effort for the tooltip
        base, eff = name, "default"
        for e in ("default", "low", "medium", "high", "xhigh", "max"):
            if name.endswith("-" + e):
                base, eff = name[: -(len(e) + 1)], e
                break
        full = FULLIDS[base]
        why = REASONS[key].get(name, "")
        seat_line = (f'seats: {html.escape(", ".join(f"{n} ({b})" for n, b in seats))}' if seats else '')
        info, ops = meta["info"], meta["ops"]
        if meta["cost_src"] == "bench":
            cost_line = f'cost: mean of {info["d"]} delivered run(s), this bench'
            if info["n"] > info["d"]:
                cost_line += f' (incl. {info["n"] - info["d"]} failed attempt(s): ${info["incl"]:.3f}/delivered)'
        else:
            cost_line = 'cost: generic CSV estimate (no run data on this bench)'
        if ops:
            ops_line = f'delivered {ops["d"]}/{ops["n"]} (all benches)'
        else:
            ops_line = 'delivered: no run data'
        fp_line = ff_line(meta, bench)
        TIPHTML = (f'<b>{html.escape(full)}</b> <i>{html.escape(eff)}</i><br>'
                   f'score {s_:g} · ${c:g}/task · {latency_text(meta["dur"])}'
                   + (' · single valid run' if single else '')
                   + (' · one scorer family (~)' if one_fam else '')
                   + f'<br><small>{html.escape(cost_line)}</small>'
                   + f'<br><small>{html.escape(ops_line)}</small>'
                   + (f'<br><small>{html.escape(fp_line)}</small>' if fp_line else '')
                   + (f'<br>{seat_line}' if seat_line else '')
                   + (f'<br><small>{html.escape(why)}</small>' if why else '')
                   + (f'<br><small>note: {html.escape(note)}</small>' if note else ''))
        data_tip = html.escape(TIPHTML, quote=True)
        if single:
            o.append(f'<circle class="pt" data-tip="{data_tip}" cx="{x:.1f}" cy="{y:.1f}" r="6" fill="#fff" stroke="{col}" stroke-width="2"/>')
        else:
            o.append(f'<circle class="pt" data-tip="{data_tip}" cx="{x:.1f}" cy="{y:.1f}" r="6" fill="{col}"/>')
        label = name + ("~" if one_fam else "")  # model name (+ ~ = one scorer family); tooltip carries score/cost/seat/why
        w = len(label) * CH
        # displacement cap: labels stay within +/-20px vertical of their own dot
        cands = [(x+9, y+d, "start") for d in (-4, 14, -20)] \
              + [(x-9, y+d, "end") for d in (-4, 14, -20)]
        chosen = None
        for cx, cy, anc in cands:
            bx = box(cx, cy, w, anc)
            if bx[0] < L or bx[2] > W - R + 40 or bx[1] < T - 5 or bx[3] > H - B:
                continue
            if any(overlap(bx, q) for q in placed):
                continue
            chosen = (cx, cy, anc, bx); break
        if chosen is None:
            # no free slot within the cap: default position anyway - a small
            # overlap is recoverable, a label floating far from its dot is a lie
            cx, cy, anc = x + 9, y - 4, "start"
            chosen = (cx, cy, anc, box(cx, cy, w, anc))
        cx, cy, anc, bx = chosen
        placed.append(bx)
        fill = "#1d4ed8" if here else "#374151"
        # leader line when the label is not at the default position: keep it
        # visually attached to its dot (thin grey, dot edge -> box nearest edge)
        if (cx, cy, anc) != (x + 9, y - 4, "start"):
            bx0, by0, bx1, by1 = bx
            tcx, tcy = (bx0 + bx1) / 2, (by0 + by1) / 2
            dx, dy = tcx - x, tcy - y
            dist = math.hypot(dx, dy) or 1
            sx, sy = x + 6.5 * dx / dist, y + 6.5 * dy / dist   # dot edge (r=6)
            ex = min(max(sx, bx0), bx1); ey = min(max(sy, by0), by1)  # box entry point
            o.append(f'<line x1="{sx:.1f}" y1="{sy:.1f}" x2="{ex:.1f}" y2="{ey:.1f}" stroke="#aaa" stroke-width="1"/>')
        o.append(f'<text class="pt" data-tip="{data_tip}" x="{cx:.1f}" y="{cy:.1f}" text-anchor="{"start" if anc=="start" else "end"}" fill="{fill}" stroke="#fff" stroke-width="3" paint-order="stroke">{html.escape(label)}</text>')
    o.append('</svg>')
    return "\n".join(o)

ROSTER_MODEL = {
    "glm-5.3-flash": "glm", "claude-haiku-5.5": "haiku", "deepseek-v4p1-flash": "dsflash",
    "deepseek-v4p1-flash-1017": "1017", "minimax-m3p1-flash": "minimax", "claude-sonnet-5.5": "sonnet",
    "gpt-6.1-terra": "terra", "claude-opus-5.5": "opus", "qwen3p8-2p4t-a95b": "qwen",
    "gemini-4-hydrogen": "hydrogen", "gemini-4-argon": "argon", "gemini-4-carbon": "carbon",
}
ROSTER_EFFORTS = ("low", "medium", "high", "xhigh")


def ops_text(model, eff):
    """Roster ops cell: delivered k/n across all benches, latency range in minutes."""
    o = ops_for(model, eff) if model else None
    if not o or o["n"] == 0:
        return "no runs"
    txt = f'{o["d"]}/{o["n"]} delivered'
    if o["dur_min"] is not None:
        lo, hi = round(o["dur_min"] / 60), round(o["dur_max"] / 60)
        txt += f' · {lo}–{hi} min' if lo != hi else f' · ~{lo} min'
    if o["n"] > o["d"]:
        txt += f' · {o["n"] - o["d"]} failed attempt(s)'
        txt += f' · cost incl. failed ${o["tot"] / o["d"]:.2f}/delivered'
    return txt


def patch_roster_ops(src):
    """Adds an 'ops' column (before the fallback column) to every #roster seat row.
    Idempotent: an existing ops cell is replaced, not duplicated."""
    a = src.index('<section id="roster">'); b = src.index('<section id="charts">')
    sec = src[a:b]
    if 'Ops (delivered' not in sec:
        sec = sec.replace('<th>Fallback if it regresses</th>',
                          '<th>Ops (delivered · latency)</th><th>Fallback if it regresses</th>', 1)
    def patch_row(m):
        attrs, body = m.group(1), m.group(2)
        cells = re.findall(r"<td[^>]*>.*?</td>", body, re.S)
        if len(cells) < 6:
            return m.group(0)
        model_txt = re.sub(r"<[^>]+>", " ", cells[1]).split()
        if not model_txt:
            return m.group(0)
        name = model_txt[0]
        eff = model_txt[1] if len(model_txt) > 1 and model_txt[1] in ROSTER_EFFORTS else "default"
        key = ROSTER_MODEL.get(name)
        ops_cell = f'<td class="ops" style="white-space:nowrap">{html.escape(ops_text(key, eff))}</td>'
        if 'class="ops"' in body:
            body = re.sub(r'<td class="ops"[^>]*>.*?</td>', ops_cell, body, count=1, flags=re.S)
        else:
            last = cells[-1]
            body = body.replace(last, ops_cell + last, 1)
        return f"<tr{attrs}>{body}</tr>"
    sec = re.sub(r"<tr([^>]*)>(.*?)</tr>", patch_row, sec, flags=re.S)
    return src[:a] + sec + src[b:]



# ---- Artificial-Analysis-style ops charts (time per task, tokens per task) ----
ARM_CHALLENGERS = [("qwen", "medium"), ("carbon", "high"), ("gpt-6.2-sol", "high")]
OPS_BENCHES = [("O", "O (orchestration)"), ("IR", "IR (impl review)"), ("DR2", "DR-v2 (design review)"),
               ("I2-RG4", "I-v2 RG4 (implementation)"), ("D", "D (design authoring)")]
FAM_COLOR = {"glm": "#1a7f37", "haiku": "#b3261e", "sonnet": "#b3261e", "opus": "#b3261e", "fable": "#b3261e",
             "dsflash": "#0b57d0", "1017": "#0b57d0", "minimax": "#6d28d9", "qwen": "#d97706",
             "terra": "#a16207", "sol": "#a16207", "gpt-6.2-sol": "#a16207", "astra": "#a16207",
             "argon": "#0891b2", "carbon": "#0891b2", "hydrogen": "#0891b2", "gem38": "#0891b2",
             "muse": "#c2185b", "kimi": "#52525b",
             "mai-code-2": "#e11d48", "mai-code-2-flash": "#e11d48"}
TOKEN_PARTS = [("input", "input", "#1d4ed8"), ("cache_read", "cache read", "#93c5fd"),
               ("output", "output", "#f59e0b"), ("reasoning", "reasoning", "#a855f7")]


def arm_list():
    return list(dict.fromkeys(list(SEATS.keys()) + ARM_CHALLENGERS))


def arm_name(m, e):
    return m if e == "default" else f"{m} {e}"


def fmt_time(sec):
    return f"~{sec:.0f}s" if sec < 120 else f"~{sec / 60:.0f} min"


OPS_SCORE_COL = {"O": "O8", "IR": "IR", "DR2": "DR2", "I2-RG4": "I2-RG4", "D": "D"}
OPS_SCORE_DENOM = {"O": "/8", "IR": "/3+", "DR2": "/14", "I2-RG4": "/14", "D": "/11"}


def bench_score(bench, model, eff):
    """Score label for a bar: the CSV cell of this bench (IR: bonus-inclusive), compact."""
    col = OPS_SCORE_COL.get(bench)
    for r in csv.DictReader(open(CSVPATH)):
        if r["model"].strip() == model and r["effort"].strip() == eff:
            v = r.get(col, "").strip().rstrip("*~")
            try:
                return f"{float(v):g}{OPS_SCORE_DENOM[bench]}"
            except ValueError:
                return ""
    return ""


def ops_section_html():
    W_, LW, RM, TOP, GH, RH = 1200, 230, 120, 36, 24, 18
    # --- (a) time per task: median per arm and bench, log scale
    tg = []
    for bcode, blabel in OPS_BENCHES:
        items = []
        for m, e in arm_list():
            d = cell_dur(bcode, m, e)
            if d:
                items.append((m, e, d))
        items.sort(key=lambda it: it[2]["med"])
        if items:
            tg.append((blabel, bcode, items))
    lo_t, hi_t = 10.0, 3600.0
    def xt(t):
        return LW + (math.log10(max(t, lo_t)) - math.log10(lo_t)) / (math.log10(hi_t) - math.log10(lo_t)) * (W_ - LW - RM)
    h = TOP + sum(GH + RH * len(items) for _, _, items in tg) + 46
    o = [f'<svg width="{W_}" height="{h}" viewBox="0 0 {W_} {h}" role="img" aria-label="Time per task (median, delivered runs, log scale)" font-family="system-ui" font-size="12" style="max-width:100%;height:auto">']
    for tick, lab in [(10, "10s"), (60, "1 min"), (600, "10 min"), (3600, "1 h")]:
        x = xt(tick)
        o.append(f'<line x1="{x:.1f}" x2="{x:.1f}" y1="{TOP - 6}" y2="{h - 40}" stroke="#e5e7eb"/>')
        o.append(f'<text x="{x:.1f}" y="{h - 24}" text-anchor="middle" fill="#555">{lab}</text>')
    y = TOP
    for blabel, bcode, items in tg:
        o.append(f'<text x="8" y="{y + 16}" font-weight="700" fill="#333">{html.escape(blabel)} — {len(items)} arms</text>')
        y += GH
        for m, e, d in items:
            fam = FAM_COLOR.get(m, "#555")
            x1 = xt(d["med"])
            tip = html.escape(f'{m} {e} · {bcode}: median {fmt_time(d["med"])} (range {fmt_time(d["lo"])}–{fmt_time(d["hi"])}, {d["n"]} delivered run(s))', quote=True)
            o.append(f'<text x="{LW - 8}" y="{y + 12}" text-anchor="end" fill="{fam}" font-weight="600">{html.escape(arm_name(m, e))}</text>')
            o.append(f'<rect class="pt" data-tip="{tip}" x="{LW}" y="{y + 3}" width="{x1 - LW:.1f}" height="12" fill="{fam}" fill-opacity="0.85"/>')
            sc = bench_score(bcode, m, e)
            lab = fmt_time(d["med"]) + (f" · {sc}" if sc else "")
            o.append(f'<text x="{x1 + 6:.1f}" y="{y + 12}" fill="#374151">{html.escape(lab)}</text>')
            y += RH
    o.append('</svg>')
    time_svg = "\n".join(o)
    fastest = min(((m, e, b, d) for _, b, its in tg for m, e, d in its), key=lambda t: t[3]["med"], default=None)
    slowest = max(((m, e, b, d) for _, b, its in tg for m, e, d in its), key=lambda t: t[3]["med"], default=None)
    # --- (b) tokens per task: stacked, linear
    kg = []
    missing = 0
    for bcode, blabel in OPS_BENCHES:
        items = []
        for m, e in arm_list():
            if not cell_dur(bcode, m, e):
                continue
            t = cell_tokens(bcode, m, e)
            if t:
                items.append((m, e, t))
            else:
                missing += 1
        items.sort(key=lambda it: it[2]["total"])
        if items:
            kg.append((blabel, bcode, items))
    allt = [t["total"] for _, _, its in kg for _, _, t in its]
    maxT = math.ceil(max(allt) / 250_000) * 250_000 if allt else 1
    def xk(v):
        return LW + v / maxT * (W_ - LW - RM)
    hk = TOP + sum(GH + RH * len(items) for _, _, items in kg) + 46
    ok = [f'<svg width="{W_}" height="{hk}" viewBox="0 0 {W_} {hk}" role="img" aria-label="Tokens per task (mean per delivered run, stacked)" font-family="system-ui" font-size="12" style="max-width:100%;height:auto">']
    for k in range(0, int(maxT) + 1, 250_000):
        x = xk(k)
        ok.append(f'<line x1="{x:.1f}" x2="{x:.1f}" y1="{TOP - 6}" y2="{hk - 40}" stroke="#e5e7eb"/>')
        ok.append(f'<text x="{x:.1f}" y="{hk - 24}" text-anchor="middle" fill="#555">{k / 1000:.0f}k</text>')
    y = TOP
    for blabel, bcode, items in kg:
        ok.append(f'<text x="8" y="{y + 16}" font-weight="700" fill="#333">{html.escape(blabel)} — {len(items)} arms</text>')
        y += GH
        for m, e, t in items:
            fam = FAM_COLOR.get(m, "#555")
            ok.append(f'<text x="{LW - 8}" y="{y + 12}" text-anchor="end" fill="{fam}" font-weight="600">{html.escape(arm_name(m, e))}</text>')
            acc = 0.0
            for key, lab, colr in TOKEN_PARTS:
                v = t[key]
                x0, x1 = xk(acc), xk(acc + v)
                tip = html.escape(f'{m} {e} · {bcode}: {lab} {v / 1000:.0f}k of {t["total"] / 1000:.0f}k tokens per run (mean of {t["n"]} run(s))', quote=True)
                ok.append(f'<rect class="pt" data-tip="{tip}" x="{x0:.1f}" y="{y + 3}" width="{max(x1 - x0, 0):.1f}" height="12" fill="{colr}"/>')
                acc += v
            sc = bench_score(bcode, m, e)
            tok_lab = f'{t["total"] / 1000:.0f}k' if t["total"] < 1_000_000 else f'{t["total"] / 1_000_000:.1f}M'
            lab = f"~{tok_lab} tok" + (f" · {sc}" if sc else "")
            ok.append(f'<text x="{xk(acc) + 6:.1f}" y="{y + 12}" fill="#374151">{html.escape(lab)}</text>')
            y += RH
    ok.append('</svg>')
    tok_svg = "\n".join(ok)
    # shares for the takeaway
    cache_share = (sum(t["cache_read"] for _, _, its in kg for _, _, t in its) /
                   max(sum(t["total"] for _, _, its in kg for _, _, t in its), 1))
    top_tok = max(((m, e, b, t) for _, b, its in kg for m, e, t in its), key=lambda q: q[3]["total"], default=None)
    t1 = (f"Time per task (median per bench, log scale): fastest {arm_name(fastest[0], fastest[1])} on {fastest[2]} at {fmt_time(fastest[3]['med'])}, "
          f"slowest {arm_name(slowest[0], slowest[1])} on {slowest[2]} at {fmt_time(slowest[3]['med'])}") if fastest and slowest else "Time per task"
    t2 = (f"Tokens per task (mean per delivered run): {arm_name(top_tok[0], top_tok[1])} on {top_tok[2]} uses the most ({top_tok[3]['total'] / 1000:.0f}k); "
          f"cache reads are {cache_share:.0%} of all tokens") if top_tok else "Tokens per task"
    out = [
        '<section id="ops">\n<h2>Ops — time and tokens per task</h2>\n'
        '<p class="note">Artificial-Analysis-style operations view for the seated arms and the top challengers. '
        'Delivered runs only (scored or completed); durations and tokens come from the session record (run-ops.tsv). '
        f'Token records are present for every arm shown; {missing} arm-by-bench cell(s) carry no token record and are absent (n.v.). '
        'Hover any bar for its exact values.</p>',
        f'<h3>{html.escape(t1)}</h3>', time_svg,
        '<p class="note">Bar = median wall-clock time per delivered run on that bench, log scale; label = median. Colour = model family.</p>',
        f'<h3>{html.escape(t2)}</h3>', tok_svg,
        '<p class="note">Stacked bar = mean tokens per delivered run: input, cache read, output, reasoning (sum over the parent session and its delegated children).</p>',
        '</section>\n',
    ]
    return "\n".join(out)


def build_and_write():
    blocks = []
    blocks.append('<section id="charts">\n<h2>Charts — who wins each decision bench</h2>\n<p class="note">Each dot is one measured model&times;effort cell, read directly from the score CSV (dots = measured cells; not measured / DNF / categorical cells have no dot). Left = cheaper per task, up = higher score. <strong>Blue</strong> = holds a seat on this bench; grey = does not; hollow ring = single valid run (*). <strong>~</strong> = one scorer family (the cell was scored by one family only). Dashed line = best trade-off frontier: no other model is both cheaper and better.</p>')
    for key, title, ymax, column, ylabel, ref, bench in BENCHES:
        pts = load_dots(column)
        blocks.append(f'<h3>{html.escape(title)}</h3>')
        blocks.append(svg(title, ymax, pts, bench, ylabel, ref))
        blocks.append(f'<p class="note">blue = seat on this bench · grey = no seat · filled = 2+ valid runs · hollow = 1 run (under-measured) · ~ = one scorer family · dashed = frontier · X = cost per delivered run on this bench (generic CSV estimate where no run data) · IR/DR2 show findings and false positives separately where the run record states them; otherwise the net is marked “net” — a net score never hides real findings · findings = categories credited (DR2, of 10; the score also carries the proof bonus) or seeded hits + bonus (IR, of 3 + bonus) · FP = mean over the readers that stated a false-positive count (reader counts shown); the official record (the FP the CSV note states) always wins · hover = provider/model id, effort, score, cost, delivery and latency, seats, why, CSV note</p>')
    blocks.append('<h3>Why the best-and-cheaper model is not always the seat</h3>')
    blocks.append('<p class="note"><strong>Tie rule (ratified 2026-11-20).</strong> Eligibility = two scorer families + &ge;2 valid runs; the cheapest arm inside the MDE band wins the seat.</p>')
    blocks.append('''<table class="matrix"><thead><tr><th>Seat</th><th>Best-and-cheaper candidate</th><th>Why it is not the seat</th></tr></thead><tbody>
<tr><td>orchestration</td><td>haiku-medium (7.5 at $0.01) / sonnet-high (8 at $0.10)</td><td>glm-max (7.33/8 n=3 · $0.007 — stability x3 confirmed 2026-11-23) — the highest-volume seat: haiku-medium scores 7.5 at 2x, sonnet-high 8 at 20x; the price rule wins at this volume. Revisit if glm O &lt; 5.</td></tr>
<tr><td>cheap-design-review</td><td>qwen-xhigh (10 at ~$1.07, one valid run)</td><td>minimax holds it twice over: medium effort holds this rung (8.0 at $0.04, on price - qwen-medium posts 8.6 at 8x the cost), xhigh holds strong-design-review (11.25 with 4 executed proofs) — a same-family effort escalation the owner accepted. Minimax is critique-only: its design authoring collapses across runs (two DNFs, false claim).</td></tr>
<tr><td>strong-design-review</td><td>carbon-high (10 at $0.15-0.23, one valid run)</td><td>minimax-xhigh holds the rung on the complete grid: 11.25/14 with 4 executed proofs at $0.03 — the best DR2 measured. 1017 medium measures 4.75 on the official panel.</td></tr>
<tr><td>strong-design</td><td>opus (9.58 at ~$1.39)</td><td>1017-high holds it (9.81 at $0.12) - rank-1 D measured, 1/12 of opus's price; opus keeps alt2/terminal.</td></tr>
<tr><td>strong-review-alternative2</td><td>—</td><td>qwen-xhigh (4.0 · $0.15) — family-diverse last stop before opus/deep (the true terminal); qwen misses seeded-3 on both runs — depth stop, not floor material.</td></tr>
<tr><td>strong-design-review-alternative</td><td>carbon-high (10 at $0.15-0.23, one valid run)</td><td>argon-high (9.5, multi-run) - the best non-minimax DR2; reviews designs when minimax has already reviewed them (fresh family, gemini vs minimax). carbon's 10 is one valid run; qwen's 10 is a single run at ~$1/task with 0-7.5 variance elsewhere.</td></tr>
<tr><td>cheap-design</td><td>1017 (7.06 at $0.10; high posts 9.81)</td><td>haiku medium holds the rung: 8.08 at $0.02/task — higher and 5x cheaper than 1017 medium. 1017 high holds strong-design; minimax cannot write designs (collapsing runs, false claim).</td></tr>
<tr><td>cheap-code</td><td>haiku-high (8.83 at $0.05)</td><td>The seat is haiku default (8.33 official I-v2 mean at $0.02-0.03): the cheap tier needs cheap, not best, and briefs &gt;90k tokens already pay a 5&times; cliff at default.</td></tr>
<tr><td>cheap-review</td><td>glm-low (2.5 at $0.005, the previous holder)</td><td>minimax-xhigh takes the rung (IR 4.33 bonus-inclusive at $0.014): gates fail silently, so floor recall is the protection - the 4.33 mean on top of clean 3/3 runs buys the recall the 2.5 floor lacks. glm-low leaves review (2.5) and is documented as the lineage-legal fallback reviewer for deepseek/gemini-produced work only.</td></tr>
<tr><td>cheap-mech</td><td>—</td><td>dsflash - mechanical edits need cheapest-per-token reliability, not depth; I2 8 suffices.</td></tr>
<tr><td>explore</td><td>—</td><td>dsflash - read-only grounding at the cheapest blended rate; no bench disputes it.</td></tr>
<tr><td>strong-review</td><td>minimax-xhigh (4.33 at $0.014, holds cheap-review)</td><td>sonnet-medium takes the rung (IR 4.75, 4 valid runs 5;5;4;5 at $0.09) - a fresh family vs the minimax floor it escalates from; keeping the rung in the floor's own family would pair minimax review with minimax review.</td></tr>
<tr><td>strong-review-alt</td><td>qwen-xhigh (4.0 at $0.15, the quality step)</td><td>strong-review-alt = 1017 high (3.62 · $0.016) — a lineage VALVE, not a quality step: when minimax-xhigh (the floor gate) fails on claude-produced code, the next rung up (sonnet-medium) is claude and may not review claude — 1017 (deepseek) is the only cheap fresh-family escalation. Dominated on this chart by minimax-xhigh (4.33, cheaper) ON PURPOSE: quality here would be qwen-xhigh (4.0 · $0.15) — 10x the price for a rung almost never pulled.</td></tr>
<tr><td>strong-code-alternative</td><td>haiku-high (8.83 at $0.15)</td><td>The only real capability step above cheap-code (+0.5); family-alternates with minimax. sonnet-high (7.75 at $0.40) buys no I2 points and left the code ladder.</td></tr>
<tr><td>strong-design-alternative</td><td>kimi-medium (6.94 at $0.18, 2 runs)</td><td>sonnet-high holds it (8.4 at $0.83: clean re-fold 8 + H4 fold v3 +0.4) - beat kimi-medium on quality; fresh family vs 1017 for stuck designs. Sonnet keeps a seat, just on a different bench.</td></tr>
<tr><td>strong-code</td><td>sonnet-high (13.5~ on RG4, one scorer family) · haiku-high (13.5 at $0.15)</td><td>minimax-xhigh holds it: 13.0 at $0.03 on RG4 (2 valid runs, 3-pt spread). The 0.5 gap to sonnet-high and haiku-high is under the 1.5 pt MDE, so the tie rule applies and the price decides (13&times; cheaper than sonnet-high at $0.40). Challenger line: qwen-medium 13.5 (2 valid runs, $0.30-0.68) - the family-diverse tie at 10x the price, not a seat change.</td></tr>
</tbody></table>''')
    blocks.append('''<div id="tooltip" style="position:fixed;pointer-events:none;background:#1f2937;color:#fff;padding:8px 10px;border-radius:6px;font:12px system-ui;max-width:340px;z-index:9;box-shadow:0 4px 12px rgba(0,0,0,.3);display:none"></div>
<script>
(function () {
  var tip = document.getElementById('tooltip');
  document.addEventListener('mouseover', function (e) {
    var t = e.target.closest ? e.target.closest('[data-tip]') : null;
    if (!t) return;
    tip.innerHTML = t.getAttribute('data-tip');
    tip.style.display = 'block';
  });
  document.addEventListener('mousemove', function (e) {
    if (tip.style.display !== 'block') return;
    var w = tip.offsetWidth, h = tip.offsetHeight;
    var x = e.clientX + 12, y = e.clientY + 12;
    if (x + w > window.innerWidth - 8) x = e.clientX - w - 12;
    if (y + h > window.innerHeight - 8) y = e.clientY - h - 12;
    tip.style.left = x + 'px';
    tip.style.top = y + 'px';
  });
  document.addEventListener('mouseout', function (e) {
    if (e.target.closest && e.target.closest('[data-tip]')) tip.style.display = 'none';
  });
})();
</script>''')
    blocks.append('</section>\n')
    blocks.append(ops_section_html())
    new = "\n".join(blocks)

    src = patch_roster_ops(open(PATH).read())
    start = src.index('<section id="charts">')
    end = src.index('<section id="codes">')
    src = src[:start] + new + src[end:]
    open(PATH, "w").write(src)
    print("charts rewritten")


if __name__ == "__main__":
    build_and_write()
