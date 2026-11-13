"""reportgen — summarize CSV inputs through per-column transforms.

Reads every *.csv in the input directory, applies the per-column
transforms from a rules file, and writes a JSON summary plus an HTML
rendering of the same summary to the output directory. A content cache
(cache/state.json) lets unchanged inputs skip re-transformation on later
runs.

Usage:
    python3 reportgen.py [--rules rules.example.toml] [--input input]
                         [--output output] [--cache cache/state.json]
"""

import argparse
import csv
import html
import json
import os
import sys

import cache
import transforms

DEFAULT_RULES = "rules.example.toml"
DEFAULT_INPUT = "input"
DEFAULT_OUTPUT = "output"


class TransformFailure(transforms.TransformError):
    """Raised by run() when any cell failed its transform. Nothing is
    written in that case: no report and no cache state."""


def load_rules(path):
    """Load a rules file. Only the [transforms] table is read; it maps
    column name -> transform name. Other tables are reserved for future
    report options and ignored."""
    rules = {}
    section = None
    with open(path, "r", encoding="utf-8") as fh:
        for lineno, raw in enumerate(fh, start=1):
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("[") and line.endswith("]"):
                section = line[1:-1].strip()
                continue
            if "=" not in line:
                raise ValueError('%s:%d: expected key = "value"' % (path, lineno))
            key, _, value = line.partition("=")
            if section == "transforms":
                rules[key.strip().strip('"')] = value.strip().strip('"')
    return rules


def load_rows(path):
    """Return (header, data_rows). Blank physical lines are not rows;
    quoted cells may span physical lines."""
    with open(path, "r", encoding="utf-8", newline="") as fh:
        reader = csv.reader(fh)
        header = next(reader)
        return header, [row for row in reader if row]


def summarize_file(header, data_rows, rules):
    """Column-level summary of one input file: per column, the non-empty
    cell count, the distinct count over transformed values, the first
    three distinct values in sorted order, and the numeric sum when every
    transformed value is a float. Cells that fail their transform are
    recorded in `skipped_rows`; run() refuses to emit anything from a
    summary that has any."""
    columns = {}
    skipped_rows = []
    for row_no, row in enumerate(data_rows, start=2):
        for i, col in enumerate(header):
            raw = row[i] if i < len(row) else ""
            tname = rules.get(col)
            if tname:
                try:
                    value = transforms.apply(tname, raw)
                except transforms.TransformError as exc:
                    skipped_rows.append(
                        {"row": row_no, "column": col, "reason": str(exc)})
                    continue
            else:
                value = raw
            stats = columns.setdefault(col, {"non_empty": 0, "values": set()})
            if raw != "":
                stats["non_empty"] += 1
            stats["values"].add(value)
    out = {}
    for col in sorted(columns):
        stats = columns[col]
        values = stats["values"]
        entry = {"non_empty": stats["non_empty"], "distinct": len(values),
                 "sample": sorted(values, key=str)[:3]}
        numeric = [v for v in values if isinstance(v, float)]
        if numeric and len(numeric) == len(values):
            entry["numeric_sum"] = round(sum(sorted(numeric)), 2)
        out[col] = entry
    return {"columns": out, "skipped_rows": skipped_rows}


def render_html(report):
    """Render the summary as a standalone HTML page, one table per file."""
    parts = ["<!doctype html>",
             "<html><head><meta charset='utf-8'>",
             "<title>reportgen summary</title></head><body>"]
    for name in sorted(report["files"]):
        res = report["files"][name]
        parts.append("<h1>%s</h1>" % html.escape(name))
        parts.append("<p>%d rows</p>" % res["rows"])
        parts.append("<table border='1'>")
        parts.append("<tr><th>column</th><th>non_empty</th>"
                     "<th>distinct</th><th>sample</th></tr>")
        summary = res["summary"]["columns"]
        for col in sorted(summary):
            stats = summary[col]
            sample = ", ".join(str(v) for v in stats["sample"])
            parts.append("<tr><td>%s</td><td>%d</td><td>%d</td><td>%s</td></tr>"
                         % (html.escape(col), stats["non_empty"],
                            stats["distinct"], html.escape(sample)))
        parts.append("</table>")
    parts.append("</body></html>")
    return "\n".join(parts)


def run(rules_path, input_dir, output_dir, cache_path):
    """Run one full pass over the input directory and write the report."""
    rules = load_rules(rules_path)
    rules_fp = cache.rules_fingerprint(rules)
    state = cache.load_state(cache_path)

    names = sorted(n for n in os.listdir(input_dir) if n.endswith(".csv"))
    results = {}
    pending = {}
    failures = []
    for name in names:
        path = os.path.join(input_dir, name)
        digest = cache.file_digest(path)
        entry = state.get(name)
        header, data_rows = load_rows(path)
        print("reportgen: %s: parsed %d rows" % (name, len(data_rows)))
        if (isinstance(entry, dict) and entry.get("digest") == digest
                and entry.get("rules_fp") == rules_fp
                and isinstance(entry.get("rows"), int)
                and isinstance(entry.get("summary"), dict)
                and not entry["summary"].get("skipped_rows")):
            results[name] = {"digest": digest, "rows": entry["rows"],
                             "summary": entry["summary"]}
        else:
            summary = summarize_file(header, data_rows, rules)
            for skipped in summary["skipped_rows"]:
                failures.append("%s: row %d, column %r: %s" % (
                    name, skipped["row"], skipped["column"], skipped["reason"]))
            results[name] = {"digest": digest, "rows": len(data_rows),
                             "summary": summary}
            pending[name] = cache.make_entry(
                path, digest, summary, rules_fp, rows=len(data_rows))

    if failures:
        # All-or-nothing: no report, no cache state from a partial pass.
        raise TransformFailure(
            "%d cell(s) failed their transform; nothing written. First: %s"
            % (len(failures), "; ".join(failures[:5])))

    report = {"rules": rules_path,
              "total_rows": sum(r["rows"] for r in results.values()),
              "files": results}
    # Render everything before touching disk so a crash cannot leave a
    # half-written report pair.
    report_json = json.dumps(report, indent=2, sort_keys=True) + "\n"
    report_html = render_html(report)
    cache.save_state(pending, path=cache_path)
    os.makedirs(output_dir, exist_ok=True)
    with open(os.path.join(output_dir, "report.json"), "w", encoding="utf-8") as fh:
        fh.write(report_json)
    with open(os.path.join(output_dir, "report.html"), "w", encoding="utf-8") as fh:
        fh.write(report_html)
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="summarize CSV inputs through per-column transforms")
    parser.add_argument("--rules", default=DEFAULT_RULES,
                        help="rules TOML file mapping columns to transforms")
    parser.add_argument("--input", default=DEFAULT_INPUT,
                        help="directory of input CSV files")
    parser.add_argument("--output", default=DEFAULT_OUTPUT,
                        help="directory for report.json / report.html")
    parser.add_argument("--cache", default=cache.DEFAULT_CACHE_PATH,
                        help="path of the cache state file")
    args = parser.parse_args(argv)
    return run(args.rules, args.input, args.output, args.cache)


if __name__ == "__main__":
    try:
        main()
    except TransformFailure as exc:
        sys.exit("reportgen: error: %s" % exc)
