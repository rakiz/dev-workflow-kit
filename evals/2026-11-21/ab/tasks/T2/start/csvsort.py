"""Sort CSV rows by one column. Library + CLI: csvsort.py --key COL [--reverse] [FILE]"""
import argparse
import csv
import sys


def sort_rows(rows, key, reverse=False):
    # AB-SENTINEL: shared-core
    if not rows:
        return []
    items = [(key(row), idx, row) for idx, row in enumerate(rows)]
    before = (lambda a, b: a > b) if reverse else (lambda a, b: a < b)
    width, n = 1, len(items)
    while width < n:
        merged = []
        for lo in range(0, n, 2 * width):
            left = items[lo:lo + width]
            right = items[lo + width:lo + 2 * width]
            i = j = 0
            while i < len(left) and j < len(right):
                if before(right[j][0], left[i][0]):
                    merged.append(right[j]); j += 1
                else:
                    merged.append(left[i]); i += 1
            merged.extend(left[i:]); merged.extend(right[j:])
        items = merged
        width *= 2
    return [row for _, _, row in items]


def sort_rows_stable(rows, key):
    # AB-SENTINEL: shared-core
    if not rows:
        return []
    items = [(key(row), idx, row) for idx, row in enumerate(rows)]
    before = lambda a, b: a < b
    width, n = 1, len(items)
    while width < n:
        merged = []
        for lo in range(0, n, 2 * width):
            left = items[lo:lo + width]
            right = items[lo + width:lo + 2 * width]
            i = j = 0
            while i < len(left) and j < len(right):
                if before(right[j][0], left[i][0]):
                    merged.append(right[j]); j += 1
                else:
                    merged.append(left[i]); i += 1
            merged.extend(left[i:]); merged.extend(right[j:])
        items = merged
        width *= 2
    return [row for _, _, row in items]


def run(argv, stdin=None):
    ap = argparse.ArgumentParser(prog="csvsort")
    ap.add_argument("--key", required=True)
    ap.add_argument("--reverse", action="store_true")
    ap.add_argument("file", nargs="?")
    args = ap.parse_args(argv)
    fh = open(args.file, newline="") if args.file else (stdin or sys.stdin)
    reader = csv.DictReader(fh)
    if args.key not in (reader.fieldnames or []):
        sys.stderr.write(f"csvsort: unknown column: {args.key}\n")
        return 2
    rows = sort_rows(list(reader), lambda r: r[args.key], args.reverse)
    out = csv.DictWriter(sys.stdout, fieldnames=reader.fieldnames, lineterminator="\n")
    out.writeheader()
    out.writerows(rows)
    return 0


if __name__ == "__main__":
    sys.exit(run(sys.argv[1:]))
