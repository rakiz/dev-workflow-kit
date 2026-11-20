"""Baseline suite for reportgen: transforms, rules loading, end-to-end
report shape, and cache state bookkeeping."""

import builtins
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


class BooleanTransformTests(unittest.TestCase):
    """Feature: the `boolean` transform maps yes/true -> 1.0 and
    no/false -> 0.0, case-insensitively; anything else fails."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="rg3-bool-")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.out = os.path.join(self.tmp, "out")
        self.cache_path = os.path.join(self.tmp, "cache", "state.json")

    def test_affirmative_forms_report_one(self):
        for raw in ("yes", "Yes", "YES", "true", "True", "TRUE"):
            self.assertEqual(transforms.apply("boolean", raw), 1.0)

    def test_negative_forms_report_zero(self):
        for raw in ("no", "No", "NO", "false", "False", "FALSE"):
            self.assertEqual(transforms.apply("boolean", raw), 0.0)

    def test_surrounding_whitespace_is_trimmed(self):
        self.assertEqual(transforms.apply("boolean", "  yes "), 1.0)
        self.assertEqual(transforms.apply("boolean", "\tfalse\n"), 0.0)

    def test_any_other_input_raises(self):
        for raw in ("maybe", "y", "n", "1", "0", "", "yesno"):
            with self.assertRaises(transforms.TransformError):
                transforms.apply("boolean", raw)

    def test_boolean_column_end_to_end(self):
        inp = os.path.join(self.tmp, "in")
        os.makedirs(inp)
        with open(os.path.join(inp, "flags.csv"), "w") as fh:
            fh.write("id,flag\n1,yes\n2,NO\n3, true \n")
        rules_path = os.path.join(self.tmp, "rules.toml")
        with open(rules_path, "w") as fh:
            fh.write('[transforms]\nflag = "boolean"\n')
        report = reportgen.run(rules_path, inp, self.out, self.cache_path)
        cols = report["files"]["flags.csv"]["summary"]["columns"]
        self.assertEqual(cols["flag"]["distinct"], 2)
        # numeric_sum is over the distinct value set: 0.0 + 1.0
        self.assertEqual(cols["flag"]["numeric_sum"], 1.0)
        self.assertEqual(cols["flag"]["sample"], [0.0, 1.0])


class HtmlEscapingTests(unittest.TestCase):
    """Regression: file names, column names and sample values used to be
    interpolated into report.html unescaped (markup in data leaked into
    the page)."""

    def test_names_columns_and_samples_are_escaped(self):
        tmp = tempfile.mkdtemp(prefix="rg3-esc-")
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        inp = os.path.join(tmp, "in")
        os.makedirs(inp)
        with open(os.path.join(inp, "x<b>.csv"), "w") as fh:
            fh.write("c&1,label\nv,<i>hi</i>\n")
        rules_path = os.path.join(tmp, "rules.toml")
        with open(rules_path, "w") as fh:
            fh.write("# no transforms\n")
        out = os.path.join(tmp, "out")
        reportgen.run(rules_path, inp, out, os.path.join(tmp, "cache", "state.json"))
        with open(os.path.join(out, "report.html")) as fh:
            page = fh.read()
        self.assertIn("x&lt;b&gt;.csv", page)
        self.assertIn("c&amp;1", page)
        self.assertIn("&lt;i&gt;hi&lt;/i&gt;", page)
        self.assertNotIn("<b>", page)
        self.assertNotIn("<i>", page)


class FailurePolicyTests(unittest.TestCase):
    """Regression for the failure policy: when any transform fails the run
    must exit 1, emit nothing new, and leave the previously good
    report.json, report.html and cache byte-for-byte intact. The old code
    saved cache entries inside the file loop and wrote report.html BEFORE
    validating, then swallowed the ValidationError as a warning with
    exit code 0."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="rg3-policy-")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.out = os.path.join(self.tmp, "out")
        self.cache_path = os.path.join(self.tmp, "cache", "state.json")
        self.rules_path = os.path.join(self.tmp, "rules.toml")
        with open(self.rules_path, "w") as fh:
            fh.write('[transforms]\namount = "currency_amount"\n')
        self.good_inp = os.path.join(self.tmp, "good_in")
        os.makedirs(self.good_inp)
        with open(os.path.join(self.good_inp, "good.csv"), "w") as fh:
            fh.write("amount\n$1.00\n$2.00\n")
        self.bad_inp = os.path.join(self.tmp, "bad_in")
        os.makedirs(self.bad_inp)
        with open(os.path.join(self.bad_inp, "bad.csv"), "w") as fh:
            fh.write("amount\nsee invoice\n")
        self.mixed_inp = os.path.join(self.tmp, "mixed_in")
        os.makedirs(self.mixed_inp)
        shutil.copy(os.path.join(self.good_inp, "good.csv"), self.mixed_inp)
        shutil.copy(os.path.join(self.bad_inp, "bad.csv"), self.mixed_inp)

    def _snapshot(self):
        snap = {}
        for p in (os.path.join(self.out, "report.json"),
                  os.path.join(self.out, "report.html"),
                  self.cache_path):
            if os.path.exists(p):
                with open(p, "rb") as fh:
                    snap[p] = fh.read()
            else:
                snap[p] = None
        return snap

    def test_failed_run_leaves_previous_report_and_cache_byte_identical(self):
        reportgen.run(self.rules_path, self.good_inp, self.out, self.cache_path)
        before = self._snapshot()
        with self.assertRaises(reportgen.ValidationError):
            reportgen.run(self.rules_path, self.mixed_inp, self.out, self.cache_path)
        self.assertEqual(self._snapshot(), before)

    def test_failed_first_run_emits_nothing(self):
        with self.assertRaises(reportgen.ValidationError):
            reportgen.run(self.rules_path, self.bad_inp, self.out, self.cache_path)
        self.assertEqual(self._snapshot(),
                         {os.path.join(self.out, "report.json"): None,
                          os.path.join(self.out, "report.html"): None,
                          self.cache_path: None})

    def test_main_exits_1_on_transform_failure(self):
        with self.assertRaises(SystemExit) as cm:
            reportgen.main(["--rules", self.rules_path,
                            "--input", self.bad_inp,
                            "--output", self.out,
                            "--cache", self.cache_path])
        self.assertEqual(cm.exception.code, 1)
        self.assertFalse(os.path.exists(os.path.join(self.out, "report.json")))
        self.assertFalse(os.path.exists(os.path.join(self.out, "report.html")))
        self.assertFalse(os.path.exists(self.cache_path))


