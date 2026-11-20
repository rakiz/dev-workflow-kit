"""Regression tests for the boolean transform, cache hygiene, rules
read count, HTML escaping, and transform-failure atomicity."""

import builtins
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


def read_bytes(path):
    with open(path, "rb") as fh:
        return fh.read()


class BooleanTransformTests(unittest.TestCase):
    def test_affirmative_forms(self):
        for raw in ("yes", "YES", "Yes", "true", "TRUE", "True", " yes "):
            self.assertEqual(transforms.apply("boolean", raw), 1.0)

    def test_negative_forms(self):
        for raw in ("no", "NO", "No", "false", "FALSE", "False", " no "):
            self.assertEqual(transforms.apply("boolean", raw), 0.0)

    def test_rejects_other_values(self):
        for raw in ("", "maybe", "1", "0", "y", "n"):
            with self.assertRaises(transforms.TransformError):
                transforms.apply("boolean", raw)

    def test_end_to_end(self):
        tmp = tempfile.mkdtemp(prefix="rg3-boolean-")
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        inp = os.path.join(tmp, "in")
        os.makedirs(inp)
        with open(os.path.join(inp, "flags.csv"), "w") as fh:
            fh.write("flag\nYES\nno\nTrue\n")
        rules_path = os.path.join(tmp, "rules.toml")
        with open(rules_path, "w") as fh:
            fh.write('[transforms]\nflag = "boolean"\n')
        report = reportgen.run(rules_path, inp, os.path.join(tmp, "out"),
                               os.path.join(tmp, "cache", "state.json"))
        col = report["files"]["flags.csv"]["summary"]["columns"]["flag"]
        self.assertEqual(col["distinct"], 2)
        self.assertEqual(col["numeric_sum"], 1.0)


class CacheHygieneTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="rg3-hygiene-")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.inp = os.path.join(self.tmp, "in")
        os.makedirs(self.inp)
        self.csv_path = os.path.join(self.inp, "flags.csv")
        with open(self.csv_path, "w") as fh:
            fh.write("flag\nYES\nno\n")
        self.rules_path = os.path.join(self.tmp, "rules.toml")
        with open(self.rules_path, "w") as fh:
            fh.write('[transforms]\nflag = "boolean"\n')
        self.out = os.path.join(self.tmp, "out")
        self.cache_path = os.path.join(self.tmp, "cache", "state.json")

    def write_state(self, state):
        os.makedirs(os.path.dirname(self.cache_path), exist_ok=True)
        with open(self.cache_path, "w") as fh:
            json.dump(state, fh)

    def matching_entry(self, version):
        rules = reportgen.load_rules(self.rules_path)
        return {
            "digest": cache.file_digest(self.csv_path),
            "rows": 99,
            "generated_from": 99,
            "rules_fp": cache.rules_fingerprint(rules),
            "registry_version": version,
            "summary": {"columns": {}, "skipped_rows": []},
        }

    def test_future_entry_version_treated_as_empty(self):
        future = str(int(cache.REGISTRY_VERSION) + 1)
        self.write_state({"flags.csv": self.matching_entry(future)})
        report = reportgen.run(self.rules_path, self.inp, self.out,
                               self.cache_path)
        self.assertEqual(report["total_rows"], 2)
        col = report["files"]["flags.csv"]["summary"]["columns"]["flag"]
        self.assertEqual(col["numeric_sum"], 1.0)
        state = cache.load_state(self.cache_path)
        self.assertEqual(state["flags.csv"]["rows"], 2)
        self.assertEqual(state["flags.csv"]["registry_version"],
                         cache.REGISTRY_VERSION)

    def test_future_top_level_version_treated_as_empty(self):
        entry = self.matching_entry(cache.REGISTRY_VERSION)
        self.write_state({"version": str(int(cache.REGISTRY_VERSION) + 1),
                          "flags.csv": entry})
        report = reportgen.run(self.rules_path, self.inp, self.out,
                               self.cache_path)
        self.assertEqual(report["total_rows"], 2)
        self.assertEqual(cache.load_state(self.cache_path)["flags.csv"]["rows"], 2)

    def test_stale_registry_version_not_reused(self):
        reportgen.run(self.rules_path, self.inp, self.out, self.cache_path)
        state = cache.load_state(self.cache_path)
        state["flags.csv"]["registry_version"] = "1"
        state["flags.csv"]["rows"] = 99
        state["flags.csv"]["summary"] = {"columns": {}, "skipped_rows": []}
        self.write_state(state)
        report = reportgen.run(self.rules_path, self.inp, self.out,
                               self.cache_path)
        self.assertEqual(report["total_rows"], 2)
        col = report["files"]["flags.csv"]["summary"]["columns"]["flag"]
        self.assertEqual(col["numeric_sum"], 1.0)

    def test_entry_with_skipped_rows_not_reused(self):
        reportgen.run(self.rules_path, self.inp, self.out, self.cache_path)
        state = cache.load_state(self.cache_path)
        state["flags.csv"]["summary"] = {
            "columns": {}, "skipped_rows": [{"row": 2, "column": "flag",
                                             "reason": "bad"}]}
        self.write_state(state)
        report = reportgen.run(self.rules_path, self.inp, self.out,
                               self.cache_path)
        col = report["files"]["flags.csv"]["summary"]["columns"]["flag"]
        self.assertEqual(col["numeric_sum"], 1.0)

    def test_cached_report_matches_first_run(self):
        with open(os.path.join(self.inp, "flags.csv"), "w") as fh:
            fh.write("flag,status\nYES,\n")
        with open(self.rules_path, "w") as fh:
            fh.write('[transforms]\nflag = "boolean"\nstatus = "upper"\n')
        first = reportgen.run(self.rules_path, self.inp, self.out,
                              self.cache_path)
        second = reportgen.run(self.rules_path, self.inp, self.out,
                               self.cache_path)
        self.assertEqual(first, second)
        self.assertEqual(
            first["files"]["flags.csv"]["generated_from"], 1)


