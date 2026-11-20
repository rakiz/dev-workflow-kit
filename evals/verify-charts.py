#!/usr/bin/env python3
"""verify-charts.py — dot-by-dot audit of LEADERBOARD.html against grid2-scores.csv.

Parses the 5 SVGs in the #charts section of LEADERBOARD.html, recomputes each
dot's expected (x, y, color, fill) from the score CSV using the SAME math as
gen-charts.py (imported, not duplicated: log-x by cost column, linear-y by
score, blue/grey by the SEATS map, filled/hollow by run count), and asserts
equality dot by dot, in generation order.

It also audits the IR/DR2 tooltip lines: each findings/FP line is recomputed
from fp-findings.tsv (extract-fp-findings.py output) and from the official
note-derived FP, and must match the published tooltip. A cell whose official
record states an FP must publish exactly that FP - a lower panel FP is a
published-number regression, never a match.

Prints a table bench -> checked/ok. Exits non-zero (fail-closed) on any
mismatch, on a dot-count mismatch, or if the CSV/HTML cannot be parsed.
"""
import csv
import importlib.util
import os
import re
import sys

_spec = importlib.util.spec_from_file_location(
    "gen_charts", os.path.join(os.path.dirname(os.path.abspath(__file__)), "gen-charts.py"))
gc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(gc)
BENCHES, CSVPATH, PATH = gc.BENCHES, gc.CSVPATH, gc.PATH
load_dots, xpos, ypos = gc.load_dots, gc.xpos, gc.ypos


def parse_svg_dots(svg):
    """The <circle class="pt"> dots of one SVG, in document order:
    (cx, cy, color, hollow, data-tip)."""
    dots = []
    for m in re.finditer(r'<circle class="pt"[^>]*/>', svg):
        tag = m.group(0)
        cx = float(re.search(r'cx="([-\d.]+)"', tag).group(1))
        cy = float(re.search(r'cy="([-\d.]+)"', tag).group(1))
        hollow = 'fill="#fff"' in tag
        col = (re.search(r'stroke="(#[0-9a-f]+)"', tag).group(1) if hollow
               else re.search(r'fill="(#[0-9a-f]+)"', tag).group(1))
        tip = re.search(r'data-tip="([^"]*)"', tag)
        dots.append((round(cx, 1), round(cy, 1), col, hollow,
                     unescape_tip(tip.group(1)) if tip else ""))
    return dots


def unescape_tip(tip):
    """The tooltip as the browser shows it (the attribute is HTML-escaped)."""
    import html as h
    return h.unescape(tip)


def expected_dots(pts, bench, ymax):
    """What svg() in gen-charts.py would draw: same iteration order
    (sorted by cost asc, score desc), same xpos/ypos/color/fill math."""
    out = []
    for name, s, cost, seats, single, note, one_fam, meta in sorted(pts, key=lambda p: (p[2], -p[1])):
        x, y = xpos(cost), ypos(s, ymax)
        here = [1 for n, b in seats if b == bench]
        col = "#1d4ed8" if here else "#9ca3af"
        out.append((round(x, 1), round(y, 1), col, bool(single)))
    return out


