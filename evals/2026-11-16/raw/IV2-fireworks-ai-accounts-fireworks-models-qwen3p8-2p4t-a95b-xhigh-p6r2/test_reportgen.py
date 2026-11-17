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
    """Feature: rules may map a column to `boolean`; yes/true -> 1.0,
    no/false -> 0.0 (case-insensitive), anything else TransformError."""

    def test_affirmative_and_negative_forms(self):
        for raw in ("yes", "YES", "Yes", "true", "TRUE", "True"):
            value = transforms.apply("boolean", raw)
            self.assertEqual(value, 1.0)
            self.assertIsInstance(value, float)
        for raw in ("no", "NO", "No", "false", "FALSE", "False"):
            value = transforms.apply("boolean", raw)
            self.assertEqual(value, 0.0)
            self.assertIsInstance(value, float)

    def test_other_inputs_raise(self):
        for raw in ("maybe", "1", "0", "y", "n", "", "tru", "yes/no"):
            with self.assertRaises(transforms.TransformError):
                transforms.apply("boolean", raw)

    def test_boolean_column_end_to_end(self):
        tmp = tempfile.mkdtemp(prefix="rg3-bool-")
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        inp = os.path.join(tmp, "in")
        os.makedirs(inp)
        with open(os.path.join(inp, "flags.csv"), "w") as fh:
            fh.write("id,flag\n1,yes\n2,NO\n3,True\n4,false\n")
        rules_path = os.path.join(tmp, "rules.toml")
        with open(rules_path, "w") as fh:
            fh.write('[transforms]\nflag = "boolean"\n')
        out = os.path.join(tmp, "out")
        report = reportgen.run(rules_path, inp, out,
                               os.path.join(tmp, "cache", "state.json"))
        cols = report["files"]["flags.csv"]["summary"]["columns"]
        # numeric_sum sums the distinct transformed values: 0.0 + 1.0.
        self.assertEqual(cols["flag"]["numeric_sum"], 1.0)
        self.assertEqual(cols["flag"]["sample"], [0.0, 1.0])
        self.assertEqual(cols["flag"]["distinct"], 2)


