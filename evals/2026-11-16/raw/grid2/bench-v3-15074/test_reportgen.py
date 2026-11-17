"""Baseline suite for reportgen: transforms, rules loading, end-to-end
report shape, and cache state bookkeeping."""

import json
import os
import shutil
import tempfile
import unittest
import unittest.mock

import cache
import reportgen
import transforms

BASE = os.path.dirname(os.path.abspath(__file__))
INPUT_DIR = os.path.join(BASE, "input")
RULES = os.path.join(BASE, "rules.example.toml")


class TransformTests(unittest.TestCase):
    def test_trim_upper_lower(self):
        self.assertEqual(transforms.apply("trim", "  x "), "x")
        self.assertEqual(transforms.apply("upper", "aB"), "AB")
        self.assertEqual(transforms.apply("lower", "aB"), "ab")

    def test_currency_amount(self):
        self.assertEqual(transforms.apply("currency_amount", "$1,234.5"), 1234.5)
        with self.assertRaises(transforms.TransformError):
            transforms.apply("currency_amount", "see invoice")

    def test_round2(self):
        self.assertEqual(transforms.apply("round2", "3.14159"), 3.14)
        with self.assertRaises(transforms.TransformError):
            transforms.apply("round2", "n/a")

    def test_date_iso(self):
        self.assertEqual(transforms.apply("date_iso", "01/15/2026"), "2026-01-15")
        with self.assertRaises(transforms.TransformError):
            transforms.apply("date_iso", "2026-01-15")

    def test_unknown_transform_name(self):
        with self.assertRaises(transforms.TransformError):
            transforms.apply("nope", "x")

    def test_boolean_maps_affirmative_and_negative_forms(self):
        for raw in ("yes", "YES", " True ", "tRuE"):
            self.assertEqual(transforms.apply("boolean", raw), 1.0)
        for raw in ("no", "No", "FALSE", " false"):
            self.assertEqual(transforms.apply("boolean", raw), 0.0)

    def test_boolean_rejects_other_input(self):
        for raw in ("", "maybe", "1", "0", "y", "nope"):
            with self.assertRaises(transforms.TransformError):
                transforms.apply("boolean", raw)

    def test_date_iso_rejects_non_ascii_digits_as_transform_error(self):
        # '\u00b9' passes str.isdigit() but int() rejects it; it must surface
        # as TransformError, not as an unhandled ValueError.
        with self.assertRaises(transforms.TransformError):
            transforms.apply("date_iso", "\u00b9/15/2026")


class RulesTests(unittest.TestCase):
    def test_rules_loader_ignores_other_tables(self):
        tmp = tempfile.mkdtemp(prefix="rg3-rules-")
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        path = os.path.join(tmp, "rules.toml")
        with open(path, "w") as fh:
            fh.write('# rules\n[report]\ntitle = "x"\n\n[transforms]\nname = "upper"\n')
        self.assertEqual(reportgen.load_rules(path), {"name": "upper"})

    def test_shipped_rules_load(self):
        rules = reportgen.load_rules(RULES)
        self.assertEqual(rules["amount"], "currency_amount")
        self.assertEqual(rules["date"], "date_iso")
        self.assertNotIn("notes", rules)


class EndToEndTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="rg3-e2e-")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.out = os.path.join(self.tmp, "out")
        self.cache_path = os.path.join(self.tmp, "cache", "state.json")

    def run_tool(self, rules=RULES, input_dir=INPUT_DIR):
        return reportgen.run(rules, input_dir, self.out, self.cache_path)

    def test_shipped_inputs_report(self):
        report = self.run_tool()
        self.assertEqual(report["total_rows"], 12012)
        self.assertEqual(set(report["files"]), {
            "big_transactions.csv", "small_devices.csv",
            "small_employees.csv", "small_transactions.csv"})
        tx = report["files"]["small_transactions.csv"]["summary"]["columns"]
        self.assertEqual(tx["merchant"]["distinct"], 3)
        self.assertEqual(tx["amount"]["numeric_sum"], 275.59)
        emp = report["files"]["small_employees.csv"]["summary"]["columns"]
        self.assertEqual(emp["salary"]["numeric_sum"], 430000.0)
        dev = report["files"]["small_devices.csv"]["summary"]["columns"]
        self.assertEqual(dev["device_id"]["distinct"], 3)
        self.assertTrue(os.path.exists(os.path.join(self.out, "report.html")))

    def test_temp_input_end_to_end(self):
        inp = os.path.join(self.tmp, "in")
        os.makedirs(inp)
        with open(os.path.join(inp, "t.csv"), "w") as fh:
            fh.write("item,label\n1,alpha\n2,beta\n")
        rules_path = os.path.join(self.tmp, "rules.toml")
        with open(rules_path, "w") as fh:
            fh.write('[transforms]\nitem = "round2"\n')
        report = self.run_tool(rules=rules_path, input_dir=inp)
        self.assertEqual(report["total_rows"], 2)
        cols = report["files"]["t.csv"]["summary"]["columns"]
        self.assertEqual(cols["item"]["numeric_sum"], 3.0)
        self.assertEqual(cols["label"]["sample"], ["alpha", "beta"])

    def test_boolean_column_end_to_end(self):
        inp = os.path.join(self.tmp, "in")
        os.makedirs(inp)
        with open(os.path.join(inp, "f.csv"), "w") as fh:
            fh.write("flag\nYes\nno\nTRUE\n")
        rules_path = os.path.join(self.tmp, "rules.toml")
        with open(rules_path, "w") as fh:
            fh.write('[transforms]\nflag = "boolean"\n')
        report = self.run_tool(rules=rules_path, input_dir=inp)
        col = report["files"]["f.csv"]["summary"]["columns"]["flag"]
        self.assertEqual(col["numeric_sum"], 2.0)
        self.assertEqual(col["distinct"], 2)

    def test_numeric_sum_counts_duplicate_cells(self):
        inp = _write_inputs(self.tmp, {"d.csv": "amount\n10.00\n10.00\n5\n"})
        rules_path = _write_rules(self.tmp, '[transforms]\namount = "round2"\n')
        report = self.run_tool(rules=rules_path, input_dir=inp)
        col = report["files"]["d.csv"]["summary"]["columns"]["amount"]
        self.assertEqual(col["numeric_sum"], 25.0)
        self.assertEqual(col["distinct"], 2)


