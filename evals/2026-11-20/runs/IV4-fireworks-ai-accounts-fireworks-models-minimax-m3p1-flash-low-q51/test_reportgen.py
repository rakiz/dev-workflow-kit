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


class BooleanTransformTests(unittest.TestCase):
    def test_affirmative_and_negative_forms(self):
        for token in ("yes", "YES", "Yes", "true", "TRUE", "True"):
            self.assertEqual(transforms.apply("boolean", token), 1.0)
        for token in ("no", "NO", "No", "false", "FALSE", "False"):
            self.assertEqual(transforms.apply("boolean", token), 0.0)

    def test_other_values_raise(self):
        for token in ("maybe", "", "1", "0", "y"):
            with self.assertRaises(transforms.TransformError):
                transforms.apply("boolean", token)


class RulesReadOnceTests(unittest.TestCase):
    """The rules file must be read at most once per run."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="rg3-read-")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.out = os.path.join(self.tmp, "out")
        self.cache_path = os.path.join(self.tmp, "cache", "state.json")

    def test_rules_file_is_read_once_per_run(self):
        real_open = open
        reads = []

        def counting_open(file, *args, **kwargs):
            try:
                same = os.path.abspath(file) == os.path.abspath(RULES)
            except TypeError:
                same = False
            if same:
                reads.append(file)
            return real_open(file, *args, **kwargs)

        with unittest.mock.patch("builtins.open", counting_open):
            reportgen.run(RULES, INPUT_DIR, self.out, self.cache_path)
        self.assertEqual(len(reads), 1)


class FailurePolicyTests(unittest.TestCase):
    """A transform failure must abort the run: exit 1, no new report, and
    the previous report and cache left byte-for-byte intact."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="rg3-fail-")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.inp = os.path.join(self.tmp, "in")
        self.out = os.path.join(self.tmp, "out")
        os.makedirs(self.inp)
        self.cache_path = os.path.join(self.tmp, "cache", "state.json")
        self.rules_path = os.path.join(self.tmp, "rules.toml")
        with open(self.rules_path, "w") as fh:
            fh.write('[transforms]\namount = "round2"\n')
        self.csv = os.path.join(self.inp, "t.csv")

    def write_csv(self, body):
        with open(self.csv, "w") as fh:
            fh.write(body)

    def run_cli(self):
        return reportgen.main(["--rules", self.rules_path,
                               "--input", self.inp,
                               "--output", self.out,
                               "--cache", self.cache_path])

    def read_bytes(self, path):
        with open(path, "rb") as fh:
            return fh.read()

    def test_failure_exits_1_and_leaves_artifacts_untouched(self):
        self.write_csv("amount\n1.0\n")
        self.assertEqual(self.run_cli(), 0)
        report_json = os.path.join(self.out, "report.json")
        report_html = os.path.join(self.out, "report.html")
        before = (self.read_bytes(report_json), self.read_bytes(report_html),
                  self.read_bytes(self.cache_path))

        self.write_csv("amount\n1.0\nn/a\n")
        self.assertEqual(self.run_cli(), 1)
        after = (self.read_bytes(report_json), self.read_bytes(report_html),
                 self.read_bytes(self.cache_path))
        self.assertEqual(before, after)

    def test_failed_run_emits_no_new_report(self):
        self.write_csv("amount\nn/a\n")
        self.assertEqual(self.run_cli(), 1)
        self.assertFalse(os.path.exists(os.path.join(self.out, "report.json")))
        self.assertFalse(os.path.exists(os.path.join(self.out, "report.html")))
        self.assertFalse(os.path.exists(self.cache_path))


class CacheHygieneTests(unittest.TestCase):
    """A cache/state.json written by a future schema version must not
    crash the run: the cache is treated as empty, the run is redone in
    full and a valid state file is written back."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="rg3-hyg-")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.out = os.path.join(self.tmp, "out")
        self.cache_path = os.path.join(self.tmp, "cache", "state.json")
        os.makedirs(os.path.dirname(self.cache_path))

    def write_state(self, payload):
        with open(self.cache_path, "w") as fh:
            json.dump(payload, fh, indent=2, sort_keys=True)

    def test_future_top_level_version_is_ignored(self):
        self.write_state({"version": "999",
                          "entries": {"small_transactions.csv": {"digest": "x"}}})
        report = reportgen.run(RULES, INPUT_DIR, self.out, self.cache_path)
        self.assertEqual(report["total_rows"], 12012)
        state = cache.load_state(self.cache_path)
        self.assertIn("small_transactions.csv", state)
        self.assertEqual(
            state["small_transactions.csv"]["registry_version"],
            cache.REGISTRY_VERSION)

    def test_future_entry_registry_version_is_ignored(self):
        entry = {"digest": "x", "rows": 0, "generated_from": 0,
                 "rules_fp": "y", "registry_version": "999",
                 "summary": {"columns": {}, "skipped_rows": []}}
        self.write_state({"small_transactions.csv": entry})
        report = reportgen.run(RULES, INPUT_DIR, self.out, self.cache_path)
        self.assertEqual(report["total_rows"], 12012)
        state = cache.load_state(self.cache_path)
        self.assertEqual(
            state["small_transactions.csv"]["registry_version"],
            cache.REGISTRY_VERSION)
        self.assertNotEqual(
            state["small_transactions.csv"]["summary"], entry["summary"])

    def test_stale_entry_registry_version_is_not_reused(self):
        entry = {"digest": "x", "rows": 999, "generated_from": 0,
                 "rules_fp": "y", "registry_version": "0",
                 "summary": {"columns": {}, "skipped_rows": []}}
        self.write_state({"small_transactions.csv": entry})
        report = reportgen.run(RULES, INPUT_DIR, self.out, self.cache_path)
        self.assertEqual(report["total_rows"], 12012)
        self.assertEqual(report["files"]["small_transactions.csv"]["rows"], 4)


class HtmlEscapingTests(unittest.TestCase):
    def test_sample_values_are_escaped(self):
        tmp = tempfile.mkdtemp(prefix="rg3-esc-")
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        inp = os.path.join(tmp, "in")
        os.makedirs(inp)
        with open(os.path.join(inp, "labels.csv"), "w") as fh:
            fh.write("item,label\ni1,red <b> & bold\n")
        rules_path = os.path.join(tmp, "rules.toml")
        with open(rules_path, "w") as fh:
            fh.write('[transforms]\nitem = "trim"\n')
        out = os.path.join(tmp, "out")
        reportgen.run(rules_path, inp, out, os.path.join(tmp, "cache", "state.json"))
        with open(os.path.join(out, "report.html")) as fh:
            html_text = fh.read()
        self.assertNotIn("<b>", html_text)
        self.assertIn("red &lt;b&gt; &amp; bold", html_text)


if __name__ == "__main__":
    unittest.main()
