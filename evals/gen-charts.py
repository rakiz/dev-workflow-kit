import csv, html, math, re
from reasons import REASONS

PATH = "/Users/sebastien.mendez/code_projects/IA-tooling/dev-workflow-kit/evals/LEADERBOARD.html"
CSVPATH = "/Users/sebastien.mendez/code_projects/IA-tooling/dev-workflow-kit/evals/2026-11-16/grid2-scores.csv"

W, H = 1200, 540
L, R, T, B = 80, 60, 30, 60
X0, X1 = 0.004, 5.0   # log range in USD (fable/astra sit at ~$4/task)
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
}

# roster final seat map: (CSV model, effort) -> [(seat name, deciding bench code)].
# Source of truth: models.json "global" + the roster's "Decided on" citations.
# glm-low left review (documented fallback reviewer for deepseek/gemini-produced
# work); hydrogen-high holds no seat.
SEATS = {
    ("glm", "high"): [("orchestration", "O")],
    ("haiku", "default"): [("cheap-code", "I-v2")],
    ("haiku", "medium"): [("cheap-design", "D")],
    ("haiku", "high"): [("strong-code-alternative", "I-v2")],
    ("dsflash", "default"): [("cheap-mech", "I-v2"), ("explore", "I-v2")],
    ("minimax", "medium"): [("cheap-design-review", "DR-v2")],
    ("minimax", "xhigh"): [("cheap-review", "IR"), ("strong-design-review", "DR-v2"), ("strong-code", "I-v2")],
    ("opus", "default"): [("deep", "I-v2"), ("strong-code-alternative2", "I-v2"), ("strong-design-alternative2", "D")],
    ("sonnet", "medium"): [("strong-review", "IR")],
    ("sonnet", "high"): [("strong-design-alternative", "D")],
    ("qwen", "xhigh"): [("strong-review-alternative2", "IR")],
    ("1017", "high"): [("strong-design", "D"), ("strong-review-alternative", "IR")],
    ("argon", "high"): [("strong-design-review-alternative", "DR-v2")],
}

