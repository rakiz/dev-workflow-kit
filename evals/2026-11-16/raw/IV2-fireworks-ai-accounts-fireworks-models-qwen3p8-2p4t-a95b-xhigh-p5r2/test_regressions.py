"""Regression tests for the defects fixed alongside the GOAL.md features,
plus tests for the features themselves.

Defects covered (one test per defect, named in each docstring):
  D1  report.html was written before the summaries were validated, so a
      run with a failed transform still emitted a report.
  D2  cache.save_state() ran mid-loop, before validation, so a run with
      a failed transform left cache entries behind — including the
      failed file's own summary.
  D3  a crash inside a transform (any non-TransformError exception)
      escaped the run instead of ending it like every other transform
      failure.
  D4  cache lookup never compared registry_version, contradicting the
      documented contract that entries produced under another registry
      version are never reused.
  D5  cache.make_entry computed generated_from differently from a fresh
      run (header-column count vs non-empty-cell count), so identical
      inputs produced different reports depending on cache state.
  D6  render_html interpolated raw strings, leaking markup into the
      report (the shipped test_legacy_report suite failed on it).

Features covered:
  F1  boolean transform (GOAL.md item 1).
  F2  a cache/state.json written by a future schema version is treated
      as an empty cache and rewritten (GOAL.md item 2).
"""

import json
import os
import shutil
import tempfile
import unittest

import cache
import reportgen
import transforms


def write(path, text):
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)


def read_json(path):
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


class TmpCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="rg3-reg-")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.inp = os.path.join(self.tmp, "in")
        os.makedirs(self.inp)
        self.out = os.path.join(self.tmp, "out")
        self.cache_path = os.path.join(self.tmp, "cache", "state.json")
        self.rules_path = os.path.join(self.tmp, "rules.toml")

    def run_tool(self):
        return reportgen.run(self.rules_path, self.inp, self.out,
                             self.cache_path)


class BooleanTransformTests(TmpCase):
    """F1: the boolean transform."""

    def test_affirmative_forms_report_one(self):
        for raw in ("yes", "YES", "Yes", "true", "TRUE", "True", " yes "):
            value = transforms.apply("boolean", raw)
            self.assertIsInstance(value, float)
            self.assertEqual(value, 1.0)

    def test_negative_forms_report_zero(self):
        for raw in ("no", "NO", "No", "false", "FALSE", "False", " no "):
            value = transforms.apply("boolean", raw)
            self.assertIsInstance(value, float)
            self.assertEqual(value, 0.0)

    def test_any_other_input_raises(self):
        for raw in ("maybe", "", "1", "0", "y", "n", "truthy", "yes no"):
            with self.assertRaises(transforms.TransformError):
                transforms.apply("boolean", raw)

    def test_boolean_column_end_to_end(self):
        write(os.path.join(self.inp, "flags.csv"), "flag\nYes\nno\nTRUE\nfalse\n")
        write(self.rules_path, '[transforms]\nflag = "boolean"\n')
        report = self.run_tool()
        col = report["files"]["flags.csv"]["summary"]["columns"]["flag"]
        self.assertEqual(col["numeric_sum"], 2.0)
        self.assertEqual(col["distinct"], 2)
        self.assertEqual(col["sample"], [0.0, 1.0])
        self.assertEqual(col["non_empty"], 4)


