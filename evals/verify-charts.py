#!/usr/bin/env python3
"""verify-charts.py — dot-by-dot audit of LEADERBOARD.html against grid2-scores.csv.

Parses the 5 SVGs in the #charts section of LEADERBOARD.html, recomputes each
dot's expected (x, y, color, fill) from the score CSV using the SAME math as
gen-charts.py (imported, not duplicated: log-x by cost column, linear-y by
score, blue/grey by the SEATS map, filled/hollow by run count), and asserts
equality dot by dot, in generation order.

Prints a table bench -> checked/ok. Exits non-zero (fail-closed) on any
mismatch, on a dot-count mismatch, or if the CSV/HTML cannot be parsed.
"""
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
    (cx, cy, color, hollow)."""
    dots = []
    for m in re.finditer(r'<circle class="pt"[^>]*/>', svg):
        tag = m.group(0)
        cx = float(re.search(r'cx="([-\d.]+)"', tag).group(1))
        cy = float(re.search(r'cy="([-\d.]+)"', tag).group(1))
        hollow = 'fill="#fff"' in tag
        col = (re.search(r'stroke="(#[0-9a-f]+)"', tag).group(1) if hollow
               else re.search(r'fill="(#[0-9a-f]+)"', tag).group(1))
        dots.append((cx, cy, col, hollow))
    return dots


def expected_dots(pts, bench, ymax):
    """What svg() in gen-charts.py would draw: same iteration order
    (sorted by cost asc, score desc), same xpos/ypos/color/fill math."""
    out = []
    for name, s, cost, seats, single, note, one_fam in sorted(pts, key=lambda p: (p[2], -p[1])):
        x, y = xpos(cost), ypos(s, ymax)
        here = [1 for n, b in seats if b == bench]
        col = "#1d4ed8" if here else "#9ca3af"
        out.append((round(x, 1), round(y, 1), col, bool(single)))
    return out


def main():
    html = open(PATH).read()
    start = html.index('<section id="charts">')
    end = html.index('<section id="codes">')
    section = html[start:end]
    svgs = re.findall(r'<svg.*?</svg>', section, re.S)
    if len(svgs) != len(BENCHES):
        print(f"FAIL: expected {len(BENCHES)} SVGs in #charts, found {len(svgs)}")
        return 1

    total_checked = total_ok = 0
    failures = []
    print(f"{'bench':<12} {'checked':>7} {'ok':>7}")
    for svg, (key, title, ymax, column, ylabel, ref, bench) in zip(svgs, BENCHES):
        # the SVG must belong to this bench: its aria-label is the chart title
        label = re.search(r'aria-label="([^"]+)"', svg)
        if not label or not htmlish_equal(label.group(1), title):
            failures.append(f"{bench}: SVG aria-label {label and label.group(1)!r} != chart title")
        actual = parse_svg_dots(svg)
        exp = expected_dots(load_dots(column), bench, ymax)
        ok = 0
        if len(actual) != len(exp):
            failures.append(f"{bench}: dot count {len(actual)} != expected {len(exp)}")
        for i, (a, e) in enumerate(zip(actual, exp)):
            ax, ay, acol, ahollow = a
            ex, ey, ecol, ehollow = e
            if abs(ax - ex) > 0.05 or abs(ay - ey) > 0.05 or acol != ecol or ahollow != ehollow:
                failures.append(
                    f"{bench} dot {i}: got (x={ax}, y={ay}, color={acol}, hollow={ahollow})"
                    f" expected (x={ex}, y={ey}, color={ecol}, hollow={ehollow})")
            else:
                ok += 1
        # one-family marker: every cell flagged one_fam in the CSV carries a "~" label
        # suffix, and no other label does (the marker is the only "~" on a label)
        want_tilde = sum(1 for p in load_dots(column) if p[6])
        got_tilde = len(re.findall(r'<text class="pt"[^>]*>[^<]*~</text>', svg))
        if got_tilde != want_tilde:
            failures.append(f"{bench}: one-family '~' labels {got_tilde} != expected {want_tilde}")
        total_checked += len(exp)
        total_ok += ok
        print(f"{bench:<12} {len(exp):>7} {ok:>7}  (~ labels {got_tilde}/{want_tilde})")

    print(f"{'TOTAL':<12} {total_checked:>7} {total_ok:>7}")
    if failures:
        print("\nMISMATCHES (fail-closed):")
        for f in failures:
            print("  " + f)
        return 1
    print(f"\nOK: {total_ok}/{total_checked} dots match grid2-scores.csv "
          f"({CSVPATH}) with the gen-charts math")
    return 0


def htmlish_equal(aria_label, title):
    """svg() writes the title into aria-label via html.escape — compare on
    the escaped form."""
    import html as h
    return h.escape(title) == aria_label


if __name__ == "__main__":
    sys.exit(main())
