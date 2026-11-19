"""Baseline suite for reportgen: transforms, rules loading, end-to-end
report shape, and cache state bookkeeping."""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

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
    def test_boolean_accepts_affirmative_and_negative_forms(self):
        for text in ("yes", "YES", "Yes", "true", "TRUE", "True"):
            self.assertEqual(transforms.apply("boolean", text), 1.0)
        for text in ("no", "NO", "No", "false", "FALSE", "False"):
            self.assertEqual(transforms.apply("boolean", text), 0.0)

    def test_boolean_rejects_any_other_value(self):
        for text in ("maybe", "", "1", "0", "y", "n", "yesno"):
            with self.assertRaises(transforms.TransformError):
                transforms.apply("boolean", text)

    def test_boolean_column_is_summarized_as_numbers(self):
        tmp = tempfile.mkdtemp(prefix="rg3-bool-")
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        inp = os.path.join(tmp, "in")
        os.makedirs(inp)
        with open(os.path.join(inp, "t.csv"), "w") as fh:
            fh.write("item,flag\n1,yes\n2,no\n3,YES\n")
        rules_path = os.path.join(tmp, "rules.toml")
        with open(rules_path, "w") as fh:
            fh.write('[transforms]\nitem = "round2"\nflag = "boolean"\n')
        out = os.path.join(tmp, "out")
        report = reportgen.run(rules_path, inp, out,
                               os.path.join(tmp, "cache", "state.json"))
        cols = report["files"]["t.csv"]["summary"]["columns"]
        self.assertEqual(cols["flag"]["sample"], [0.0, 1.0])
        self.assertEqual(cols["flag"]["distinct"], 2)
        self.assertEqual(cols["flag"]["non_empty"], 3)
        # numeric_sum sums the distinct transformed values, like every
        # other numeric column of the summary.
        self.assertEqual(cols["flag"]["numeric_sum"], 1.0)


