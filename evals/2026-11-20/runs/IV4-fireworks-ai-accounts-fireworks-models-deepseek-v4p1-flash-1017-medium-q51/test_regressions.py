"""Regression tests for the boolean transform, cache hygiene, and the
transform-failure invariants."""

import builtins
import contextlib
import io
import json
import os
import shutil
import tempfile
import unittest

import cache
import reportgen
import transforms


def _read_bytes(path):
    with open(path, "rb") as fh:
        return fh.read()


def _read_json(path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


class _TempDirTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="rg3-reg-")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.inp = os.path.join(self.tmp, "in")
        os.makedirs(self.inp)
        self.out = os.path.join(self.tmp, "out")
        self.cache_path = os.path.join(self.tmp, "cache", "state.json")

    def write_input(self, name, text):
        with open(os.path.join(self.inp, name), "w", encoding="utf-8") as fh:
            fh.write(text)

    def write_rules(self, text):
        path = os.path.join(self.tmp, "rules.toml")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text)
        return path

    def run_main(self, rules_path):
        with contextlib.redirect_stdout(io.StringIO()), \
                contextlib.redirect_stderr(io.StringIO()):
            return reportgen.main(["--rules", rules_path, "--input", self.inp,
                                   "--output", self.out,
                                   "--cache", self.cache_path])


class BooleanTransformTests(unittest.TestCase):
    def test_affirmative_and_negative_forms_are_case_insensitive(self):
        for raw in ("yes", "YES", "Yes", "true", "TRUE", "True"):
            self.assertEqual(transforms.apply("boolean", raw), 1.0)
        for raw in ("no", "NO", "No", "false", "FALSE", "False"):
            self.assertEqual(transforms.apply("boolean", raw), 0.0)

    def test_other_values_raise(self):
        for raw in ("maybe", "", "1", "0", "y", "n", "truthy"):
            with self.assertRaises(transforms.TransformError):
                transforms.apply("boolean", raw)


class CacheHygieneTests(_TempDirTest):
    def test_future_state_version_is_treated_as_empty_and_rewritten(self):
        self.write_input("a.csv", "flag\nyes\nno\n")
        rules_path = self.write_rules('[transforms]\nflag = "boolean"\n')
        os.makedirs(os.path.dirname(self.cache_path))
        future = {"version": int(cache.REGISTRY_VERSION) + 1,
                  "a.csv": ["a future schema entry"]}
        with open(self.cache_path, "w", encoding="utf-8") as fh:
            json.dump(future, fh)

        self.assertEqual(self.run_main(rules_path), 0)

        state = _read_json(self.cache_path)
        self.assertEqual(set(state), {"a.csv"})
        self.assertNotIn("version", state)
        self.assertEqual(state["a.csv"]["registry_version"],
                         cache.REGISTRY_VERSION)
        report = _read_json(os.path.join(self.out, "report.json"))
        self.assertEqual(report["files"]["a.csv"]["rows"], 2)

    def test_future_entry_version_is_treated_as_empty(self):
        self.write_input("a.csv", "x\n3\n")
        rules_path = self.write_rules('[transforms]\nx = "round2"\n')
        os.makedirs(os.path.dirname(self.cache_path))
        future = {"a.csv": {"registry_version":
                            str(int(cache.REGISTRY_VERSION) + 1)}}
        with open(self.cache_path, "w", encoding="utf-8") as fh:
            json.dump(future, fh)

        self.assertEqual(self.run_main(rules_path), 0)

        state = _read_json(self.cache_path)
        self.assertEqual(state["a.csv"]["registry_version"],
                         cache.REGISTRY_VERSION)

    def test_stale_registry_version_entry_is_not_reused(self):
        self.write_input("a.csv", "x\n3\n")
        rules_path = self.write_rules('[transforms]\nx = "round2"\n')
        rules = reportgen.load_rules(rules_path)
        digest = cache.file_digest(os.path.join(self.inp, "a.csv"))
        os.makedirs(os.path.dirname(self.cache_path))
        stale = {"a.csv": {
            "digest": digest, "rows": 99, "generated_from": 99,
            "rules_fp": cache.rules_fingerprint(rules),
            "registry_version": "1",
            "summary": {"columns": {"x": {"non_empty": 0, "distinct": 0,
                                          "sample": []}},
                        "skipped_rows": []}}}
        with open(self.cache_path, "w", encoding="utf-8") as fh:
            json.dump(stale, fh)

        self.assertEqual(self.run_main(rules_path), 0)

        report = _read_json(os.path.join(self.out, "report.json"))
        self.assertEqual(report["files"]["a.csv"]["rows"], 1)
        self.assertEqual(
            report["files"]["a.csv"]["summary"]["columns"]["x"]["numeric_sum"],
            3.0)