def _write_inputs(root, files):
    inp = os.path.join(root, "in")
    os.makedirs(inp)
    for name, text in files.items():
        with open(os.path.join(inp, name), "w") as fh:
            fh.write(text)
    return inp


def _write_rules(root, body):
    path = os.path.join(root, "rules.toml")
    with open(path, "w") as fh:
        fh.write(body)
    return path


class CacheTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="rg3-cache-")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.out = os.path.join(self.tmp, "out")
        self.cache_path = os.path.join(self.tmp, "cache", "state.json")

    def run_tool(self):
        return reportgen.run(RULES, INPUT_DIR, self.out, self.cache_path)

    def test_first_run_creates_missing_cache_dir(self):
        self.assertFalse(os.path.exists(os.path.dirname(self.cache_path)))
        self.run_tool()
        self.assertTrue(os.path.exists(self.cache_path))

    def test_cache_state_written_on_first_run(self):
        self.run_tool()
        state = cache.load_state(self.cache_path)
        self.assertEqual(set(state), {
            "big_transactions.csv", "small_devices.csv",
            "small_employees.csv", "small_transactions.csv"})
        digest = cache.file_digest(
            os.path.join(INPUT_DIR, "small_transactions.csv"))
        self.assertEqual(state["small_transactions.csv"]["digest"], digest)

    def test_state_file_stable_across_runs(self):
        self.run_tool()
        before = json.load(open(self.cache_path))
        self.run_tool()
        after = json.load(open(self.cache_path))
        self.assertEqual(before, after)

    def test_future_schema_state_is_discarded_and_rewritten(self):
        os.makedirs(os.path.dirname(self.cache_path))
        with open(self.cache_path, "w") as fh:
            json.dump({"small_devices.csv": {
                "digest": "x", "rows": 1, "generated_from": 1, "rules_fp": "y",
                "registry_version": str(int(cache.REGISTRY_VERSION) + 1),
                "summary": {"shape": "future"}}}, fh)
        report = self.run_tool()
        self.assertEqual(report["total_rows"], 12012)
        self.assertEqual(report["files"]["small_devices.csv"]["summary"]["columns"]
                         ["device_id"]["distinct"], 3)
        state = cache.load_state(self.cache_path)
        self.assertEqual(len(state), 4)
        for entry in state.values():
            self.assertEqual(entry["registry_version"], cache.REGISTRY_VERSION)

    def test_entry_with_older_registry_version_is_not_reused(self):
        rules = reportgen.load_rules(RULES)
        os.makedirs(os.path.dirname(self.cache_path))
        digest = cache.file_digest(os.path.join(INPUT_DIR, "small_devices.csv"))
        stale = {"digest": digest, "rows": 3, "generated_from": 1,
                 "rules_fp": cache.rules_fingerprint(rules),
                 "registry_version": str(int(cache.REGISTRY_VERSION) - 1),
                 "summary": {"columns": {"device_id": {
                     "non_empty": 99, "distinct": 99, "sample": ["stale"]}},
                     "skipped_rows": []}}
        with open(self.cache_path, "w") as fh:
            json.dump({"small_devices.csv": stale}, fh)
        report = self.run_tool()
        col = report["files"]["small_devices.csv"]["summary"]["columns"]["device_id"]
        self.assertEqual(col["distinct"], 3)

    def test_failed_cell_run_writes_no_report_and_no_cache(self):
        root = tempfile.mkdtemp(prefix="rg3-fail-")
        self.addCleanup(shutil.rmtree, root, ignore_errors=True)
        inp = _write_inputs(root, {"a.csv": "amount\n$1\n",
                                   "b.csv": "amount\nsee invoice\n"})
        rules_path = _write_rules(root, '[transforms]\namount = "currency_amount"\n')
        out = os.path.join(root, "out")
        cache_path = os.path.join(root, "cache", "state.json")
        with self.assertRaises(reportgen.ValidationError):
            reportgen.run(rules_path, inp, out, cache_path)
        self.assertFalse(os.path.exists(os.path.join(out, "report.html")))
        self.assertFalse(os.path.exists(os.path.join(out, "report.json")))
        self.assertFalse(os.path.exists(cache_path))

    def test_crash_mid_run_writes_no_report_and_no_cache(self):
        root = tempfile.mkdtemp(prefix="rg3-crash-")
        self.addCleanup(shutil.rmtree, root, ignore_errors=True)
        inp = _write_inputs(root, {"a.csv": "item\n1\n", "b.csv": "item\n2\n"})
        rules_path = _write_rules(root, '[transforms]\nitem = "round2"\n')
        out = os.path.join(root, "out")
        cache_path = os.path.join(root, "cache", "state.json")

        def boom(value):
            if value == "2":
                raise RuntimeError("unexpected")
            return float(value)

        with unittest.mock.patch.dict(transforms.REGISTRY, {"round2": boom}):
            with self.assertRaises(RuntimeError):
                reportgen.run(rules_path, inp, out, cache_path)
        self.assertFalse(os.path.exists(cache_path))
        self.assertFalse(os.path.exists(os.path.join(out, "report.html")))


if __name__ == "__main__":
    unittest.main()
