"""Baseline suite for reportgen: transforms, rules loading, end-to-end
report shape, and cache state bookkeeping."""

import json
import os
import shutil
import tempfile
import unittest
from unittest import mock

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


def write_file(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)


class BooleanTransformTests(unittest.TestCase):
    def test_affirmative_and_negative_forms(self):
        for raw in ("yes", "YES", "True", "true"):
            self.assertEqual(transforms.apply("boolean", raw), 1.0)
        for raw in ("no", "No", "FALSE", "false"):
            self.assertEqual(transforms.apply("boolean", raw), 0.0)

    def test_any_other_input_raises(self):
        for raw in ("", "maybe", "1", "0", "y", "n", " yes"):
            with self.assertRaises(transforms.TransformError):
                transforms.apply("boolean", raw)

    def test_boolean_column_summarized_as_numeric(self):
        tmp = tempfile.mkdtemp(prefix="rg3-bool-")
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        write_file(os.path.join(tmp, "in", "f.csv"), "id,flag\n1,yes\n2,No\n3,TRUE\n")
        rules = os.path.join(tmp, "rules.toml")
        write_file(rules, '[transforms]\nflag = "boolean"\n')
        report = reportgen.run(rules, os.path.join(tmp, "in"),
                               os.path.join(tmp, "out"),
                               os.path.join(tmp, "cache", "state.json"))
        flag = report["files"]["f.csv"]["summary"]["columns"]["flag"]
        self.assertEqual(flag["numeric_sum"], 2.0)
        self.assertEqual(flag["distinct"], 2)


class SumRegressionTests(unittest.TestCase):
    # Regression: numeric_sum was taken over the set of distinct values, so
    # repeated amounts (two $40.00 payments) were counted once.
    def test_repeated_values_each_count_toward_sum(self):
        tmp = tempfile.mkdtemp(prefix="rg3-sum-")
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        write_file(os.path.join(tmp, "in", "p.csv"), "id,amount\n1,$40.00\n2,$40.00\n3,$0.50\n")
        rules = os.path.join(tmp, "rules.toml")
        write_file(rules, '[transforms]\namount = "currency_amount"\n')
        report = reportgen.run(rules, os.path.join(tmp, "in"),
                               os.path.join(tmp, "out"),
                               os.path.join(tmp, "cache", "state.json"))
        amount = report["files"]["p.csv"]["summary"]["columns"]["amount"]
        self.assertEqual(amount["numeric_sum"], 80.5)
        self.assertEqual(amount["distinct"], 2)


class DateRegressionTests(unittest.TestCase):
    # Regression: str.isdigit() accepts superscript digits, which int() rejects,
    # so '²/15/2026' used to crash with ValueError instead of TransformError.
    def test_non_ascii_digits_raise_transform_error(self):
        for raw in ("\u00b2/15/2026", "01/\u00b215/2026", "01/15/\u00b2026"):
            with self.assertRaises(transforms.TransformError):
                transforms.apply("date_iso", raw)