class RulesReadCountTests(unittest.TestCase):
    def test_rules_file_read_once_per_run(self):
        tmp = tempfile.mkdtemp(prefix="rg3-reads-")
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        inp = os.path.join(tmp, "in")
        os.makedirs(inp)
        for name in ("a.csv", "b.csv"):
            with open(os.path.join(inp, name), "w") as fh:
                fh.write("name\none\n")
        rules_path = os.path.join(tmp, "rules.toml")
        with open(rules_path, "w") as fh:
            fh.write('[transforms]\nname = "upper"\n')
        reads = []
        real_open = builtins.open

        def counting_open(file, *args, **kwargs):
            if os.path.abspath(str(file)) == os.path.abspath(rules_path):
                reads.append(file)
            return real_open(file, *args, **kwargs)

        builtins.open = counting_open
        try:
            reportgen.run(rules_path, inp, os.path.join(tmp, "out"),
                          os.path.join(tmp, "cache", "state.json"))
        finally:
            builtins.open = real_open
        self.assertEqual(len(reads), 1)


class FailureAtomicityTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="rg3-fail-")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.inp = os.path.join(self.tmp, "in")
        os.makedirs(self.inp)
        with open(os.path.join(self.inp, "flags.csv"), "w") as fh:
            fh.write("flag\nYES\nno\n")
        self.rules_path = os.path.join(self.tmp, "rules.toml")
        with open(self.rules_path, "w") as fh:
            fh.write('[transforms]\nflag = "boolean"\n')
        self.out = os.path.join(self.tmp, "out")
        self.cache_path = os.path.join(self.tmp, "cache", "state.json")

    def run_main(self):
        return reportgen.main([
            "--rules", self.rules_path, "--input", self.inp,
            "--output", self.out, "--cache", self.cache_path])

    def seed_good_run(self):
        self.assertEqual(self.run_main(), 0)

    def snapshot(self):
        paths = [os.path.join(self.out, "report.json"),
                 os.path.join(self.out, "report.html"), self.cache_path]
        return [read_bytes(p) for p in paths]

    def test_invalid_boolean_leaves_outputs_and_cache_untouched(self):
        self.seed_good_run()
        before = self.snapshot()
        with open(os.path.join(self.inp, "flags.csv"), "w") as fh:
            fh.write("flag\nYES\nmaybe\n")
        self.assertEqual(self.run_main(), 1)
        self.assertEqual(self.snapshot(), before)

    def test_unhandled_transform_crash_is_atomic(self):
        self.seed_good_run()
        before = self.snapshot()
        with open(self.rules_path, "w") as fh:
            fh.write('[transforms]\nflag = "boom"\n')

        def explode(value):
            raise RuntimeError("boom")

        transforms.REGISTRY["boom"] = explode
        try:
            self.assertEqual(self.run_main(), 1)
        finally:
            del transforms.REGISTRY["boom"]
        self.assertEqual(self.snapshot(), before)

    def test_failed_first_run_emits_nothing(self):
        with open(os.path.join(self.inp, "flags.csv"), "w") as fh:
            fh.write("flag\nmaybe\n")
        self.assertEqual(self.run_main(), 1)
        self.assertFalse(os.path.exists(os.path.join(self.out, "report.json")))
        self.assertFalse(os.path.exists(os.path.join(self.out, "report.html")))
        self.assertFalse(os.path.exists(self.cache_path))


class HtmlEscapingTests(unittest.TestCase):
    def test_sample_values_are_escaped(self):
        tmp = tempfile.mkdtemp(prefix="rg3-escape-")
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        inp = os.path.join(tmp, "in")
        os.makedirs(inp)
        with open(os.path.join(inp, "labels.csv"), "w") as fh:
            fh.write("label\n<b> & bold\n")
        report = reportgen.run(RULES, inp, os.path.join(tmp, "out"),
                               os.path.join(tmp, "cache", "state.json"))
        report["files"]["labels.csv"]["summary"]["columns"]["label"]["sample"] = [
            "red <b> & bold"]
        rendered = reportgen.render_html(report)
        self.assertNotIn("<b>", rendered)
        self.assertIn("red &lt;b&gt; &amp; bold", rendered)


if __name__ == "__main__":
    unittest.main()
