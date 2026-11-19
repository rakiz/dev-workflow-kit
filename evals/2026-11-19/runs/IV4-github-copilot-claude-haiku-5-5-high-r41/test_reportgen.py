"""Baseline suite for reportgen: transforms, rules loading, end-to-end
report shape, and cache state bookkeeping."""

import contextlib
import io
import json
import os
import shutil
import subprocess
import sys
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


# ---------------------------------------------------------------------------
# Regression tests added with the boolean transform and the defect fixes.
# ---------------------------------------------------------------------------

def make_tmp(test, prefix):
    tmp = tempfile.mkdtemp(prefix=prefix)
    test.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
    return tmp


def write_text(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)


def read_bytes(path):
    with open(path, "rb") as fh:
        return fh.read()


def quiet_main(argv):
    """Run the CLI entry point with its stdout/stderr captured."""
    with contextlib.redirect_stdout(io.StringIO()), \
            contextlib.redirect_stderr(io.StringIO()):
        return reportgen.main(argv)


class BooleanTransformTests(unittest.TestCase):
    def test_affirmative_and_negative_forms_case_insensitive(self):
        for raw in ("yes", "YES", "True", "true"):
            self.assertEqual(transforms.apply("boolean", raw), 1.0)
        for raw in ("no", "NO", "False", "false"):
            self.assertEqual(transforms.apply("boolean", raw), 0.0)

    def test_any_other_input_raises(self):
        for raw in ("maybe", "", " yes", "1", "0", "y", "n"):
            with self.subTest(raw=raw):
                with self.assertRaises(transforms.TransformError):
                    transforms.apply("boolean", raw)

    def test_boolean_column_is_numeric_in_summary(self):
        summary = reportgen.summarize_file(
            ["flag"], [["yes"], ["no"], ["True"]], {"flag": "boolean"})
        self.assertEqual(summary["columns"]["flag"]["numeric_sum"], 2.0)
        self.assertEqual(summary["skipped_rows"], [])


class DateIsoRegressionTests(unittest.TestCase):
    def test_superscript_digit_is_transform_error_not_crash(self):
        # Defect: isdigit() accepted '²' and int() then raised ValueError,
        # an exception escaping the transform instead of TransformError.
        with self.assertRaises(transforms.TransformError):
            transforms.apply("date_iso", "\u00b2/15/2026")

    def test_other_unicode_decimal_digits_still_accepted(self):
        self.assertEqual(transforms.apply("date_iso", "\u0661/15/2026"),
                         "2026-01-15")


class HtmlEscapeTests(unittest.TestCase):
    def test_file_and_column_names_are_escaped(self):
        tmp = make_tmp(self, "rg3-esc-")
        inp = os.path.join(tmp, "in")
        write_text(os.path.join(inp, "f<1>.csv"), "<col>\nx\n")
        rules = os.path.join(tmp, "rules.toml")
        write_text(rules, "[transforms]\n")
        reportgen.run(rules, inp, os.path.join(tmp, "out"),
                      os.path.join(tmp, "cache", "state.json"))
        with open(os.path.join(tmp, "out", "report.html"), encoding="utf-8") as fh:
            page = fh.read()
        self.assertIn("<h1>f&lt;1&gt;.csv</h1>", page)
        self.assertIn("<td>&lt;col&gt;</td>", page)
        self.assertNotIn("<col>", page)