class FailedRunTests(unittest.TestCase):
    """A run in which any cell fails its transform emits no report and
    leaves no cache state behind."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="rg3-fail-")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.inp = os.path.join(self.tmp, "in")
        self.out = os.path.join(self.tmp, "out")
        self.cache_path = os.path.join(self.tmp, "cache", "state.json")
        self.rules = os.path.join(self.tmp, "rules.toml")
        write_file(self.rules, '[transforms]\nwhen = "date_iso"\n')
        write_file(os.path.join(self.inp, "a.csv"), "when,label\n01/15/2026,ok\n")
        write_file(os.path.join(self.inp, "b.csv"), "when,label\nnot-a-date,x\n")

    def assert_no_artifacts(self):
        self.assertFalse(os.path.exists(os.path.join(self.out, "report.html")))
        self.assertFalse(os.path.exists(os.path.join(self.out, "report.json")))
        self.assertFalse(os.path.exists(self.cache_path))

    def test_failed_cell_emits_no_report_and_no_cache(self):
        with self.assertRaises(reportgen.ValidationError):
            reportgen.run(self.rules, self.inp, self.out, self.cache_path)
        self.assert_no_artifacts()

    def test_failed_run_leaves_existing_cache_byte_identical(self):
        good = os.path.join(self.tmp, "good")
        write_file(os.path.join(good, "a.csv"), "when,label\n01/15/2026,ok\n")
        reportgen.run(self.rules, good, self.out, self.cache_path)
        with open(self.cache_path, "rb") as fh:
            before = fh.read()
        with self.assertRaises(reportgen.ValidationError):
            reportgen.run(self.rules, self.inp, self.out, self.cache_path)
        with open(self.cache_path, "rb") as fh:
            self.assertEqual(fh.read(), before)

    def test_crashing_transform_ends_like_a_failed_cell(self):
        def boom(value):
            raise RuntimeError("boom")
        write_file(self.rules, '[transforms]\nwhen = "date_iso"\nflag = "boom"\n')
        write_file(os.path.join(self.inp, "a.csv"), "when,label\n01/15/2026,ok\n")
        write_file(os.path.join(self.inp, "b.csv"), "when,flag\n01/15/2026,x\n")
        with mock.patch.dict(transforms.REGISTRY, {"boom": boom}):
            with self.assertRaises(reportgen.ValidationError):
                reportgen.run(self.rules, self.inp, self.out, self.cache_path)
        self.assert_no_artifacts()


class CacheRegressionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="rg3-cache2-")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.inp = os.path.join(self.tmp, "in")
        self.out = os.path.join(self.tmp, "out")
        self.cache_path = os.path.join(self.tmp, "cache", "state.json")
        self.rules = os.path.join(self.tmp, "rules.toml")
        write_file(self.rules, '[transforms]\nitem = "trim"\n')
        write_file(os.path.join(self.inp, "t.csv"), "item,label\n1,alpha\n2,beta\n")

    def run_tool(self):
        return reportgen.run(self.rules, self.inp, self.out, self.cache_path)

    def edit_entry(self, **fields):
        state = cache.load_state(self.cache_path)
        state["t.csv"].update(fields)
        with open(self.cache_path, "w", encoding="utf-8") as fh:
            json.dump(state, fh)

    # Regression: the entry's registry_version was never compared on lookup.
    def test_entry_from_other_registry_is_not_reused(self):
        self.run_tool()
        summary = cache.load_state(self.cache_path)["t.csv"]["summary"]
        summary["columns"]["label"]["distinct"] = 99
        self.edit_entry(summary=summary, registry_version="1")
        report = self.run_tool()
        self.assertEqual(report["files"]["t.csv"]["summary"]["columns"]["label"]["distinct"], 2)
        self.assertEqual(cache.load_state(self.cache_path)["t.csv"]["registry_version"],
                         cache.REGISTRY_VERSION)

    # Regression: an entry holding failed cells was reused, so a run kept
    # failing after the transform was fixed.
    def test_entry_with_skipped_rows_is_not_reused(self):
        self.run_tool()
        summary = cache.load_state(self.cache_path)["t.csv"]["summary"]
        summary["skipped_rows"] = [{"row": 2, "column": "item", "reason": "stale"}]
        self.edit_entry(summary=summary)
        report = self.run_tool()
        self.assertEqual(report["files"]["t.csv"]["summary"]["skipped_rows"], [])
        self.assertEqual(cache.load_state(self.cache_path)["t.csv"]["summary"]["skipped_rows"], [])

    # Regression: generated_from was computed differently on a cache miss
    # (non-empty mapped columns) than on a hit (header columns covered).
    def test_generated_from_matches_cold_and_warm_runs(self):
        write_file(self.rules, '[transforms]\nnote = "trim"\n')
        write_file(os.path.join(self.inp, "t.csv"), "item,note\n1,\n2,\n")
        cold = self.run_tool()["files"]["t.csv"]["generated_from"]
        warm = self.run_tool()["files"]["t.csv"]["generated_from"]
        self.assertEqual(cold, 0)
        self.assertEqual(warm, cold)

    def test_future_schema_entry_treated_as_empty_and_state_rewritten(self):
        # A future entry with a different layout (no "digest" key) crashed the lookup.
        write_file(self.cache_path, json.dumps({"t.csv": {
            "registry_version": "3", "content_sha256": "bogus", "rows": 99}}))
        report = self.run_tool()
        self.assertEqual(report["total_rows"], 2)
        self.assertEqual(report["files"]["t.csv"]["summary"]["columns"]["label"]["distinct"], 2)
        state = cache.load_state(self.cache_path)
        self.assertEqual(state["t.csv"]["registry_version"], cache.REGISTRY_VERSION)
        self.assertEqual(state["t.csv"]["rows"], 2)

    def test_future_schema_top_level_version_treated_as_empty(self):
        write_file(self.cache_path, json.dumps({
            "registry_version": "3",
            "t.csv": {"rows": 99}}))
        report = self.run_tool()
        self.assertEqual(report["total_rows"], 2)
        state = cache.load_state(self.cache_path)
        self.assertEqual(set(state), {"t.csv"})
        self.assertEqual(state["t.csv"]["registry_version"], cache.REGISTRY_VERSION)


class HtmlEscapeRegressionTests(unittest.TestCase):
    # Regression: column names were written into the HTML unescaped.
    def test_column_names_are_escaped(self):
        tmp = tempfile.mkdtemp(prefix="rg3-esc-")
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        write_file(os.path.join(tmp, "in", "h.csv"), "a<i>,label\n1,x\n")
        rules = os.path.join(tmp, "rules.toml")
        write_file(rules, '[transforms]\nlabel = "trim"\n')
        out = os.path.join(tmp, "out")
        reportgen.run(rules, os.path.join(tmp, "in"), out,
                      os.path.join(tmp, "cache", "state.json"))
        with open(os.path.join(out, "report.html"), encoding="utf-8") as fh:
            html = fh.read()
        self.assertNotIn("<i>", html)
        self.assertIn("a&lt;i&gt;", html)


if __name__ == "__main__":
    unittest.main()