def check_fp_lines(svg, pts, bench, failures, ff_cells, notes):
    """Every IR/DR2 dot must publish the findings/FP line that the run record
    supports: the findings/FP means recomputed from fp-findings.tsv, and the
    official FP the CSV note states (which always wins over the panel FP).

    The numbers are recomputed here from the TSV and the CSV note, not read
    back from the generator, so a wrong number in the tooltip fails here."""
    tips = [d[4] for d in parse_svg_dots(svg)]
    ordered = sorted(pts, key=lambda p: (p[2], -p[1]))
    if len(tips) != len(ordered):
        failures.append(f"{bench}: {len(tips)} tooltips for {len(ordered)} dots")
        return 0
    ok = 0
    for (name, s, cost, seats, single, note, one_fam, meta), tip in zip(ordered, tips):
        want = gc.ff_line(meta, bench)
        if not want:
            continue
        if want not in tip:
            failures.append(f"{bench} {name}: tooltip does not carry the expected "
                            f"findings/FP line {want!r}")
            continue
        # --- independent audit of the numbers ---------------------------
        cell = ff_cells.get((bench, name_model(name), name_effort(name)))
        official = notes.get((bench, name_model(name), name_effort(name)))
        m = re.search(r"findings (\d+(?:\.\d+)?)", tip)
        if cell and cell["findings"] is not None:
            if not m or abs(float(m.group(1)) - cell["findings"]) > 0.051:
                failures.append(f"{bench} {name}: published findings {m and m.group(1)} "
                                f"!= fp-findings.tsv mean {cell['findings']}")
                continue
        elif m:
            failures.append(f"{bench} {name}: publishes findings {m.group(1)} but "
                            f"fp-findings.tsv holds none for that cell")
            continue
        fm = re.search(r"FP (\d+(?:\.\d+)?)(?: \(official record\))?"
                       r"(?: \((\d+)/(\d+) readers\))?", tip)
        if official is not None:
            # the official record states an FP: exactly that FP is published
            if not fm or abs(float(fm.group(1)) - official) > 1e-9:
                failures.append(f"{bench} {name}: published FP {fm and fm.group(1)} "
                                f"!= official record {official}")
                continue
            if fm.group(2) is not None:
                failures.append(f"{bench} {name}: publishes panel reader counts for a "
                                f"cell whose FP comes from the official record")
                continue
        elif cell and cell["fp"] is not None:
            if not fm or abs(float(fm.group(1)) - cell["fp"]) > 0.051:
                failures.append(f"{bench} {name}: published FP {fm and fm.group(1)} "
                                f"!= fp-findings.tsv mean {cell['fp']}")
                continue
            if fm.group(2) is not None and (int(fm.group(2)) != cell["fp_readers"]
                                            or int(fm.group(3)) != cell["readers"]):
                failures.append(f"{bench} {name}: published FP reader counts "
                                f"{fm.group(2)}/{fm.group(3)} != fp-findings.tsv "
                                f"{cell['fp_readers']}/{cell['readers']}")
                continue
        elif fm:
            failures.append(f"{bench} {name}: publishes FP {fm.group(1)} but no FP is "
                            f"recorded for that cell")
            continue
        ok += 1
    return ok


def name_model(name):
    """'opus-default' -> 'opus'; 'opus' -> 'opus' (the CSV model/effort pair)."""
    if name in gc.SEATS or ("-" not in name):
        return name
    for e in ("default", "low", "medium", "high", "xhigh"):
        if name.endswith("-" + e):
            return name[: -(len(e) + 1)]
    return name


def name_effort(name):
    if name in gc.SEATS or ("-" not in name):
        return "default"
    for e in ("default", "low", "medium", "high", "xhigh"):
        if name.endswith("-" + e):
            return e
    return "default"


def load_ff_cells():
    """cell -> findings/FP means + reader counts, recomputed from
    fp-findings.tsv (the extractor's withheld rows are not published)."""
    if not os.path.exists(gc.FF_PATH):
        return {}
    run_cell = {}
    with open(gc.RUNSCORES, encoding="utf-8", newline="") as fh:
        for r in csv.DictReader(fh, delimiter="\t"):
            if r["status"] == "scored" and r["bench"] in ("IR", "DR2"):
                run_cell[r["run_id"]] = (r["bench"], r["model"].strip(), r["effort"].strip())
    cells = {}
    with open(gc.FF_PATH, encoding="utf-8", newline="") as fh:
        for r in csv.DictReader(fh, delimiter="\t"):
            if r["row_kind"] != "mean" or r["run_id"] not in run_cell:
                continue
            if r.get("qual") in ("contradicts", "none"):
                continue
            c = cells.setdefault(run_cell[r["run_id"]], {"f": [], "p": [], "readers": 0,
                                                          "fp_readers": 0})
            c["readers"] += int(r.get("n_readers") or 0)
            c["fp_readers"] += int(r.get("n_fp") or 0)
            if r["findings"]:
                c["f"].append(float(r["findings"]))
            if r["fp"]:
                c["p"].append(float(r["fp"]))
    for c in cells.values():
        c["findings"] = sum(c["f"]) / len(c["f"]) if c["f"] else None
        c["fp"] = sum(c["p"]) / len(c["p"]) if c["p"] else None
    return cells