class FailurePolicyTests(unittest.TestCase):
    """Any transform failure: exit 1, nothing new emitted, previous report
    and cache untouched."""

    def setUp(self):
        self.tmp = make_tmp(self, "rg3-policy-")
        self.inp = os.path.join(self.tmp, "in")
        self.out = os.path.join(self.tmp, "out")
        self.cache_path = os.path.join(self.tmp, "cache", "state.json")
        self.rules = os.path.join(self.tmp, "rules.toml")
        write_text(self.rules, '[transforms]\nwhen = "date_iso"\nitem = "trim"\n')
        write_text(os.path.join(self.inp, "a.csv"), "item,when\n1,01/15/2026\n")

    def argv(self):
        return ["--rules", self.rules, "--input", self.inp,
                "--output", self.out, "--cache", self.cache_path]

    def outputs(self):
        return [os.path.join(self.out, "report.json"),
                os.path.join(self.out, "report.html"), self.cache_path]

    def test_failed_transform_keeps_previous_outputs_byte_for_byte(self):
        self.assertEqual(quiet_main(self.argv()), 0)
        before = {p: read_bytes(p) for p in self.outputs()}
        write_text(os.path.join(self.inp, "b.csv"), "item,when\n2,not-a-date\n")
        self.assertEqual(quiet_main(self.argv()), 1)
        self.assertEqual({p: read_bytes(p) for p in self.outputs()}, before)

    def test_failed_transform_on_cold_start_emits_nothing(self):
        write_text(os.path.join(self.inp, "b.csv"), "item,when\n2,not-a-date\n")
        self.assertEqual(quiet_main(self.argv()), 1)
        self.assertFalse(os.path.exists(self.out))
        self.assertFalse(os.path.exists(self.cache_path))

    def test_unhandled_crash_keeps_previous_outputs_byte_for_byte(self):
        self.assertEqual(quiet_main(self.argv()), 0)
        before = {p: read_bytes(p) for p in self.outputs()}
        write_text(os.path.join(self.inp, "a.csv"), "item,when\n1,01/16/2026\n")

        def boom(value):
            raise RuntimeError("boom")

        with mock.patch.dict(transforms.REGISTRY, {"trim": boom}):
            with self.assertRaises(RuntimeError):
                reportgen.run(self.rules, self.inp, self.out, self.cache_path)
        self.assertEqual({p: read_bytes(p) for p in self.outputs()}, before)

    def test_cli_exit_status(self):
        script = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                              "reportgen.py")
        ok = subprocess.run([sys.executable, script] + self.argv(),
                            capture_output=True, text=True)
        self.assertEqual(ok.returncode, 0, ok.stderr)
        write_text(os.path.join(self.inp, "b.csv"), "item,when\n2,not-a-date\n")
        bad = subprocess.run([sys.executable, script] + self.argv(),
                             capture_output=True, text=True)
        self.assertEqual(bad.returncode, 1)
        self.assertIn("failed their transform", bad.stderr)


class CacheRegistryVersionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = make_tmp(self, "rg3-regv-")
        self.inp = os.path.join(self.tmp, "in")
        write_text(os.path.join(self.inp, "a.csv"), "item\n1\n2\n")
        self.rules = os.path.join(self.tmp, "rules.toml")
        write_text(self.rules, '[transforms]\nitem = "round2"\n')
        self.out = os.path.join(self.tmp, "out")
        self.cache_path = os.path.join(self.tmp, "cache", "state.json")

    def run_tool(self):
        return reportgen.run(self.rules, self.inp, self.out, self.cache_path)

    def test_entry_from_other_registry_version_is_not_reused(self):
        self.run_tool()
        state = cache.load_state(self.cache_path)
        state["a.csv"]["registry_version"] = "2"
        state["a.csv"]["summary"]["columns"]["item"]["distinct"] = 999
        write_text(self.cache_path, json.dumps(state))
        report = self.run_tool()
        self.assertEqual(report["files"]["a.csv"]["summary"]["columns"]["item"]["distinct"], 2)
        self.assertEqual(cache.load_state(self.cache_path)["a.csv"]["registry_version"],
                         cache.REGISTRY_VERSION)