class CacheSchemaTests(unittest.TestCase):
    """The state file is versioned: a state file written by a future
    schema version must not crash the run and must not be reused."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="rg3-schema-")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.out = os.path.join(self.tmp, "out")
        self.cache_path = os.path.join(self.tmp, "cache", "state.json")
        self.rules_fp = cache.rules_fingerprint(reportgen.load_rules(RULES))

    def write_state(self, document):
        os.makedirs(os.path.dirname(self.cache_path), exist_ok=True)
        with open(self.cache_path, "w", encoding="utf-8") as fh:
            json.dump(document, fh, indent=2, sort_keys=True)

    def bogus_entry(self, name):
        path = os.path.join(INPUT_DIR, name)
        return {"digest": cache.file_digest(path), "rows": 1,
                "generated_from": 0, "rules_fp": self.rules_fp,
                "registry_version": cache.REGISTRY_VERSION,
                "summary": {"columns": {
                    "tx_id": {"non_empty": 1, "distinct": 99, "sample": ["bogus"]},
                    "merchant": {"non_empty": 1, "distinct": 99,
                                 "sample": ["bogus"]}},
                    "skipped_rows": []}}

    def test_future_schema_version_cache_does_not_crash_and_is_rewritten(self):
        self.write_state({cache.STATE_VERSION_KEY: cache.REGISTRY_VERSION + 1,
                          cache.STATE_ENTRIES_KEY: {
                              "small_transactions.csv":
                                  self.bogus_entry("small_transactions.csv")}})
        report = reportgen.run(RULES, INPUT_DIR, self.out, self.cache_path)
        tx = report["files"]["small_transactions.csv"]["summary"]["columns"]
        self.assertEqual(tx["merchant"]["distinct"], 3)
        self.assertEqual(tx["amount"]["numeric_sum"], 275.59)
        with open(self.cache_path, encoding="utf-8") as fh:
            state = json.load(fh)
        self.assertEqual(state[cache.STATE_VERSION_KEY], cache.REGISTRY_VERSION)
        self.assertEqual(set(state[cache.STATE_ENTRIES_KEY]), {
            "big_transactions.csv", "small_devices.csv",
            "small_employees.csv", "small_transactions.csv"})
        entry = state[cache.STATE_ENTRIES_KEY]["small_transactions.csv"]
        self.assertEqual(entry["registry_version"], cache.REGISTRY_VERSION)
        self.assertEqual(
            entry["summary"]["columns"]["merchant"]["distinct"], 3)

    def test_unreadable_cache_file_is_treated_as_empty(self):
        os.makedirs(os.path.dirname(self.cache_path), exist_ok=True)
        with open(self.cache_path, "w", encoding="utf-8") as fh:
            fh.write("{not json at all")
        report = reportgen.run(RULES, INPUT_DIR, self.out, self.cache_path)
        self.assertEqual(report["total_rows"], 12012)
        with open(self.cache_path, encoding="utf-8") as fh:
            state = json.load(fh)
        self.assertEqual(state[cache.STATE_VERSION_KEY], cache.REGISTRY_VERSION)

    def test_entry_from_another_registry_version_is_not_reused(self):
        entry = self.bogus_entry("small_transactions.csv")
        entry["registry_version"] = cache.REGISTRY_VERSION - 1
        self.write_state({cache.STATE_VERSION_KEY: cache.REGISTRY_VERSION,
                          cache.STATE_ENTRIES_KEY: {
                              "small_transactions.csv": entry}})
        report = reportgen.run(RULES, INPUT_DIR, self.out, self.cache_path)
        tx = report["files"]["small_transactions.csv"]["summary"]["columns"]
        self.assertEqual(tx["merchant"]["distinct"], 3)

    def test_cached_entry_with_failed_transforms_is_not_reused(self):
        entry = self.bogus_entry("small_transactions.csv")
        entry["summary"]["skipped_rows"] = [{"row": 2, "column": "amount",
                                             "reason": "not a number"}]
        self.write_state({cache.STATE_VERSION_KEY: cache.REGISTRY_VERSION,
                          cache.STATE_ENTRIES_KEY: {
                              "small_transactions.csv": entry}})
        report = reportgen.run(RULES, INPUT_DIR, self.out, self.cache_path)
        tx = report["files"]["small_transactions.csv"]["summary"]["columns"]
        self.assertEqual(tx["merchant"]["distinct"], 3)


class FailurePolicyTests(unittest.TestCase):
    """A failed transform must fail the run without touching the
    previously written report or the cache."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="rg3-fail-")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.out = os.path.join(self.tmp, "out")
        self.cache_path = os.path.join(self.tmp, "cache", "state.json")
        self.rules = os.path.join(self.tmp, "rules.toml")
        with open(self.rules, "w") as fh:
            fh.write('[transforms]\nflag = "boolean"\n')
        self.good_in = os.path.join(self.tmp, "good")
        os.makedirs(self.good_in)
        with open(os.path.join(self.good_in, "t.csv"), "w") as fh:
            fh.write("flag\nyes\nno\n")
        self.bad_in = os.path.join(self.tmp, "bad")
        os.makedirs(self.bad_in)
        with open(os.path.join(self.bad_in, "t.csv"), "w") as fh:
            fh.write("flag\nyes\nmaybe\n")

    def artifacts(self):
        paths = [os.path.join(self.out, "report.json"),
                 os.path.join(self.out, "report.html"), self.cache_path]
        out = {}
        for path in paths:
            with open(path, "rb") as fh:
                out[path] = fh.read()
        return out

    def test_failed_transform_leaves_previous_artifacts_intact(self):
        reportgen.run(self.rules, self.good_in, self.out, self.cache_path)
        before = self.artifacts()
        with self.assertRaises(reportgen.ValidationError):
            reportgen.run(self.rules, self.bad_in, self.out, self.cache_path)
        self.assertEqual(self.artifacts(), before)

    def test_failed_transform_writes_no_new_artifacts(self):
        with self.assertRaises(reportgen.ValidationError):
            reportgen.run(self.rules, self.bad_in, self.out, self.cache_path)
        self.assertFalse(os.path.exists(os.path.join(self.out, "report.json")))
        self.assertFalse(os.path.exists(os.path.join(self.out, "report.html")))
        self.assertFalse(os.path.exists(self.cache_path))

    def test_cli_exits_1_on_failed_transform(self):
        reportgen.run(self.rules, self.good_in, self.out, self.cache_path)
        before = self.artifacts()
        code = reportgen.main(["--rules", self.rules, "--input", self.bad_in,
                               "--output", self.out, "--cache", self.cache_path])
        self.assertEqual(code, 1)
        self.assertEqual(self.artifacts(), before)
        proc = subprocess.run(
            [sys.executable, os.path.join(BASE, "reportgen.py"),
             "--rules", self.rules, "--input", self.bad_in,
             "--output", self.out, "--cache", self.cache_path],
            cwd=BASE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        self.assertEqual(proc.returncode, 1)
        self.assertEqual(self.artifacts(), before)


class RunBehaviourTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="rg3-run-")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.out = os.path.join(self.tmp, "out")
        self.cache_path = os.path.join(self.tmp, "cache", "state.json")

    def test_rules_file_is_read_once_per_run(self):
        calls = []
        real = reportgen.load_rules

        def counting(path):
            calls.append(path)
            return real(path)

        reportgen.load_rules = counting
        self.addCleanup(setattr, reportgen, "load_rules", real)
        reportgen.run(RULES, INPUT_DIR, self.out, self.cache_path)
        self.assertEqual(len(calls), 1)

    def test_report_does_not_depend_on_cache_warmth(self):
        reportgen.run(RULES, INPUT_DIR, self.out, self.cache_path)
        with open(os.path.join(self.out, "report.json"), "rb") as fh:
            cold = fh.read()
        reportgen.run(RULES, INPUT_DIR, self.out, self.cache_path)
        with open(os.path.join(self.out, "report.json"), "rb") as fh:
            warm = fh.read()
        self.assertEqual(cold, warm)

    def test_html_escapes_file_names_columns_and_values(self):
        inp = os.path.join(self.tmp, "in")
        os.makedirs(inp)
        with open(os.path.join(inp, "a<b>&c.csv"), "w") as fh:
            fh.write("col<1>,label\nv,red <b> & bold\n")
        reportgen.run(RULES, inp, self.out, self.cache_path)
        with open(os.path.join(self.out, "report.html")) as fh:
            html = fh.read()
        self.assertNotIn("<b>", html)
        self.assertNotIn("col<1>", html)
        self.assertIn("col&lt;1&gt;", html)
        self.assertIn("a&lt;b&gt;&amp;c.csv", html)
        self.assertIn("red &lt;b&gt; &amp; bold", html)


if __name__ == "__main__":
    unittest.main()