class RulesReadTests(_TempDirTest):
    def test_rules_file_is_read_once_per_run(self):
        self.write_input("a.csv", "x\n1\n")
        self.write_input("b.csv", "x\n2\n")
        rules_path = self.write_rules('[transforms]\nx = "round2"\n')
        real_open = builtins.open
        reads = {"n": 0}
        target = os.path.abspath(rules_path)

        def counting_open(path, *args, **kwargs):
            if os.path.abspath(str(path)) == target:
                reads["n"] += 1
            return real_open(path, *args, **kwargs)

        builtins.open = counting_open
        try:
            self.assertEqual(self.run_main(rules_path), 0)
        finally:
            builtins.open = real_open
        self.assertEqual(reads["n"], 1)


class FailurePolicyTests(_TempDirTest):
    def _seed_previous_outputs(self):
        os.makedirs(self.out)
        with open(os.path.join(self.out, "report.json"), "w") as fh:
            fh.write("PREVIOUS JSON")
        with open(os.path.join(self.out, "report.html"), "w") as fh:
            fh.write("PREVIOUS HTML")
        os.makedirs(os.path.dirname(self.cache_path))
        with open(self.cache_path, "w") as fh:
            fh.write('{"other.csv": {"digest": "old"}}')
        return (_read_bytes(os.path.join(self.out, "report.json")),
                _read_bytes(os.path.join(self.out, "report.html")),
                _read_bytes(self.cache_path))

    def _assert_untouched(self, before):
        self.assertEqual(
            _read_bytes(os.path.join(self.out, "report.json")), before[0])
        self.assertEqual(
            _read_bytes(os.path.join(self.out, "report.html")), before[1])
        self.assertEqual(_read_bytes(self.cache_path), before[2])

    def test_bad_cell_exits_one_after_a_good_file(self):
        self.write_input("a.csv", "amount\n$5.00\n")
        self.write_input("b.csv", "amount\nn/a\n")
        rules_path = self.write_rules(
            '[transforms]\namount = "currency_amount"\n')
        before = self._seed_previous_outputs()

        self.assertEqual(self.run_main(rules_path), 1)
        self._assert_untouched(before)

    def test_transform_crash_exits_one_and_emits_nothing(self):
        self.write_input("a.csv", "x\nvalue\n")
        rules_path = self.write_rules('[transforms]\nx = "trim"\n')
        before = self._seed_previous_outputs()
        original = transforms.REGISTRY["trim"]

        def explode(value):
            raise RuntimeError("unexpected transform crash")

        transforms.REGISTRY["trim"] = explode
        try:
            self.assertEqual(self.run_main(rules_path), 1)
        finally:
            transforms.REGISTRY["trim"] = original
        self._assert_untouched(before)


class ReportStabilityTests(_TempDirTest):
    def test_generated_from_is_stable_across_runs(self):
        self.write_input("a.csv", "id,status,d1\n1,,x\n")
        rules_path = self.write_rules(
            '[transforms]\nid = "trim"\nstatus = "upper"\n')
        self.assertEqual(self.run_main(rules_path), 0)
        first = _read_bytes(os.path.join(self.out, "report.json"))
        self.assertEqual(self.run_main(rules_path), 0)
        second = _read_bytes(os.path.join(self.out, "report.json"))
        self.assertEqual(first, second)


class HtmlEscapingTests(_TempDirTest):
    def test_column_names_are_escaped(self):
        self.write_input("a.csv", "x,<b>col\n1,red <i> & bold\n")
        rules_path = self.write_rules('[transforms]\nx = "trim"\n')
        self.assertEqual(self.run_main(rules_path), 0)
        with open(os.path.join(self.out, "report.html"),
                  encoding="utf-8") as fh:
            html_text = fh.read()
        self.assertNotIn("<b>", html_text)
        self.assertNotIn("<i>", html_text)
        self.assertIn("&lt;b&gt;col", html_text)
        self.assertIn("red &lt;i&gt; &amp; bold", html_text)


if __name__ == "__main__":
    unittest.main()