class TransformCrashFunnelTests(unittest.TestCase):
    """Regression: a transform crashing with an unexpected exception is a
    transform failure under the same policy. date_iso has such a crash:
    superscript digits pass .isdigit() but int() raises ValueError on them
    (e.g. month '\u00b2'), which used to escape summarize_file as a raw
    ValueError."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="rg3-crash-")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.out = os.path.join(self.tmp, "out")
        self.cache_path = os.path.join(self.tmp, "cache", "state.json")
        self.inp = os.path.join(self.tmp, "in")
        os.makedirs(self.inp)
        with open(os.path.join(self.inp, "d.csv"), "w") as fh:
            fh.write("d\n\u00b2/1/2026\n")
        self.rules_path = os.path.join(self.tmp, "rules.toml")
        with open(self.rules_path, "w") as fh:
            fh.write('[transforms]\nd = "date_iso"\n')

    def test_crashing_cell_is_recorded_as_skipped(self):
        summary = reportgen.summarize_file(
            ["d"], [["\u00b2/1/2026"]], {"d": "date_iso"})
        self.assertEqual(len(summary["skipped_rows"]), 1)
        self.assertIn("ValueError", summary["skipped_rows"][0]["reason"])

    def test_crashing_cell_fails_the_run_and_emits_nothing(self):
        with self.assertRaises(reportgen.ValidationError):
            reportgen.run(self.rules_path, self.inp, self.out, self.cache_path)
        self.assertFalse(os.path.exists(os.path.join(self.out, "report.json")))
        self.assertFalse(os.path.exists(os.path.join(self.out, "report.html")))
        self.assertFalse(os.path.exists(self.cache_path))


class RulesReadCountTests(unittest.TestCase):
    """Regression: the rules file must be read at most once per run; it
    used to be reloaded once per input file."""

    def test_rules_file_read_exactly_once_per_run(self):
        tmp = tempfile.mkdtemp(prefix="rg3-reads-")
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        inp = os.path.join(tmp, "in")
        os.makedirs(inp)
        for i in range(3):
            with open(os.path.join(inp, "f%d.csv" % i), "w") as fh:
                fh.write("a\n%d\n" % i)
        rules_path = os.path.join(tmp, "rules.toml")
        with open(rules_path, "w") as fh:
            fh.write('[transforms]\na = "trim"\n')
        out = os.path.join(tmp, "out")
        cache_path = os.path.join(tmp, "cache", "state.json")

        load_calls = []
        real_load_rules = reportgen.load_rules

        def counting_load_rules(path):
            load_calls.append(path)
            return real_load_rules(path)

        rules_opens = []
        real_open = builtins.open

        def counting_open(file, *args, **kwargs):
            if isinstance(file, str) and file == rules_path:
                rules_opens.append(file)
            return real_open(file, *args, **kwargs)

        with mock.patch.object(reportgen, "load_rules", counting_load_rules):
            with mock.patch.object(builtins, "open", counting_open):
                reportgen.run(rules_path, inp, out, cache_path)
        self.assertEqual(load_calls, [rules_path])
        self.assertEqual(len(rules_opens), 1)


class CacheVersionTests(unittest.TestCase):
    """GOAL item 2 regression: a cache/state.json written by a future
    schema version (registry_version greater than the current one) must
    not crash the run — treat the cache as empty, do the full run, and
    rewrite a valid state file. Also covers the documented contract that
    an entry stamped with any other registry version is never reused
    (the old code never compared the version at lookup)."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="rg3-ver-")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.inp = os.path.join(self.tmp, "in")
        os.makedirs(self.inp)
        self.csv_path = os.path.join(self.inp, "f.csv")
        with open(self.csv_path, "w") as fh:
            fh.write("amount\n$1.00\n")
        self.rules_path = os.path.join(self.tmp, "rules.toml")
        with open(self.rules_path, "w") as fh:
            fh.write('[transforms]\namount = "currency_amount"\n')
        self.out = os.path.join(self.tmp, "out")
        self.cache_path = os.path.join(self.tmp, "cache", "state.json")
        os.makedirs(os.path.dirname(self.cache_path))
        self.digest = cache.file_digest(self.csv_path)
        self.rules_fp = cache.rules_fingerprint(
            reportgen.load_rules(self.rules_path))

    def _write_state(self, version, summary):
        """Write a state file whose entry matches this run's digest and
        rules fingerprint, so a lookup that skips the version check would
        happily reuse it."""
        state = {"f.csv": {"digest": self.digest, "rows": 1,
                           "generated_from": 1, "rules_fp": self.rules_fp,
                           "registry_version": version, "summary": summary}}
        with open(self.cache_path, "w") as fh:
            json.dump(state, fh)

    def test_future_version_state_treated_as_empty_and_rewritten(self):
        future = str(int(cache.REGISTRY_VERSION) + 1)
        poisoned = {"columns": {"amount": {"non_empty": 999, "distinct": 999,
                                           "sample": ["poison"],
                                           "numeric_sum": 999.0}}}
        self._write_state(future, poisoned)
        report = reportgen.run(self.rules_path, self.inp, self.out,
                               self.cache_path)
        cols = report["files"]["f.csv"]["summary"]["columns"]
        self.assertNotIn("poison", str(cols))
        self.assertEqual(cols["amount"]["numeric_sum"], 1.0)
        with open(self.cache_path) as fh:
            state = json.load(fh)
        entry = state["f.csv"]
        self.assertEqual(entry["registry_version"], cache.REGISTRY_VERSION)
        self.assertEqual(entry["summary"], report["files"]["f.csv"]["summary"])

    def test_future_version_incompatible_shape_does_not_crash(self):
        future = str(int(cache.REGISTRY_VERSION) + 1)
        self._write_state(future, {"stats": []})  # future schema, no "columns"
        report = reportgen.run(self.rules_path, self.inp, self.out,
                               self.cache_path)
        cols = report["files"]["f.csv"]["summary"]["columns"]
        self.assertEqual(cols["amount"]["numeric_sum"], 1.0)

    def test_old_version_entry_not_reused(self):
        old = str(int(cache.REGISTRY_VERSION) - 1)
        self._write_state(old, {"columns": {}})
        report = reportgen.run(self.rules_path, self.inp, self.out,
                               self.cache_path)
        cols = report["files"]["f.csv"]["summary"]["columns"]
        self.assertEqual(cols["amount"]["numeric_sum"], 1.0)


class GeneratedFromStabilityTests(unittest.TestCase):
    """Regression: generated_from used to be stored in the cache with a
    different definition (header columns covered by rules) than the fresh
    run computed (rules-mapped columns with at least one non-empty cell),
    so the report changed between run 1 and run 2 on identical inputs."""

    def test_report_identical_on_fresh_and_cached_run(self):
        tmp = tempfile.mkdtemp(prefix="rg3-genfrom-")
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        inp = os.path.join(tmp, "in")
        os.makedirs(inp)
        with open(os.path.join(inp, "f.csv"), "w") as fh:
            fh.write("a,b\n1,\n2,\n")  # b is mapped but always empty
        rules_path = os.path.join(tmp, "rules.toml")
        with open(rules_path, "w") as fh:
            fh.write('[transforms]\na = "trim"\nb = "trim"\n')
        out = os.path.join(tmp, "out")
        cache_path = os.path.join(tmp, "cache", "state.json")
        report1 = reportgen.run(rules_path, inp, out, cache_path)
        report2 = reportgen.run(rules_path, inp, out, cache_path)
        self.assertEqual(report1, report2)
        self.assertEqual(report1["files"]["f.csv"]["generated_from"], 1)


if __name__ == "__main__":
    unittest.main()
