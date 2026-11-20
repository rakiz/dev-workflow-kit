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


class ValidationError(Exception):
    """Raised when a summary was derived from an incomplete transform
    pass (at least one cell failed its transform)."""


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
    skipped and recorded in `skipped_rows`."""
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


def generated_from(header, data_rows, rules):
    """Number of rules-mapped columns that have at least one non-empty
    cell in the file."""
    non_empty = set()
    for row in data_rows:
        for i, col in enumerate(header):
            if i < len(row) and row[i] != "":
                non_empty.add(col)
    return sum(1 for col in header if col in rules and col in non_empty)


def validate_summary(summary):
    """Reject a summary that was derived from cells that failed their
    transform."""
    skipped = summary.get("skipped_rows") or []
    if skipped:
        first = skipped[0]
        raise ValidationError(
            "%d cell(s) failed their transform (first: row %s, column %s)"
            % (len(skipped), first["row"], first["column"]))


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
            sample = ", ".join(html.escape(str(v)) for v in stats["sample"])
            parts.append("<tr><td>%s</td><td>%d</td><td>%d</td><td>%s</td></tr>"
                         % (html.escape(col), stats["non_empty"],
                            stats["distinct"], sample))
        parts.append("</table>")
    parts.append("</body></html>")
    return "\n".join(parts)


def run(rules_path, input_dir, output_dir, cache_path):
    """Run one full pass over the input directory and write the report."""
    state = cache.load_state(cache_path)
    rules = load_rules(rules_path)
    rules_fp = cache.rules_fingerprint(rules)

    names = sorted(n for n in os.listdir(input_dir) if n.endswith(".csv"))
    results = {}
    pending = {}
    for name in names:
        path = os.path.join(input_dir, name)
        digest = cache.file_digest(path)
        entry = state.get(name)
        header, data_rows = load_rows(path)
        print("reportgen: %s: parsed %d rows" % (name, len(data_rows)))
        if (entry and entry["digest"] == digest
                and entry.get("rules_fp") == rules_fp
                and entry.get("registry_version") == cache.REGISTRY_VERSION):
            results[name] = {"digest": digest, "rows": entry["rows"],
                             "generated_from": entry["generated_from"],
                             "summary": entry["summary"]}
        else:
            summary = summarize_file(header, data_rows, rules)
            results[name] = {"digest": digest, "rows": len(data_rows),
                             "generated_from": generated_from(header, data_rows, rules),
                             "summary": summary}
            pending[name] = cache.make_entry(path, digest, len(data_rows),
                                             summary, rules, rules_fp)

    for name in sorted(results):
        validate_summary(results[name]["summary"])

    report = {"rules": rules_path,
              "total_rows": sum(r["rows"] for r in results.values()),
              "files": results}
    os.makedirs(output_dir, exist_ok=True)
    with open(os.path.join(output_dir, "report.html"), "w", encoding="utf-8") as fh:
        fh.write(render_html(report))
    with open(os.path.join(output_dir, "report.json"), "w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=2, sort_keys=True)
        fh.write("\n")
    cache.save_state(pending, path=cache_path)
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
    try:
        run(args.rules, args.input, args.output, args.cache)
    except ValidationError as exc:
        sys.stderr.write("reportgen: warning: %s\n" % exc)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
