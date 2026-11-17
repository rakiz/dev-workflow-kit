"""Regression tests — one per defect fixed alongside the GOAL.md work.

D1  render_html emitted file names, column names and sample values
    unescaped, leaking markup and '&' into the page (shipped
    test_legacy_report was red).
D2  run() wrote report.html before validate_summary, so a run with
    transform failures still emitted a report.
D3  run() called cache.save_state inside the per-file loop, before
    validation, so a run with transform failures left cache entries
    derived from an incomplete transform pass.
D4  a transform crashing with a non-TransformError exception escaped as
    an unhandled traceback instead of ending the run the same way as
    every other transform failure.
D5  the cache lookup never compared registry_version, so summaries
    produced under an older transform registry were reused despite the
    documented design ("the version is compared at lookup").
D6  cache.make_entry stored a different generated_from than the report
    computed, so report.json content depended on whether the run was a
    cache hit or a fresh pass.
"""

import os
import shutil
import tempfile
import unittest

import cache
import reportgen
import transforms


class D1HtmlEscapingRegression(unittest.TestCase):
    def test_render_html_escapes_names_and_samples(self):
        report = {"files": {"a<b>.csv": {
            "rows": 1,
            "summary": {"columns": {
                "lab&l": {"non_empty": 1, "distinct": 1,
                          "sample": ["red <b> & bold"]}}}}}}
        out = reportgen.render_html(report)
        self.assertNotIn("<b>", out)
        self.assertIn("red &lt;b&gt; &amp; bold", out)
        self.assertIn("lab&amp;l", out)


class FailurePolicyTestBase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="rg3-reg-")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.inp = os.path.join(self.tmp, "in")
        os.makedirs(self.inp)
        self.out = os.path.join(self.tmp, "out")
        self.cache_path = os.path.join(self.tmp, "cache", "state.json")

    def _scenario(self, csv_text, rules_text):
        with open(os.path.join(self.inp, "t.csv"), "w") as fh:
            fh.write(csv_text)
        rules_path = os.path.join(self.tmp, "rules.toml")
        with open(rules_path, "w") as fh:
            fh.write(rules_text)
        return rules_path


class D2NoReportOnTransformFailureRegression(FailurePolicyTestBase):
    def test_failed_run_emits_no_report(self):
        rules = self._scenario("v\n1\nnope\n", '[transforms]\nv = "round2"\n')
        with self.assertRaises(reportgen.ValidationError):
            reportgen.run(rules, self.inp, self.out, self.cache_path)
        self.assertFalse(os.path.exists(os.path.join(self.out,
                                                     "report.html")))
        self.assertFalse(os.path.exists(os.path.join(self.out,
                                                     "report.json")))


class D3NoCacheStateOnTransformFailureRegression(FailurePolicyTestBase):
    def test_failed_run_leaves_no_cache_state(self):
        rules = self._scenario("v\n1\nnope\n", '[transforms]\nv = "round2"\n')
        with self.assertRaises(reportgen.ValidationError):
            reportgen.run(rules, self.inp, self.out, self.cache_path)
        self.assertFalse(os.path.exists(self.cache_path))

    def test_good_file_does_not_get_cached_when_a_later_file_fails(self):
        with open(os.path.join(self.inp, "a_good.csv"), "w") as fh:
            fh.write("v\n1\n")
        with open(os.path.join(self.inp, "b_bad.csv"), "w") as fh:
            fh.write("v\nnope\n")
        rules_path = os.path.join(self.tmp, "rules.toml")
        with open(rules_path, "w") as fh:
            fh.write('[transforms]\nv = "round2"\n')
        with self.assertRaises(reportgen.ValidationError):
            reportgen.run(rules_path, self.inp, self.out, self.cache_path)
        self.assertFalse(os.path.exists(self.cache_path))


class D4CrashIsATransformFailureRegression(FailurePolicyTestBase):
    def test_crashing_transform_ends_run_like_any_other_failure(self):
        def boom(value):
            raise RuntimeError("boom")

        transforms.REGISTRY["boom"] = boom
        self.addCleanup(transforms.REGISTRY.pop, "boom", None)
        rules = self._scenario("v\nx\n", '[transforms]\nv = "boom"\n')
        with self.assertRaises(reportgen.ValidationError):
            reportgen.run(rules, self.inp, self.out, self.cache_path)
        self.assertFalse(os.path.exists(os.path.join(self.out,
                                                     "report.html")))
        self.assertFalse(os.path.exists(os.path.join(self.out,
                                                     "report.json")))
        self.assertFalse(os.path.exists(self.cache_path))


class D5RegistryVersionComparedAtLookupRegression(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="rg3-ver-")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.inp = os.path.join(self.tmp, "in")
        os.makedirs(self.inp)
        with open(os.path.join(self.inp, "t.csv"), "w") as fh:
            fh.write("v\n1\n")
        self.rules = os.path.join(self.tmp, "rules.toml")
        with open(self.rules, "w") as fh:
            fh.write('[transforms]\nv = "round2"\n')
        self.out = os.path.join(self.tmp, "out")
        self.cache_path = os.path.join(self.tmp, "cache", "state.json")

    def test_entry_from_older_registry_is_not_reused(self):
        reportgen.run(self.rules, self.inp, self.out, self.cache_path)
        state = cache.load_state(self.cache_path)
        entry = state["t.csv"]
        entry["registry_version"] = str(int(cache.REGISTRY_VERSION) - 1)
        # poison the cached summary so reuse would be observable
        entry["summary"]["columns"]["v"]["numeric_sum"] = -999.0
        cache.save_state({"t.csv": entry}, path=self.cache_path)

        report = reportgen.run(self.rules, self.inp, self.out,
                               self.cache_path)
        col = report["files"]["t.csv"]["summary"]["columns"]["v"]
        self.assertEqual(col["numeric_sum"], 1.0)
        state = cache.load_state(self.cache_path)
        self.assertEqual(state["t.csv"]["registry_version"],
                         cache.REGISTRY_VERSION)
        self.assertEqual(
            state["t.csv"]["summary"]["columns"]["v"]["numeric_sum"], 1.0)


class D6GeneratedFromConsistentAcrossCacheRegression(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="rg3-gen-")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.inp = os.path.join(self.tmp, "in")
        os.makedirs(self.inp)
        self.out = os.path.join(self.tmp, "out")
        self.cache_path = os.path.join(self.tmp, "cache", "state.json")

    def test_cached_run_reports_same_generated_from_as_fresh_run(self):
        # a rules-mapped column whose cells are all empty: the report
        # counts only rules-mapped columns with a non-empty cell
        with open(os.path.join(self.inp, "t.csv"), "w") as fh:
            fh.write("v,label\n,beta\n")
        rules_path = os.path.join(self.tmp, "rules.toml")
        with open(rules_path, "w") as fh:
            fh.write('[transforms]\nv = "trim"\n')
        fresh = reportgen.run(rules_path, self.inp, self.out,
                              self.cache_path)
        cached = reportgen.run(rules_path, self.inp, self.out,
                               self.cache_path)
        self.assertEqual(fresh["files"]["t.csv"]["generated_from"], 0)
        self.assertEqual(cached, fresh)


if __name__ == "__main__":
    unittest.main()