class TransformFailurePolicyRegressionTests(unittest.TestCase):
    """Regression (defect: report.html and cache entries were written
    before validation): a run in which any cell failed its transform must
    end with no report emitted and no cache state left behind, whether the
    failure was caught and carried on from or crashed the pass."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="rg3-fail-")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.out = os.path.join(self.tmp, "out")
        self.cache_path = os.path.join(self.tmp, "cache", "state.json")

    def _write(self, relpath, content):
        path = os.path.join(self.tmp, relpath)
        with open(path, "w") as fh:
            fh.write(content)
        return path

    def _assert_nothing_emitted(self):
        self.assertFalse(os.path.exists(os.path.join(self.out, "report.html")))
        self.assertFalse(os.path.exists(os.path.join(self.out, "report.json")))
        self.assertFalse(os.path.exists(self.cache_path))

    def test_caught_transform_failure_emits_no_report_or_cache(self):
        inp = os.path.join(self.tmp, "in")
        os.makedirs(inp)
        self._write(os.path.join("in", "bad.csv"), "item\nnot-a-number\n")
        rules = self._write("rules.toml", '[transforms]\nitem = "round2"\n')
        with self.assertRaises(reportgen.ValidationError):
            reportgen.run(rules, inp, self.out, self.cache_path)
        self._assert_nothing_emitted()

    def test_unhandled_transform_crash_emits_no_report_or_cache(self):
        def boom(value):
            raise RuntimeError("transform crashed")
        transforms.REGISTRY["boom"] = boom
        self.addCleanup(transforms.REGISTRY.pop, "boom", None)
        inp = os.path.join(self.tmp, "in")
        os.makedirs(inp)
        # a.csv transforms cleanly first; b.csv then crashes mid-pass. A
        # pre-validation per-file cache save would leave a.csv's entry.
        self._write(os.path.join("in", "a.csv"), "item\n1\n")
        self._write(os.path.join("in", "b.csv"), "thing\nx\n")
        rules = self._write(
            "rules.toml", '[transforms]\nitem = "round2"\nthing = "boom"\n')
        with self.assertRaises(RuntimeError):
            reportgen.run(rules, inp, self.out, self.cache_path)
        self._assert_nothing_emitted()


class HtmlEscapingRegressionTests(unittest.TestCase):
    """Regression (defect: render_html interpolated raw text — the shipped
    legacy suite caught sample values): file names, column names and sample
    values must all be HTML-escaped."""

    def test_names_and_samples_are_escaped(self):
        tmp = tempfile.mkdtemp(prefix="rg3-esc-")
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        inp = os.path.join(tmp, "in")
        os.makedirs(inp)
        with open(os.path.join(inp, "da<ta>.csv"), "w") as fh:
            fh.write("c<ol>,plain\nv & 1,x\n")
        rules_path = os.path.join(tmp, "rules.toml")
        with open(rules_path, "w") as fh:
            fh.write("[transforms]\n")
        out = os.path.join(tmp, "out")
        reportgen.run(rules_path, inp, out,
                      os.path.join(tmp, "cache", "state.json"))
        with open(os.path.join(out, "report.html")) as fh:
            html_text = fh.read()
        self.assertNotIn("<col>", html_text)
        self.assertNotIn("da<ta>", html_text)
        self.assertIn("c&lt;ol&gt;", html_text)
        self.assertIn("da&lt;ta&gt;.csv", html_text)
        self.assertIn("v &amp; 1", html_text)


class GeneratedFromCacheRegressionTests(unittest.TestCase):
    """Regression (defect: cache.make_entry counted every rules-mapped
    column while reportgen.generated_from counted only those with a
    non-empty cell): a cache hit must reproduce the fresh run's report
    exactly, `generated_from` included."""

    def test_generated_from_same_on_fresh_and_cached_run(self):
        tmp = tempfile.mkdtemp(prefix="rg3-gf-")
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        inp = os.path.join(tmp, "in")
        os.makedirs(inp)
        # `status` is rules-mapped but empty in every row.
        with open(os.path.join(inp, "dev.csv"), "w") as fh:
            fh.write("id,status\n1,\n2,\n")
        rules_path = os.path.join(tmp, "rules.toml")
        with open(rules_path, "w") as fh:
            fh.write('[transforms]\nid = "trim"\nstatus = "upper"\n')
        out = os.path.join(tmp, "out")
        cache_path = os.path.join(tmp, "cache", "state.json")
        fresh = reportgen.run(rules_path, inp, out, cache_path)
        cached = reportgen.run(rules_path, inp, out, cache_path)
        gf_fresh = fresh["files"]["dev.csv"]["generated_from"]
        gf_cached = cached["files"]["dev.csv"]["generated_from"]
        self.assertEqual(gf_fresh, 1)
        self.assertEqual(gf_cached, gf_fresh)


class FutureSchemaCacheRegressionTests(unittest.TestCase):
    """Regression / cache hygiene: a cache/state.json written by a future
    schema version (version stamp greater than REGISTRY_VERSION) must not
    crash the run — treat the cache as empty, do the full run, rewrite a
    valid state file."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="rg3-fut-")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.inp = os.path.join(self.tmp, "in")
        os.makedirs(self.inp)
        self.csv_path = os.path.join(self.inp, "dev.csv")
        with open(self.csv_path, "w") as fh:
            fh.write("id\n1\n")
        self.rules_path = os.path.join(self.tmp, "rules.toml")
        with open(self.rules_path, "w") as fh:
            fh.write('[transforms]\nid = "trim"\n')
        self.out = os.path.join(self.tmp, "out")
        self.cache_path = os.path.join(self.tmp, "cache", "state.json")
        os.makedirs(os.path.dirname(self.cache_path))

    def _write_state(self, state):
        with open(self.cache_path, "w") as fh:
            json.dump(state, fh)

    def test_future_entry_state_does_not_crash_and_is_rewritten(self):
        rules = reportgen.load_rules(self.rules_path)
        self._write_state({"dev.csv": {
            "digest": cache.file_digest(self.csv_path),
            "rows": "many",
            "generated_from": None,
            "rules_fp": cache.rules_fingerprint(rules),
            "registry_version": str(int(cache.REGISTRY_VERSION) + 1),
            # A summary shape this build cannot even validate: reusing the
            # entry would crash the run.
            "summary": ["not", "a", "mapping"]}})
        report = reportgen.run(self.rules_path, self.inp, self.out,
                               self.cache_path)
        self.assertEqual(report["files"]["dev.csv"]["rows"], 1)
        state = cache.load_state(self.cache_path)
        self.assertEqual(set(state), {"dev.csv"})
        entry = state["dev.csv"]
        self.assertEqual(entry["registry_version"], cache.REGISTRY_VERSION)
        self.assertEqual(entry["summary"]["skipped_rows"], [])

    def test_future_top_level_version_state_is_rewritten(self):
        self._write_state({
            "version": int(cache.REGISTRY_VERSION) + 100,
            "files": {"dev.csv": {"rows": "bogus"}}})
        report = reportgen.run(self.rules_path, self.inp, self.out,
                               self.cache_path)
        self.assertEqual(report["files"]["dev.csv"]["rows"], 1)
        state = cache.load_state(self.cache_path)
        self.assertEqual(set(state), {"dev.csv"})

    def test_current_state_still_reused(self):
        first = reportgen.run(self.rules_path, self.inp, self.out,
                              self.cache_path)
        with open(self.cache_path) as fh:
            before = json.load(fh)
        second = reportgen.run(self.rules_path, self.inp, self.out,
                               self.cache_path)
        with open(self.cache_path) as fh:
            after = json.load(fh)
        self.assertEqual(before, after)
        self.assertEqual(first["files"]["dev.csv"],
                         second["files"]["dev.csv"])


if __name__ == "__main__":
    unittest.main()