def load_note_fps():
    """cell -> the official FP the CSV note states (the established record)."""
    out = {}
    with open(gc.CSVPATH, encoding="utf-8", newline="") as fh:
        for r in csv.DictReader(fh):
            model, eff = r["model"].strip(), r["effort"].strip()
            for bench, col in (("IR", "IR"), ("DR2", "DR2")):
                m = re.search(bench + r"[^;]*?(\d+)\s*FP", r.get("notes") or "")
                if m:
                    out[(bench, model, eff)] = int(m.group(1))
    return out


def main():
    html = open(PATH).read()
    start = html.index('<section id="charts">')
    end = html.index('<section id="ops">')   # score scatters only; #ops has its own two SVGs
    section = html[start:end]
    svgs = re.findall(r'<svg.*?</svg>', section, re.S)
    if len(svgs) != len(BENCHES):
        print(f"FAIL: expected {len(BENCHES)} SVGs in #charts, found {len(svgs)}")
        return 1

    total_checked = total_ok = 0
    total_ff = total_ff_ok = 0
    ff_cells = load_ff_cells()
    note_fps = load_note_fps()
    failures = []
    print(f"{'bench':<12} {'checked':>7} {'ok':>7}  {'findings/FP':>12}")
    for svg, (key, title, ymax, column, ylabel, ref, bench) in zip(svgs, BENCHES):
        # the SVG must belong to this bench: its aria-label is the chart title
        label = re.search(r'aria-label="([^"]+)"', svg)
        if not label or not htmlish_equal(label.group(1), title):
            failures.append(f"{bench}: SVG aria-label {label and label.group(1)!r} != chart title")
        pts = load_dots(column)
        actual = parse_svg_dots(svg)
        exp = expected_dots(pts, bench, ymax)
        ok = 0
        if len(actual) != len(exp):
            failures.append(f"{bench}: dot count {len(actual)} != expected {len(exp)}")
        for i, (a, e) in enumerate(zip(actual, exp)):
            ax, ay, acol, ahollow = a[0], a[1], a[2], a[3]
            ex, ey, ecol, ehollow = e
            if abs(ax - ex) > 0.05 or abs(ay - ey) > 0.05 or acol != ecol or ahollow != ehollow:
                failures.append(
                    f"{bench} dot {i}: got (x={ax}, y={ay}, color={acol}, hollow={ahollow})"
                    f" expected (x={ex}, y={ey}, color={ecol}, hollow={ehollow})")
            else:
                ok += 1
        # one-family marker: every cell flagged one_fam in the CSV carries a "~" label
        # suffix, and no other label does (the marker is the only "~" on a label)
        want_tilde = sum(1 for p in pts if p[6])
        got_tilde = len(re.findall(r'<text class="pt"[^>]*>[^<]*~</text>', svg))
        if got_tilde != want_tilde:
            failures.append(f"{bench}: one-family '~' labels {got_tilde} != expected {want_tilde}")
        # findings/FP tooltip audit (IR and DR2 only)
        ff_ok = ff_checked = 0
        if column in ("IR", "DR2"):
            ff_ok = check_fp_lines(svg, pts, column, failures, ff_cells, note_fps)
            ff_checked = len([p for p in pts if gc.ff_line(p[7], column)])
            total_ff += ff_checked
            total_ff_ok += ff_ok
        total_checked += len(exp)
        total_ok += ok
        print(f"{bench:<12} {len(exp):>7} {ok:>7}  {ff_ok:>5}/{ff_checked:<6}")

    print(f"{'TOTAL':<12} {total_checked:>7} {total_ok:>7}")
    if failures:
        print("\nMISMATCHES (fail-closed):")
        for f in failures:
            print("  " + f)
        return 1
    print(f"\nOK: {total_ok}/{total_checked} dots match grid2-scores.csv "
          f"({CSVPATH}) with the gen-charts math")
    print(f"OK: {total_ff_ok}/{total_ff} IR/DR2 tooltips carry the findings/FP line "
          f"of fp-findings.tsv and the official note-derived FP")
    return 0


def htmlish_equal(aria_label, title):
    """svg() writes the title into aria-label via html.escape — compare on
    the escaped form."""
    import html as h
    return h.escape(title) == aria_label


if __name__ == "__main__":
    sys.exit(main())