class FailurePolicyTests(TmpCase):
    """Invariant 1: a run in which any cell failed its transform ends the
    same way however the failure surfaced — no report, no cache state."""

    def make_failing_input(self):
        write(os.path.join(self.inp, "a.csv"), "item\n1\n2\n")
        write(os.path.join(self.inp, "b.csv"), "item\noops\n")
        write(self.rules_path, '[transforms]\nitem = "round2"\n')

    def test_failed_run_emits_no_report(self):
        """D1: report.html used to be written before validation."""
        self.make_failing_input()
        with self.assertRaises(reportgen.ValidationError):
            self.run_tool()
        self.assertFalse(os.path.exists(os.path.join(self.out, "report.html")))
        self.assertFalse(os.path.exists(os.path.join(self.out, "report.json")))

    def test_failed_run_leaves_no_cache_state(self):
        """D2: cache entries used to be saved mid-run, before validation,
        so the good file's entry (and the failed file's own summary)
        survived a failed run."""
        self.make_failing_input()
        with self.assertRaises(reportgen.ValidationError):
            self.run_tool()
        self.assertFalse(os.path.exists(self.cache_path))
        self.assertFalse(os.path.exists(os.path.dirname(self.cache_path)))

    def test_transform_crash_ends_run_like_any_other_failure(self):
        """D3: a non-TransformError crash inside a transform used to
        escape the run; it must end the run the same way a raised
        TransformError does."""
        def boom(value):
            raise RuntimeError("transform crashed")

        transforms.REGISTRY["boom"] = boom
        self.addCleanup(transforms.REGISTRY.pop, "boom", None)
        write(os.path.join(self.inp, "a.csv"), "item\n1\n")
        write(os.path.join(self.inp, "b.csv"), "item\nx\n")
        write(self.rules_path, '[transforms]\nitem = "boom"\n')
        with self.assertRaises(reportgen.ValidationError):
            self.run_tool()
        self.assertFalse(os.path.exists(os.path.join(self.out, "report.html")))
        self.assertFalse(os.path.exists(os.path.join(self.out, "report.json")))
        self.assertFalse(os.path.exists(self.cache_path))

    def test_failed_run_does_not_touch_preexisting_state(self):
        """Chosen failure policy: a failed run writes nothing at all; a
        state file left by an earlier, complete run survives untouched
        (its entries are not derived from the failed pass)."""
        write(os.path.join(self.inp, "a.csv"), "item\n1\n2\n")
        write(self.rules_path, '[transforms]\nitem = "round2"\n')
        self.run_tool()
        before = read_json(self.cache_path)
        write(os.path.join(self.inp, "a.csv"), "item\noops\n")
        with self.assertRaises(reportgen.ValidationError):
            self.run_tool()
        self.assertEqual(read_json(self.cache_path), before)


class CacheVersionTests(TmpCase):
    """Cache lookup honours the registry version and never reuses an
    entry derived from an incomplete transform pass."""

    def make_input(self):
        write(os.path.join(self.inp, "t.csv"), "item\n1\n2\n")
        write(self.rules_path, '[transforms]\nitem = "round2"\n')

    def rewrite_state(self, mutate):
        state = read_json(self.cache_path)
        mutate(state)
        with open(self.cache_path, "w", encoding="utf-8") as fh:
            json.dump(state, fh, indent=2, sort_keys=True)

    def test_entry_from_other_registry_version_is_not_reused(self):
        """D4: lookup used to ignore registry_version, so an entry
        stamped by another registry was reused despite the documented
        contract; it must be recomputed instead."""
        self.make_input()
        self.run_tool()

        def mutate(state):
            state["t.csv"]["registry_version"] = "1"
            state["t.csv"]["rows"] = 999

        self.rewrite_state(mutate)
        report = self.run_tool()
        self.assertEqual(report["files"]["t.csv"]["rows"], 2)
        state = read_json(self.cache_path)
        self.assertEqual(state["t.csv"]["registry_version"],
                         cache.REGISTRY_VERSION)
        self.assertEqual(state["t.csv"]["rows"], 2)

    def test_cached_entry_with_failed_cells_is_not_reused(self):
        """Invariant 1 hygiene: an entry whose summary records a failed
        cell (e.g. written by pre-fix code, when "boolean" was still an
        unknown transform) must never be reused; the file is recomputed
        and the entry rewritten."""
        write(os.path.join(self.inp, "flags.csv"), "flag\nyes\n")
        write(self.rules_path, '[transforms]\nflag = "boolean"\n')
        self.run_tool()

        def mutate(state):
            state["flags.csv"]["summary"]["skipped_rows"] = [
                {"row": 2, "column": "flag",
                 "reason": "unknown transform: 'boolean'"}]

        self.rewrite_state(mutate)
        report = self.run_tool()
        col = report["files"]["flags.csv"]["summary"]["columns"]["flag"]
        self.assertEqual(col["numeric_sum"], 1.0)
        state = read_json(self.cache_path)
        self.assertEqual(state["flags.csv"]["summary"]["skipped_rows"], [])