class FutureSchemaCacheTests(unittest.TestCase):
    def setUp(self):
        self.tmp = make_tmp(self, "rg3-future-")
        self.inp = os.path.join(self.tmp, "in")
        write_text(os.path.join(self.inp, "a.csv"), "item\n1\n2\n")
        self.rules = os.path.join(self.tmp, "rules.toml")
        write_text(self.rules, '[transforms]\nitem = "round2"\n')
        self.out = os.path.join(self.tmp, "out")
        self.cache_path = os.path.join(self.tmp, "cache", "state.json")

    def test_future_schema_state_is_treated_as_empty_and_rewritten(self):
        # Matching digest and rules fingerprint, so a naive lookup would
        # reuse this entry; its shape is not one this code can read.
        digest = cache.file_digest(os.path.join(self.inp, "a.csv"))
        rules_fp = cache.rules_fingerprint(reportgen.load_rules(self.rules))
        write_text(self.cache_path, json.dumps({"a.csv": {
            "digest": digest, "rules_fp": rules_fp, "registry_version": "99",
            "rows": 0, "summary": {"future": True}}}))
        report = reportgen.run(self.rules, self.inp, self.out, self.cache_path)
        self.assertEqual(report["files"]["a.csv"]["summary"]["columns"]["item"]["distinct"], 2)
        with open(self.cache_path, encoding="utf-8") as fh:
            rewritten = json.load(fh)
        self.assertEqual(rewritten["a.csv"]["registry_version"], cache.REGISTRY_VERSION)
        self.assertNotIn("future", rewritten["a.csv"]["summary"])

    def test_load_state_treats_future_version_as_empty(self):
        write_text(self.cache_path, json.dumps({"a.csv": {
            "registry_version": str(int(cache.REGISTRY_VERSION) + 1)}}))
        self.assertEqual(cache.load_state(self.cache_path), {})


class RulesReadOnceTests(unittest.TestCase):
    def test_rules_file_read_once_per_run(self):
        tmp = make_tmp(self, "rg3-reads-")
        inp = os.path.join(tmp, "in")
        for name in ("a.csv", "b.csv", "c.csv"):
            write_text(os.path.join(inp, name), "item\n1\n")
        with mock.patch.object(reportgen, "load_rules",
                               wraps=reportgen.load_rules) as spy:
            reportgen.run(RULES, inp, os.path.join(tmp, "out"),
                          os.path.join(tmp, "cache", "state.json"))
        self.assertEqual(spy.call_count, 1)


class GeneratedFromConsistencyTests(unittest.TestCase):
    def test_cold_and_warm_runs_report_same_generated_from(self):
        tmp = make_tmp(self, "rg3-genfrom-")
        inp = os.path.join(tmp, "in")
        # 'item' is mapped but has no non-empty cell in this file.
        write_text(os.path.join(inp, "e.csv"), "item,label\n,alpha\n")
        rules = os.path.join(tmp, "rules.toml")
        write_text(rules, '[transforms]\nitem = "trim"\n')
        args = (rules, inp, os.path.join(tmp, "out"),
                os.path.join(tmp, "cache", "state.json"))
        cold = reportgen.run(*args)["files"]["e.csv"]["generated_from"]
        warm = reportgen.run(*args)["files"]["e.csv"]["generated_from"]
        self.assertEqual(cold, 0)
        self.assertEqual(warm, cold)


class HeaderOnlyFileTests(unittest.TestCase):
    def test_header_only_file_keeps_its_columns(self):
        summary = reportgen.summarize_file(["a", "b"], [], {"a": "trim"})
        self.assertEqual(sorted(summary["columns"]), ["a", "b"])
        self.assertEqual(summary["columns"]["b"]["non_empty"], 0)


class NumericSumTests(unittest.TestCase):
    def test_numeric_sum_counts_repeated_values_once_per_cell(self):
        # Defect: the sum ran over the set of distinct values, so two
        # cells of 40.00 summed to 40.00 instead of 80.00.
        summary = reportgen.summarize_file(
            ["amount"], [["$40.00"], ["$40.00"], ["$0.50"]],
            {"amount": "currency_amount"})
        self.assertEqual(summary["columns"]["amount"]["numeric_sum"], 80.5)
        self.assertEqual(summary["columns"]["amount"]["distinct"], 2)


if __name__ == "__main__":
    unittest.main()
