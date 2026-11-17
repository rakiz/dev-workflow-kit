import math, re, html
from reasons import REASONS
PATH = "/Users/sebastien.mendez/code_projects/IA-tooling/dev-workflow-kit/evals/LEADERBOARD.html"

# name, score, cost, seats, single_run [, label_suffix]
# Full-effort dot sets from 2026-11-16/grid2-scores.csv. Costs are the CSV
# cost_per_task_est (midpoint of a range, ~N -> N). label_suffix (optional,
# used by the IR chart) is appended to the dot label: "3+2" style bonus/FP.
CHARTS = [
 ("Orchestration (O, /8): opus plans best; glm keeps the seat on price (5-7/8 at $0.005-0.03)", 8, [
  ("opus", 7.5, 1.50, ["deep"], False),
  ("1017-high", 7, 0.02, [], False),
  ("1017-medium", 6.75, 0.02, [], False),
  ("1017-low", 6.25, 0.02, [], False),
  ("haiku-medium", 7, 0.01, ["cheap-code"], False),
  ("haiku-high", 7, 0.02, [], True),
  ("haiku-xhigh", 7, 0.03, [], True),
  ("haiku-default", 6.5, 0.01, [], False),
  ("haiku-low", 5, 0.01, [], True),
  ("sonnet-high", 6.5, 0.10, ["strong-code"], False),
  ("sonnet-medium", 4.5, 0.10, ["strong-review-alt"], False),
  ("argon-medium", 6, 0.09, [], True),
  ("argon-high", 6, 0.10, ["strong-design-review-alt"], False),
  ("argon-low", 5, 0.09, [], True),
  ("carbon-high", 6, 0.21, [], False),
  ("carbon-medium", 6, 0.18, [], False),
  ("carbon-low", 6, 0.15, [], False),
  ("astra", 6, 4.00, [], False),
  ("minimax-high", 5.75, 0.01, [], False),
  ("minimax-xhigh", 5.5, 0.01, [], False),
  ("minimax-medium", 5.25, 0.01, [], False),
  ("minimax-low", 4.5, 0.01, [], False),
  ("sol-low", 7, 0.09, [], False),
  ("sol-medium", 7, 0.095, [], False),
  ("sol-xhigh", 7, 0.09, [], False),
  ("qwen-medium", 5.5, 0.10, [], False),
  ("qwen-low", 2, 0.09, [], True),
  ("glm-high", 7, 0.005, ["orchestration"], True),
  ("glm-low", 5, 0.005, [], True),
  ("dsflash", 5, 0.008, ["cheap-mech", "explore"], False),
  ("dsflash-low", 5, 0.008, [], True),
  ("hydrogen-high", 7, 0.06, [], True),
  ("hydrogen-medium", 5, 0.06, [], True),
  ("muse-medium", 3.7, 0.10, [], False),
  ("muse-high", 7, 0.15, [], True),
  ("muse-low", 5, 0.10, [], True),
  ("muse-xhigh", 3, 0.10, [], True),
  ("kimi-medium", 4.25, 0.18, [], False),
  ("kimi-high", 4, 0.18, [], False),
  ("fable", 1, 4.00, [], False),
 ]),
 ("Implementation (I-v2, /14): opus buys the top score; haiku-high and hydrogen-high are the cheap surprises; 1017 sweeps 8 at every effort", 14, [
  ("opus", 10, 1.385, ["deep", "strong-code-alt2"], False),
  ("sonnet-high", 9, 0.83, ["strong-code"], False),
  ("hydrogen-high", 9, 0.365, [], False),
  ("haiku-high", 9, 0.05, [], False),
  ("1017-low", 8, 0.07, [], False),
  ("1017-high", 8, 0.12, [], False),
  ("minimax-low", 8, 0.03, [], False),
  ("sol-medium", 8, 0.095, [], False),
  ("astra", 8, 4.0, [], False),
  ("haiku-default", 7.5, 0.025, ["cheap-code"], False),
  ("minimax-high", 7.5, 0.05, [], False),
  ("gem38-medium", 7.5, 0.065, [], False),
  ("terra-medium", 7.5, 0.09, ["strong-code-alt"], False),
  ("haiku-medium", 7, 0.02, [], False),
  ("kimi-medium", 7, 0.175, [], False),
  ("qwen-medium", 7, 0.49, [], False),
  ("haiku-xhigh", 7, 0.225, [], True),
  ("argon-high", 7, 0.545, [], True),
  ("glm-low", 6, 0.01, [], False),
  ("haiku-low", 6, 0.02, [], False),
  ("fable", 6, 4.0, [], False),
  ("terra-low", 6, 0.05, [], False),
  ("terra-high", 6, 0.05, [], False),
  ("terra-xhigh", 6, 0.05, [], False),
  ("qwen-xhigh", 5.3, 1.07, [], False),
  ("hydrogen-medium", 5, 0.19, [], False),
  ("minimax-medium", 5, 0.04, [], False),
  ("muse-medium", 4.5, 0.095, [], False),
  ("dsflash", 4.5, 0.03, [], False),
  ("glm-high", 5.5, 0.03, [], False),
  ("1017-medium", 4.5, 0.10, [], False),
  ("minimax-xhigh", 8, 0.03, [], False),
  ("hydrogen-xhigh", 2, 0.70, [], False),
 ]),
 ("Design writing (D, /11): opus best; 1017-high is the best value (8.25 at $0.12); glm and gem38 cannot write designs", 11, [
  ("opus", 8.75, 1.385, ["strong-design-alt2"], False),
  ("1017-high", 8.25, 0.12, [], False),
  ("sonnet-high", 7, 0.83, ["strong-design"], False),
  ("haiku-high", 7.25, 0.05, [], False),
  ("haiku-medium", 7, 0.02, [], False),
  ("haiku-xhigh", 7, 0.225, [], True),
  ("1017-low", 6.75, 0.07, [], False),
  ("minimax-xhigh", 6.75, 0.03, [], False),
  ("1017-medium", 6.5, 0.10, ["cheap-design"], False),
  ("hydrogen-medium", 6.25, 0.19, [], False),
  ("carbon-high", 6.5, 0.19, [], True),
  ("hydrogen-high", 6, 0.365, ["strong-design-alt"], False),
  ("astra", 6, 4.0, [], False),
  ("kimi-medium", 6, 0.175, [], False),
  ("sol-medium", 5.75, 0.095, [], False),
  ("haiku-low", 5.75, 0.02, [], False),
  ("minimax-medium", 5, 0.04, [], False),
  ("haiku-default", 5, 0.025, [], False),
  ("dsflash", 5, 0.03, [], True),
  ("argon-high", 5.25, 0.545, [], True),
  ("muse-medium", 2.75, 0.095, [], False),
  ("qwen-medium", 2.5, 0.49, [], False),
  ("qwen-xhigh", 4.7, 1.07, [], False),
  ("terra-low", 4.5, 0.05, [], False),
  ("terra-medium", 4, 0.09, [], False),
  ("terra-high", 4.5, 0.05, [], False),
  ("terra-xhigh", 4.5, 0.05, [], False),
  ("glm-high", 0.75, 0.03, [], False),
  ("minimax-low", 1.75, 0.03, [], False),
  ("fable", 1.5, 4.0, [], False),
  ("gem38-medium", 0.5, 0.065, [], False),
  ("glm-low", 1, 0.01, [], False),
  ("minimax-high", 5.5, 0.05, [], True),
  ("hydrogen-xhigh", 6.75, 0.70, [], False),
 ]),
 ("Design review (DR-v2, /14): minimax-xhigh posts 11.5 with 4 executed proofs - the first perfect-plus DR2; opus scores 0 (2 FPs)", 14, [
  ("minimax-xhigh", 11.5, 0.03, [], False),
  ("carbon-high", 10, 0.19, [], True),
  ("qwen-xhigh", 10, 1.07, [], True),
  ("argon-high", 9.5, 0.545, ["strong-design-review-alt"], False),
  ("dsflash", 9, 0.03, [], False),
  ("minimax-medium", 8.5, 0.04, ["cheap-design-review"], False),
  ("qwen-medium", 8, 0.49, [], False),
  ("minimax-high", 7.5, 0.05, [], False),
  ("haiku-high", 7, 0.05, [], False),
  ("haiku-xhigh", 7, 0.225, [], False),
  ("1017-low", 7, 0.07, [], False),
  ("1017-high", 7, 0.12, [], False),
  ("sonnet-high", 7, 0.83, [], False),
  ("gem38-medium", 6.5, 0.065, [], False),
  ("minimax-low", 6, 0.03, [], False),
  ("haiku-low", 5.5, 0.02, [], False),
  ("haiku-medium", 5.5, 0.02, [], False),
  ("kimi-medium", 5.5, 0.175, [], False),
  ("1017-medium", 5.5, 0.10, ["strong-design-review"], False),
  ("sol-medium", 5, 0.095, [], False),
  ("haiku-default", 5, 0.025, [], False),
  ("astra", 5, 4.0, [], False),
  ("terra-xhigh", 7, 0.05, [], False),
  ("terra-low", 8, 0.05, [], False),
  ("terra-medium", 8, 0.09, [], True),
  ("glm-high", 5, 0.03, [], False),
  ("glm-low", 5.5, 0.01, [], False),
  ("argon-low", 1, 0.105, [], True),
  ("argon-medium", 1, 0.105, [], True),
  ("fable", 2, 4.0, [], False),
  ("muse-medium", 1, 0.095, [], False),
  ("hydrogen-medium", 4.5, 0.19, [], False),
  ("hydrogen-high", 0.5, 0.365, [], False),
  ("opus", 0, 1.385, [], False),
 ]),
 ("Code review (IR, /3): saturated at 3/3 - almost everyone ties; only dsflash (1.5) separates", 3, [
  ("minimax-low", 2.5, 0.03, [], False, " (2FP)"),
  ("minimax-medium", 3, 0.04, [], False, " (2FP)"),
  ("minimax-high", 3, 0.05, [], False, ""),
  ("minimax-xhigh", 3, 0.03, [], False, ""),
  ("muse-medium", 3, 0.095, [], False, ""),
  ("opus", 3, 1.385, [], False, "+2"),
  ("sonnet-high", 3, 0.83, [], False, "+2, 1FP"),
  ("qwen-xhigh", 3, 1.07, ["strong-review-alt2"], False, "+2 proven"),
  ("haiku-xhigh", 3, 0.225, [], False, "+2 proven"),
  ("haiku-default", 2.5, 0.025, [], False, ""),
  ("haiku-low", 3, 0.02, [], False, ""),
  ("1017-medium", 2.5, 0.10, [], False, ""),
  ("1017-high", 2.5, 0.12, [], False, ""),
  ("glm-low", 2.7, 0.01, ["cheap-review"], False, ""),
  ("glm-high", 3, 0.03, ["strong-review"], False, " (2FP)"),
  ("gem38-low", 3, 0.05, [], False, ""),
  ("hydrogen-medium", 3, 0.19, [], False, " (FP)"),
  ("sonnet-medium", 3, 0.095, ["strong-review-alt"], False, ""),
  ("carbon-high", 2, 0.19, [], False, ""),
  ("argon-high", 2, 0.545, [], False, ""),
  ("astra", 2, 4.0, [], False, ""),
  ("kimi-medium", 2, 0.175, [], False, ""),
  ("1017-low", 2, 0.07, [], False, ""),
  ("terra-high", 2, 0.05, [], False, ""),
  ("sol-medium", 2, 0.095, [], False, ""),
  ("dsflash", 1.5, 0.03, [], False, ""),
  ("qwen-medium", 2, 0.49, [], False, ""),
  ("fable", 2, 4.0, [], False, ""),
 ]),
]