class FutureCacheTests(TmpCase):
    """F2: a cache/state.json written by a future schema version must
    not crash the run — the cache is treated as empty, the full run
    proceeds, and a valid state file is rewritten."""

    def make_input(self):
        write(os.path.join(self.inp, "a.csv"), "item\n1\n2\n")
        write(os.path.join(self.inp, "b.csv"), "item\n3\n4\n5\n")
        write(self.rules_path, '[transforms]\nitem = "round2"\n')

    def future_version(self):
        return int(cache.REGISTRY_VERSION) + 1

    def write_state(self, data):
        os.makedirs(os.path.dirname(self.cache_path), exist_ok=True)
        with open(self.cache_path, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2, sort_keys=True)

    def test_future_entry_versions_treated_as_empty_and_rewritten(self):
        self.make_input()
        self.run_tool()
        state = read_json(self.cache_path)
        state["a.csv"]["registry_version"] = self.future_version()
        state["b.csv"]["registry_version"] = str(self.future_version())
        state["a.csv"]["rows"] = 999
        state["b.csv"]["rows"] = 999
        self.write_state(state)

        report = self.run_tool()
        self.assertEqual(report["total_rows"], 5)
        self.assertEqual(report["files"]["a.csv"]["rows"], 2)
        self.assertEqual(report["files"]["b.csv"]["rows"], 3)
        rewritten = read_json(self.cache_path)
        self.assertEqual(set(rewritten), {"a.csv", "b.csv"})
        for entry in rewritten.values():
            self.assertEqual(entry["registry_version"], cache.REGISTRY_VERSION)
            self.assertNotEqual(entry["rows"], 999)

    def test_future_top_level_version_treated_as_empty_and_rewritten(self):
        self.make_input()
        self.write_state({"version": self.future_version(),
                          "files": {"a.csv": {"checksum": "whatever"}}})
        report = self.run_tool()
        self.assertEqual(report["total_rows"], 5)
        self.assertEqual(report["files"]["a.csv"]["rows"], 2)
        rewritten = read_json(self.cache_path)
        self.assertEqual(set(rewritten), {"a.csv", "b.csv"})
        self.assertNotIn("version", rewritten)
        for entry in rewritten.values():
            self.assertEqual(entry["registry_version"], cache.REGISTRY_VERSION)

    def test_unusable_state_shape_treated_as_empty(self):
        self.make_input()
        self.write_state([1, 2, 3])
        report = self.run_tool()
        self.assertEqual(report["total_rows"], 5)
        rewritten = read_json(self.cache_path)
        self.assertEqual(set(rewritten), {"a.csv", "b.csv"})


class GeneratedFromCacheConsistencyTests(TmpCase):
    def test_generated_from_identical_fresh_and_cached(self):
        """D5: a rules-mapped column that is entirely empty used to be
        counted by cache.make_entry (header-column count) but not by a
        fresh run (non-empty-cell count), so identical inputs produced
        different reports depending on cache state."""
        write(os.path.join(self.inp, "t.csv"), "item,note\n1,\n2,\n")
        write(self.rules_path,
              '[transforms]\nitem = "round2"\nnote = "trim"\n')
        fresh = self.run_tool()
        cached = self.run_tool()
        self.assertEqual(fresh["files"]["t.csv"]["generated_from"], 1)
        self.assertEqual(cached["files"]["t.csv"]["generated_from"], 1)
        state = read_json(self.cache_path)
        self.assertEqual(state["t.csv"]["generated_from"], 1)


class HtmlEscapeTests(TmpCase):
    def test_file_and_column_names_are_escaped(self):
        """D6: render_html interpolated raw strings; the shipped
        test_legacy_report suite covers sample values, this covers file
        and column names."""
        write(os.path.join(self.inp, "ev<il>.csv"), "c<b\nv&v\n")
        write(self.rules_path, "[transforms]\n")
        self.run_tool()
        with open(os.path.join(self.out, "report.html"),
                  encoding="utf-8") as fh:
            page = fh.read()
        self.assertIn("ev&lt;il&gt;.csv", page)
        self.assertIn("c&lt;b", page)
        self.assertIn("v&amp;v", page)
        self.assertNotIn("<b>", page)


if __name__ == "__main__":
    unittest.main()
