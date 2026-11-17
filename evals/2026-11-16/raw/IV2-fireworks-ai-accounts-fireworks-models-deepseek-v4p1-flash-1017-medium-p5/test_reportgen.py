"""Baseline suite for reportgen: transforms, rules loading, end-to-end
report shape, and cache state bookkeeping."""

import json
import os
import shutil
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
        for raw in ("yes", "YES", "Yes", "true", "TRUE", "True"):
            self.assertEqual(transforms.apply("boolean", raw), 1.0)
        for raw in ("no", "NO", "No", "false", "FALSE", "False"):
            self.assertEqual(transforms.apply("boolean", raw), 0.0)

    def test_boolean_rejects_other_input(self):
        for raw in ("", "1", "0", "y", "n", "maybe", "truthy", " "):
            with self.assertRaises(transforms.TransformError):
                transforms.apply("boolean", raw)


class CacheSchemaVersionTests(unittest.TestCase):
    """A state file from a future schema must be ignored, not crash."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="rg3-future-")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.out = os.path.join(self.tmp, "out")
        self.cache_path = os.path.join(self.tmp, "cache", "state.json")

    def _write_state(self, entry):
        os.makedirs(os.path.dirname(self.cache_path))
        with open(self.cache_path, "w", encoding="utf-8") as fh:
            json.dump({"big_transactions.csv": entry}, fh)

    def _matching_entry(self, version, summary):
        rules = reportgen.load_rules(RULES)
        return {
            "digest": cache.file_digest(
                os.path.join(INPUT_DIR, "big_transactions.csv")),
            "rows": 1, "generated_from": 0,
            "rules_fp": cache.rules_fingerprint(rules),
            "registry_version": version,
            "summary": summary,
        }

    def test_future_version_cache_is_treated_as_empty_and_rewritten(self):
        self._write_state(self._matching_entry("999", "future schema"))
        report = reportgen.run(RULES, INPUT_DIR, self.out, self.cache_path)
        self.assertEqual(report["total_rows"], 12012)
        state = cache.load_state(self.cache_path)
        self.assertEqual(set(state), {
            "big_transactions.csv", "small_devices.csv",
            "small_employees.csv", "small_transactions.csv"})
        for entry in state.values():
            self.assertEqual(entry["registry_version"], cache.REGISTRY_VERSION)

    def test_older_version_entry_is_not_reused(self):
        self._write_state(self._matching_entry("1", "stale schema"))
        report = reportgen.run(RULES, INPUT_DIR, self.out, self.cache_path)
        self.assertEqual(report["total_rows"], 12012)
        self.assertEqual(
            cache.load_state(self.cache_path)["big_transactions.csv"]
            ["registry_version"], cache.REGISTRY_VERSION)


class TransformFailureInvariantTests(unittest.TestCase):
    """Any failed transform cell means no report and no cache state."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="rg3-fail-")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.inp = os.path.join(self.tmp, "in")
        os.makedirs(self.inp)
        self.out = os.path.join(self.tmp, "out")
        self.cache_path = os.path.join(self.tmp, "cache", "state.json")
        self.rules_path = os.path.join(self.tmp, "rules.toml")

    def assert_nothing_written(self):
        self.assertFalse(
            os.path.exists(os.path.join(self.out, "report.html")))
        self.assertFalse(
            os.path.exists(os.path.join(self.out, "report.json")))
        self.assertFalse(os.path.exists(self.cache_path))

    def test_caught_transform_error_leaves_no_output(self):
        with open(os.path.join(self.inp, "a.csv"), "w") as fh:
            fh.write("item,label\n1,alpha\n2,nope\n")
        with open(self.rules_path, "w") as fh:
            fh.write('[transforms]\nlabel = "round2"\n')
        with self.assertRaises(reportgen.ValidationError):
            reportgen.run(self.rules_path, self.inp, self.out, self.cache_path)
        self.assert_nothing_written()

    def test_unhandled_transform_crash_leaves_no_output(self):
        def boom(value):
            if value == "boom":
                raise RuntimeError("boom")
            return value

        transforms.REGISTRY["_boom_test"] = boom
        self.addCleanup(transforms.REGISTRY.pop, "_boom_test", None)
        with open(os.path.join(self.inp, "a.csv"), "w") as fh:
            fh.write("item,label\n1,fine\n")
        with open(os.path.join(self.inp, "b.csv"), "w") as fh:
            fh.write("item,label\n2,boom\n")
        with open(self.rules_path, "w") as fh:
            fh.write('[transforms]\nlabel = "_boom_test"\n')
        with self.assertRaises(RuntimeError):
            reportgen.run(self.rules_path, self.inp, self.out, self.cache_path)
        self.assert_nothing_written()


class CacheReuseFidelityTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="rg3-reuse-")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.out = os.path.join(self.tmp, "out")
        self.cache_path = os.path.join(self.tmp, "cache", "state.json")

    def run_tool(self):
        return reportgen.run(RULES, INPUT_DIR, self.out, self.cache_path)

    def test_generated_from_matches_between_fresh_and_cached_runs(self):
        fresh = self.run_tool()
        cached = self.run_tool()
        self.assertEqual(
            {k: v["generated_from"] for k, v in fresh["files"].items()},
            {k: v["generated_from"] for k, v in cached["files"].items()})
        self.assertEqual(
            fresh["files"]["small_devices.csv"]["generated_from"], 1)
        self.assertEqual(
            cache.load_state(self.cache_path)["small_devices.csv"]
            ["generated_from"], 1)


class HtmlEscapeRegressionTests(unittest.TestCase):
    def test_report_escapes_sample_markup(self):
        tmp = tempfile.mkdtemp(prefix="rg3-escape-")
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        inp = os.path.join(tmp, "in")
        os.makedirs(inp)
        with open(os.path.join(inp, "labels.csv"), "w") as fh:
            fh.write("label\nred <b> & bold\n")
        out = os.path.join(tmp, "out")
        reportgen.run(RULES, inp, out, os.path.join(tmp, "cache", "state.json"))
        with open(os.path.join(out, "report.html")) as fh:
            html = fh.read()
        self.assertNotIn("<b>", html)
        self.assertIn("red &lt;b&gt; &amp; bold", html)


if __name__ == "__main__":
    unittest.main()