W, H = 1200, 540
L, R, T, B = 80, 60, 30, 60
X0, X1 = 0.004, 5.0   # log range in USD (fable/astra sit at ~$4/task)
Y1 = 0.0

# provider-prefixed model ids for the tooltips
FULLIDS = {
    "opus": "github-copilot/claude-opus-5.5",
    "sonnet": "github-copilot/claude-sonnet-5.5",
    "haiku": "github-copilot/claude-haiku-5.5",
    "fable": "github-copilot/claude-fable-5",
    "terra": "github-copilot/gpt-6.1-terra",
    "sol": "github-copilot/gpt-6.1-sol",
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

def svg(title, ymax, pts):
    key = next(k for k in REASONS if title.startswith(k))
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
    o.append(f'<text transform="translate(16 {(T+H-B)/2:.0f}) rotate(-90)" text-anchor="middle" fill="#333">score on this bench</text>')
    # frontier
    fr = frontier(pts)
    if len(fr) > 1:
        d = " ".join(f"{xpos(p[2]):.1f},{ypos(p[1], ymax):.1f}" for p in fr)
        o.append(f'<polyline points="{d}" fill="none" stroke="#6b7280" stroke-dasharray="5 4" stroke-width="1.3"/>')
    # points + labels: each label sits next to its own dot; pick the first
    # candidate position whose box does not overlap a placed label
    placed = []
    CH = 6.9  # px per character at 12px
    def box(cx, cy, w, anchor):
        x0 = cx if anchor == "start" else cx - w
        return (x0, cy - 11, x0 + w, cy + 3)
    def overlap(a, b):
        return not (a[2] <= b[0] or b[2] <= a[0] or a[3] <= b[1] or b[3] <= a[1])
    for entry in sorted(pts, key=lambda p: (p[2], -p[1])):
        name, s_, c, seats, single = entry[:5]
        extra = entry[5] if len(entry) > 5 else ""
        x, y = xpos(c), ypos(s_, ymax)
        seat = bool(seats)
        col = "#1d4ed8" if seat else "#9ca3af"
        # full model id (provider/model) + effort for the tooltip
        base, eff = name, "default"
        for e in ("default", "low", "medium", "high", "xhigh"):
            if name.endswith("-" + e):
                base, eff = name[: -(len(e) + 1)], e
                break
        full = FULLIDS[base]
        TIP = f"{full} ({eff}): {s_:g}{extra}" + (f" - ${c:g}/task" if c else "") + (f"\nseat: {', '.join(seats)}" if seats else "")
        why = REASONS[key].get(name, "")
        TIP = TIP + (f"\n{why}" if why else "")
        tip_el = f'<title>{html.escape(TIP)}</title>'
        # rich HTML tooltip (JS-enhanced via data-tip; <title> stays as fallback)
        seat_line = (f'<span style="color:#1d4ed8">seat: {html.escape(", ".join(seats))}</span>'
                     if seats else '<span style="color:#9ca3af">no seat</span>')
        TIPHTML = (f'<b>{html.escape(full)}</b> <i>{html.escape(eff)}</i><br>'
                   f'score {s_:g}{html.escape(extra)} · ${c:g}/task<br>'
                   f'{seat_line}'
                   + (f'<br><small>{html.escape(why)}</small>' if why else ''))
        data_tip = html.escape(TIPHTML, quote=True)
        if single:
            o.append(f'<circle class="pt" data-tip="{data_tip}" cx="{x:.1f}" cy="{y:.1f}" r="6" fill="#fff" stroke="{col}" stroke-width="2">{tip_el}</circle>')
        else:
            o.append(f'<circle class="pt" data-tip="{data_tip}" cx="{x:.1f}" cy="{y:.1f}" r="6" fill="{col}">{tip_el}</circle>')
        label = name  # model name (with effort qualifier) only; tooltip carries score/cost/seat/why
        w = len(label) * CH
        cands = [(x+9, y-4, "start"), (x+9, y+14, "start"), (x-9, y-4, "end"), (x-9, y+14, "end"),
                 (x+9, y-20, "start"), (x-9, y-20, "end"), (x+9, y+30, "start"), (x-9, y+30, "end")]
        chosen = None
        for cx, cy, anc in cands:
            bx = box(cx, cy, w, anc)
            if bx[0] < L or bx[2] > W - R + 40 or bx[1] < T - 5 or bx[3] > H - B:
                continue
            if any(overlap(bx, q) for q in placed):
                continue
            chosen = (cx, cy, anc, bx); break
        if chosen is None:
            cx, cy, anc = cands[0]; chosen = (cx, cy, anc, box(cx, cy, w, anc))
        cx, cy, anc, bx = chosen
        placed.append(bx)
        fill = "#1d4ed8" if seat else "#374151"
        o.append(f'<text class="pt" data-tip="{data_tip}" x="{cx:.1f}" y="{cy:.1f}" text-anchor="{"start" if anc=="start" else "end"}" fill="{fill}" stroke="#fff" stroke-width="3" paint-order="stroke">{html.escape(label)}{tip_el}</text>')
    o.append('</svg>')
    return "\n".join(o)

blocks = []
blocks.append('<section id="charts">\n<h2>Charts — who wins each decision bench</h2>\n<p class="note">Each dot is one model on one bench. Left = cheaper per task, up = higher score. <strong>Blue</strong> = holds a seat on this bench; grey = does not; hollow ring = single valid run (*). Dashed line = best trade-off frontier: no other model is both cheaper and better.</p>')
ORDER = ["Orchestration", "Design writing", "Design review", "Implementation", "Code review"]
CHARTS = sorted(CHARTS, key=lambda c: next(i for i, k in enumerate(ORDER) if c[0].startswith(k)))
for title, ymax, pts in CHARTS:
    fr = frontier(pts)
    blocks.append(f'<h3>{html.escape(title)}</h3>')
    blocks.append(svg(title, ymax, pts))
    blocks.append('<p class="note">blue = holds a seat (seat name on hover) · grey = no seat · hollow = single valid run (*) · dashed = best trade-off frontier (no model is both cheaper and better) · hover = provider/model id, effort, score, cost, seat, why</p>')
blocks.append('<h3>Why the best-and-cheaper model is not always the seat</h3>')
blocks.append('''<table class="matrix"><thead><tr><th>Seat</th><th>Best-and-cheaper candidate</th><th>Why it is not the seat</th></tr></thead><tbody>
<tr><td>cheap-design-review</td><td>minimax (8.5 at $0.04; xhigh posts 11.5)</td><td>Holds it. minimax-xhigh's 11.5/14 with 4 executed proofs is the best DR2 measured, but the seat stays on medium effort. Minimax is critique-only: its design-writing score fell from 8 to 2 across runs (two DNFs).</td></tr>
<tr><td>strong-design-review</td><td>minimax (8.5 at $0.04, above 1017's 5.5)</td><td>1017 held this rung on the 10-19 sweep (9/14); the complete grid measures it at 5.5. The seat is unchanged for now (dual rung with cheap-design, SPOF accepted); escalation still changes model family.</td></tr>
<tr><td>strong-design</td><td>opus (8.75 at ~$1.39, the top score)</td><td>Held by sonnet (7 at $0.40-1.26): opus gives 1.75 points for about twice the cost. opus holds strong-design-alternative2, the parking rung for good models we hesitate to drop.</td></tr>
<tr><td>strong-design-review-alt</td><td>carbon (10 at $0.15-0.23) and qwen (10 at ~$1.07)</td><td>argon holds the rung on a two-run 9.5. carbon's 10 is one valid run; qwen's 10 is an old (11-01) single run at ~$1/task with 0-7.5 variance elsewhere.</td></tr>
<tr><td>cheap-design</td><td>minimax (5 at $0.04, cheaper than 1017)</td><td>Score first, price second when scores differ reliably. 1017 gives 6.5 on two valid runs with no DNF (8.25 at high); minimax gives 8 then 2, with a false claim in the second run.</td></tr>
<tr><td>cheap-code</td><td>haiku-high (9 at $0.05)</td><td>The seat is haiku default (7.5 at $0.02-0.03): the cheap tier needs cheap, not best, and briefs &gt;90k tokens already pay a 5&times; cliff at default.</td></tr>
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