# bench charts: (REASONS key, title, y-max, CSV column, y-axis label, ref line)
BENCHES = [
    ("Orchestration",
     "Orchestration (O, /8): sonnet-high plans best (8); glm keeps the seat on price (7 at $0.005 - 20x cheaper than the top scorers)",
     8, "O8", "score on this bench", None, "O"),
    ("Design writing",
     "Design writing (D, /11): 1017-high best (9.44 at $0.12), opus 8.58 at 12x the cost; glm and gem38 cannot write designs",
     11, "D", "score on this bench", None, "D"),
    ("Design review",
     "Design review (DR-v2, /14): minimax-xhigh posts 11.25 with 4 executed proofs and takes the strong rung; opus scores 0 (2 FPs)",
     14, "DR2", "score on this bench", None, "DR-v2"),
    ("Implementation",
     "Implementation (I-v2, /14): haiku-high edges opus on the official panel mean (8.83 vs 8.5); the multi-scorer re-score reshapes the grid",
     14, "I2", "score on this bench", None, "I-v2"),
    ("Code review",
     "Code review (IR, /3+bonus): the 3 seeded defects stop separating at 3 - the bonus axis ranks the top crowd (3.0-4.35); the bottom cluster (2.0-2.5) misses a seeded defect",
     5, "IR", "IR /3 seeded (+bonus up to +2)", (3, "seeded ceiling"), "IR"),
]


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
    marks a single-valid run). not measured / DNF / cat * render no dot."""
    pts = []
    for r in csv.DictReader(open(CSVPATH)):
        v = r[column].strip()
        try:
            s = float(v.rstrip("*"))
        except ValueError:
            continue
        cost = parse_cost(r["cost_per_task_est"])
        if cost is None:
            continue
        model, eff = r["model"].strip(), r["effort"].strip()
        name = model if eff == "default" else f"{model}-{eff}"
        note = r["notes"].strip().lstrip("-").strip()
        # hollow = under-measured: CSV star OR the row's notes say single / 1 valid
        single = v.endswith("*") or bool(re.search(r"\bsingle\b|1 valid|\b1v\b", note, re.I))
        pts.append((name, s, cost, SEATS.get((model, eff), []), single, note))
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
        name, s_, c, seats, single, note = entry
        x, y = xpos(c), ypos(s_, ymax)
        # color = seat on THIS bench; fill = measurement investment (single -> hollow)
        here = [f"{n} ({b})" for n, b in seats if b == bench]
        col = "#1d4ed8" if here else "#9ca3af"
        # full model id (provider/model) + effort for the tooltip
        base, eff = name, "default"
        for e in ("default", "low", "medium", "high", "xhigh"):
            if name.endswith("-" + e):
                base, eff = name[: -(len(e) + 1)], e
                break
        full = FULLIDS[base]
        why = REASONS[key].get(name, "")
        seat_line = (f'seats: {html.escape(", ".join(f"{n} ({b})" for n, b in seats))}' if seats else '')
        TIPHTML = (f'<b>{html.escape(full)}</b> <i>{html.escape(eff)}</i><br>'
                   f'score {s_:g} · ${c:g}/task'
                   + (' · single valid run' if single else '')
                   + (f'<br>{seat_line}' if seat_line else '')
                   + (f'<br><small>{html.escape(why)}</small>' if why else '')
                   + (f'<br><small>note: {html.escape(note)}</small>' if note else ''))
        data_tip = html.escape(TIPHTML, quote=True)
        if single:
            o.append(f'<circle class="pt" data-tip="{data_tip}" cx="{x:.1f}" cy="{y:.1f}" r="6" fill="#fff" stroke="{col}" stroke-width="2"/>')
        else:
            o.append(f'<circle class="pt" data-tip="{data_tip}" cx="{x:.1f}" cy="{y:.1f}" r="6" fill="{col}"/>')
        label = name  # model name (with effort qualifier) only; tooltip carries score/cost/seat/why
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

def build_and_write():
    blocks = []
    blocks.append('<section id="charts">\n<h2>Charts — who wins each decision bench</h2>\n<p class="note">Each dot is one measured model&times;effort cell, read directly from the score CSV (dots = measured cells; not measured / DNF / categorical cells have no dot). Left = cheaper per task, up = higher score. <strong>Blue</strong> = holds a seat on this bench; grey = does not; hollow ring = single valid run (*). Dashed line = best trade-off frontier: no other model is both cheaper and better.</p>')
    for key, title, ymax, column, ylabel, ref, bench in BENCHES:
        pts = load_dots(column)
        blocks.append(f'<h3>{html.escape(title)}</h3>')
        blocks.append(svg(title, ymax, pts, bench, ylabel, ref))
        blocks.append('<p class="note">blue = seat on this bench · grey = no seat · filled = 2+ valid runs · hollow = 1 run (under-measured) · dashed = frontier · hover = provider/model id, effort, score, cost, seats, why, CSV note</p>')
    blocks.append('<h3>Why the best-and-cheaper model is not always the seat</h3>')
    blocks.append('''<table class="matrix"><thead><tr><th>Seat</th><th>Best-and-cheaper candidate</th><th>Why it is not the seat</th></tr></thead><tbody>
<tr><td>cheap-design-review</td><td>qwen-xhigh (10 at ~$1.07, one valid run)</td><td>minimax holds it twice over: medium effort holds this rung (8.0 at $0.04, on price - qwen-medium posts 8.6 at 8x the cost), xhigh holds strong-design-review (11.25 with 4 executed proofs) — a same-family effort escalation the owner accepted. Minimax is critique-only: its design authoring collapses across runs (two DNFs, false claim).</td></tr>
<tr><td>strong-design-review</td><td>carbon-high (10 at $0.15-0.23, one valid run)</td><td>minimax-xhigh holds the rung on the complete grid: 11.25/14 with 4 executed proofs at $0.03 — the best DR2 measured. 1017 medium measures 4.75 on the official panel.</td></tr>
<tr><td>strong-design</td><td>opus (8.58 at ~$1.39)</td><td>Held by 1017 high (9.44 at $0.12), ahead of opus at about 12x less cost. opus holds strong-design-alternative2, the parking rung for good models we hesitate to drop.</td></tr>
<tr><td>strong-design-review-alt</td><td>carbon (10 at $0.15-0.23) and qwen (10 at ~$1.07)</td><td>argon holds the rung on a two-run 9.5. carbon's 10 is one valid run; qwen's 10 is a single run at ~$1/task with 0-7.5 variance elsewhere.</td></tr>
<tr><td>cheap-design</td><td>1017 (7.06 at $0.10; high posts 9.44)</td><td>haiku medium holds the rung: 8.08 at $0.02/task — higher and 5x cheaper than 1017 medium. 1017 high holds strong-design; minimax cannot write designs (collapsing runs, false claim).</td></tr>
<tr><td>cheap-code</td><td>haiku-high (8.83 at $0.05)</td><td>The seat is haiku default (8.33 official I-v2 mean at $0.02-0.03): the cheap tier needs cheap, not best, and briefs &gt;90k tokens already pay a 5&times; cliff at default.</td></tr>
<tr><td>cheap-review</td><td>glm-low (2.5 at $0.005, the previous holder)</td><td>minimax-xhigh takes the rung (IR 4.33 bonus-inclusive at $0.014): gates fail silently, so floor recall is the protection - the 4.33 mean on top of clean 3/3 runs buys the recall the 2.5 floor lacks. glm-low leaves review (2.5) and is documented as the lineage-legal fallback reviewer for deepseek/gemini-produced work only.</td></tr>
<tr><td>strong-review</td><td>minimax-xhigh (4.33 at $0.014, holds cheap-review)</td><td>sonnet-medium takes the rung (IR 4.75, 4 valid runs 5;5;4;5 at $0.09) - a fresh family vs the minimax floor it escalates from; keeping the rung in the floor's own family would pair minimax review with minimax review.</td></tr>
<tr><td>strong-code-alternative</td><td>sonnet-high (7.75 at $0.40-1.26, 4-run panel mean)</td><td>Sonnet-high left the code ladder for strong-design-alternative (D 8.17). haiku-high takes the rung: 8.83 official I2 at ~$0.15/task - the capability step above cheap-code (8.33) while opus (8.5 at ~$1.39) costs 9x more.</td></tr>
<tr><td>strong-design-alternative</td><td>hydrogen-high (5.5, the previous holder)</td><td>sonnet-high takes the rung (D 8.17 at $0.83): hydrogen's 5.5 sits below the cheap tier (haiku medium 8.08) - an escalation rung below the floor it escalates to is not an escalation. Sonnet keeps a seat, just on a different bench.</td></tr>
<tr><td>strong-code</td><td>sonnet-high (7.75 at $0.40-1.26, 4-run panel mean)</td><td>Lost it 11-18 (owner vote seat swap): minimax-xhigh takes the rung on price at I2 parity (7.67 arbitrated vs 7.75, 13&times; cheaper).</td></tr>
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
    new = "\n".join(blocks)

    src = open(PATH).read()
    start = src.index('<section id="charts">')
    end = src.index('<section id="codes">')
    src = src[:start] + new + src[end:]
    open(PATH, "w").write(src)
    print("charts rewritten")


if __name__ == "__main__":
    build_and_write()
