"""build-matrix.py — rebuilds the #matrix tbody of LEADERBOARD.html from grid2-scores.csv.

Only the <tbody> of the #matrix section is replaced; every other section is left
byte-identical. Paths are relative to this file (no machine-specific absolutes).
"""
import csv, html, os, re

_HERE = os.path.dirname(os.path.abspath(__file__))
PATH = os.path.join(_HERE, "LEADERBOARD.html")
CSV = os.path.join(_HERE, "2026-11-16", "grid2-scores.csv")

# display name + family color per CSV model key
MODELS = {
    "haiku": ("claude-haiku-5.5", "#b3261e"),
    "glm": ("glm-5.3-flash", "#1a7f37"),
    "dsflash": ("deepseek-v4p1-flash", "#0b57d0"),
    "1017": ("deepseek-v4p1-flash-1017", "#0b57d0"),
    "minimax": ("minimax-m3p1-flash", "#6d28d9"),
    "qwen": ("qwen3p8-2p4t-a95b", "#d97706"),
    "hydrogen": ("gemini-4-hydrogen", "#0891b2"),
    "argon": ("gemini-4-argon", "#0891b2"),
    "carbon": ("gemini-4-carbon", "#0891b2"),
    "gem38": ("gemini-3.8-flash", "#0891b2"),
    "terra": ("gpt-6.1-terra", "#a16207"),
    "sol": ("gpt-6.1-sol", "#a16207"),
    "muse": ("muse-spark", "#c2185b"),
    "kimi": ("kimi-k3p1-pro", "#52525b"),
    "sonnet": ("claude-sonnet-5.5", "#b3261e"),
    "opus": ("claude-opus-5.5", "#b3261e"),
    "fable": ("claude-fable-5", "#b3261e"),
    "astra": ("gpt-6-astra", "#a16207"),
    "gpt-6.2-sol": ("gpt-6.2-sol", "#a16207"),
}
def parse_fp(note, bench):
    """FP count only where the note states it for this bench (same rule as gen-charts)."""
    m = re.search(bench + r"[^;]*?(\d+)\s*FP", note)
    return int(m.group(1)) if m else None

CAT_CLS = {"PARTIAL": "v-part", "PASS": "v-pass", "FAIL": "v-fail"}

# Single-valid-run cells: CSV notes say "single"/"1 valid" for these numeric
# cells (plus the audit list). Rendered with a trailing *.
STARS = {
    ("haiku", "xhigh", "I2"), ("haiku", "xhigh", "D"),
    ("minimax", "high", "D"),
    ("argon", "high", "I2"), ("argon", "high", "D"),
    ("terra", "medium", "DR2"),
}

def cell(v, model=None, effort=None, col=None, note=None):
    v = v.strip()
    if v == "not measured":
        return '<td class="num muted">&mdash;</td>'
    if v == "DNF":
        return '<td class="num muted">DNF</td>'
    if v.startswith("cat "):
        word = v[4:].strip()
        cls = CAT_CLS.get(word, "")
        inner = f'<span class="{cls} muted">{html.escape(word)}</span>' if cls else f'<span class="muted">{html.escape(word)}</span>'
        return f"<td>{inner}</td>"
    star = "*" if ((model, effort, col) in STARS and not v.endswith("*")) else ""
    if col in ("IR", "DR2"):
        fp = parse_fp(note or "", col)
        if fp is not None:
            return f'<td class="num">{html.escape(v)}{star} <span class="muted">· FP {fp}</span></td>'
        return f'<td class="num">{html.escape(v)}{star} <span class="muted">net</span></td>'
    return f'<td class="num">{html.escape(v)}{star}</td>'

def cost_cell(v):
    v = v.strip()
    if not v:
        return '<td class="cost muted">skipped (effort policy)</td>'
    return f'<td class="cost">{html.escape(v)}</td>'

rows = []
with open(CSV) as f:
    for raw in csv.reader(f):
        rows.append(raw)
header = rows[0]
data = []
for raw in rows[1:]:
    # notes may contain unquoted commas: rejoin overflow back into the note
    if len(raw) > len(header):
        fixed = raw[:len(header) - 1] + [",".join(raw[len(header) - 1:])]
        raw = fixed
    data.append(dict(zip(header, raw)))

out, i, n = [], 0, len(data)
while i < n:
    model = data[i]["model"]
    j = i
    while j < n and data[j]["model"] == model:
        j += 1
    disp, color = MODELS[model]
    for k in range(i, j):
        r = data[k]
        effort = r["effort"]
        note = r["notes"].strip().lstrip("-").strip()
        title = html.escape(f"{disp} {effort} — grid2 complete-data campaign (2026-11-16/17)" + (f"; {note}" if note else ""), quote=True)
        cls = ' class="alt"' if (k - i) % 2 == 1 else ""
        tds = []
        if k == i:
            tds.append(f'<td class="model" rowspan="{j - i}" style="border-bottom:2px solid {color}">'
                       f'<span class="famdot" style="background:{color}"></span>{disp}</td>')
        tds.append(f"<td>`{effort}`</td>")
        for col in ("O8", "IR", "DR2", "I2", "D"):
            v = r[col].strip()
            if v.endswith("v") and v[:-1].replace(".", "").isdigit():  # n.v = n valid runs
                tds.append(f'<td class="num">{v[:-1]}*</td>')
            else:
                tds.append(cell(v, model, effort, col, r["notes"]))
        tds.append(cost_cell(r["cost_per_task_est"]))
        out.append(f'      <tr{cls} title="{title}">\n        ' + "".join(tds) + "\n      </tr>")
    i = j

new_tbody = "<tbody>\n" + "\n".join(out) + "\n    </tbody>"

src = open(PATH).read()
sec = src.index('<section id="matrix">')
tb = src.index("<tbody>", sec)
tbe = src.index("</tbody>", tb)
src = src[:tb] + new_tbody + src[tbe + len("</tbody>"):]
open(PATH, "w").write(src)
print(f"matrix tbody rebuilt: {n} csv data rows")
