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
    """Feature: `boolean` transform (GOAL item 1)."""

    def test_affirmative_forms_map_to_one(self):
        for v in ("yes", "YES", "Yes", "true", "TRUE", "True"):
            self.assertEqual(transforms.apply("boolean", v), 1.0)

    def test_negative_forms_map_to_zero(self):
        for v in ("no", "NO", "No", "false", "FALSE", "False"):
            self.assertEqual(transforms.apply("boolean", v), 0.0)

    def test_anything_else_raises_transform_error(self):
        for v in ("maybe", "1", "0", "y", "n", "", "yesno", "tru"):
            with self.assertRaises(transforms.TransformError):
                transforms.apply("boolean", v)

    def test_boolean_registered(self):
        self.assertIn("boolean", transforms.REGISTRY)

    def test_boolean_end_to_end(self):
        tmp = tempfile.mkdtemp(prefix="rg3-bool-")
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        inp = os.path.join(tmp, "in")
        os.makedirs(inp)
        with open(os.path.join(inp, "flags.csv"), "w") as fh:
            fh.write("item,flag\n1,yes\n2,NO\n3,True\n")
        rules_path = os.path.join(tmp, "rules.toml")
        with open(rules_path, "w") as fh:
            fh.write('[transforms]\nitem = "round2"\nflag = "boolean"\n')
        report = reportgen.run(rules_path, inp, os.path.join(tmp, "out"),
                               os.path.join(tmp, "cache", "state.json"))
        cols = report["files"]["flags.csv"]["summary"]["columns"]
        self.assertEqual(cols["flag"]["non_empty"], 3)
        self.assertEqual(cols["flag"]["distinct"], 2)
        # numeric_sum sums the distinct transformed values: {1.0, 0.0}
        self.assertEqual(cols["flag"]["numeric_sum"], 1.0)
        self.assertEqual(cols["item"]["numeric_sum"], 6.0)


class FutureCacheVersionTests(unittest.TestCase):
    """Feature: a cache/state.json from a future schema version must not
    crash the run — treat as empty, do the full run, rewrite valid state
    (GOAL item 2)."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="rg3-fut-")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.inp = os.path.join(self.tmp, "in")
        os.makedirs(self.inp)
        with open(os.path.join(self.inp, "t.csv"), "w") as fh:
            fh.write("item\n1\n2\n")
        self.rules = os.path.join(self.tmp, "rules.toml")
        with open(self.rules, "w") as fh:
            fh.write('[transforms]\nitem = "round2"\n')
        self.out = os.path.join(self.tmp, "out")
        self.cache_path = os.path.join(self.tmp, "cache", "state.json")

    def run_tool(self):
        return reportgen.run(self.rules, self.inp, self.out, self.cache_path)

    def bump_state(self, mutate):
        self.run_tool()
        with open(self.cache_path) as fh:
            state = json.load(fh)
        mutate(state)
        with open(self.cache_path, "w") as fh:
            json.dump(state, fh)

    def test_future_entry_version_treated_as_empty_and_rewritten(self):
        future = str(int(cache.REGISTRY_VERSION) + 1)

        def mutate(state):
            for entry in state.values():
                entry["registry_version"] = future
        self.bump_state(mutate)
        report = self.run_tool()  # must not crash; full run
        self.assertEqual(report["total_rows"], 2)
        self.assertEqual(report["files"]["t.csv"]["summary"]["columns"]
                         ["item"]["numeric_sum"], 3.0)
        state = cache.load_state(self.cache_path)
        self.assertEqual(set(state), {"t.csv"})
        self.assertEqual(state["t.csv"]["registry_version"],
                         cache.REGISTRY_VERSION)
        self.assertEqual(state["t.csv"]["digest"],
                         cache.file_digest(os.path.join(self.inp, "t.csv")))

    def test_future_top_level_version_wrapper_treated_as_empty(self):
        self.run_tool()
        with open(self.cache_path, "w") as fh:
            json.dump({"version": int(cache.REGISTRY_VERSION) + 5,
                       "files": {}}, fh)
        report = self.run_tool()  # must not crash; full run
        self.assertEqual(report["total_rows"], 2)
        with open(self.cache_path) as fh:
            state = json.load(fh)
        self.assertNotIn("version", state)
        self.assertEqual(set(state), {"t.csv"})
        self.assertEqual(state["t.csv"]["registry_version"],
                         cache.REGISTRY_VERSION)


class RulesReadOnceTests(unittest.TestCase):
    """Regression (invariant): the rules file must be read at most once
    per run — it used to be re-read once per input CSV."""

    def test_rules_file_read_exactly_once(self):
        tmp = tempfile.mkdtemp(prefix="rg3-reads-")
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        out = os.path.join(tmp, "out")
        cache_path = os.path.join(tmp, "cache", "state.json")
        target = os.path.abspath(RULES)
        real_open = builtins.open
        reads = []

        def counting_open(file, *args, **kwargs):
            try:
                if os.path.abspath(os.fspath(file)) == target:
                    reads.append(file)
            except TypeError:
                pass
            return real_open(file, *args, **kwargs)

        with mock.patch("builtins.open", counting_open):
            reportgen.run(RULES, INPUT_DIR, out, cache_path)
        self.assertEqual(len(reads), 1)


class GeneratedFromStabilityTests(unittest.TestCase):
    """Regression: a cached run used to report a different
    `generated_from` than the fresh run that produced the entry
    (cache.make_entry counted rules-mapped columns regardless of
    non-empty cells)."""

    def test_generated_from_same_on_fresh_and_cached_run(self):
        tmp = tempfile.mkdtemp(prefix="rg3-genfrom-")
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        inp = os.path.join(tmp, "in")
        os.makedirs(inp)
        # `status` is rules-mapped but entirely empty -> generated_from
        # must count only `item`.
        with open(os.path.join(inp, "t.csv"), "w") as fh:
            fh.write("item,status\n1,\n2,\n")
        rules_path = os.path.join(tmp, "rules.toml")
        with open(rules_path, "w") as fh:
            fh.write('[transforms]\nitem = "round2"\nstatus = "upper"\n')
        out = os.path.join(tmp, "out")
        cache_path = os.path.join(tmp, "cache", "state.json")
        fresh = reportgen.run(rules_path, inp, out, cache_path)
        cached = reportgen.run(rules_path, inp, out, cache_path)
        self.assertEqual(fresh["files"]["t.csv"]["generated_from"], 1)
        self.assertEqual(cached["files"]["t.csv"]["generated_from"],
                         fresh["files"]["t.csv"]["generated_from"])


class RegistryVersionLookupTests(unittest.TestCase):
    """Regression: cache entries stamped with a different registry
    version used to be reused even though the documented contract says
    the version is compared at lookup."""

    def test_old_registry_version_entry_not_reused(self):
        tmp = tempfile.mkdtemp(prefix="rg3-ver-")
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        inp = os.path.join(tmp, "in")
        os.makedirs(inp)
        with open(os.path.join(inp, "t.csv"), "w") as fh:
            fh.write("item\n1\n2\n")
        rules_path = os.path.join(tmp, "rules.toml")
        with open(rules_path, "w") as fh:
            fh.write('[transforms]\nitem = "round2"\n')
        out = os.path.join(tmp, "out")
        cache_path = os.path.join(tmp, "cache", "state.json")
        reportgen.run(rules_path, inp, out, cache_path)
        with open(cache_path) as fh:
            state = json.load(fh)
        state["t.csv"]["registry_version"] = "1"
        state["t.csv"]["summary"]["columns"]["item"]["distinct"] = 999
        with open(cache_path, "w") as fh:
            json.dump(state, fh)
        report = reportgen.run(rules_path, inp, out, cache_path)
        # stale-version entry must be recomputed, not reused
        self.assertEqual(report["files"]["t.csv"]["summary"]["columns"]
                         ["item"]["distinct"], 2)
        state = cache.load_state(cache_path)
        self.assertEqual(state["t.csv"]["registry_version"],
                         cache.REGISTRY_VERSION)


class FailurePolicyTests(unittest.TestCase):
    """Regression (invariant): if any transform fails, the run must exit
    1, emit nothing new, and leave the previously good report.json /
    report.html and the cache intact byte-for-byte. Previously the HTML
    was rewritten and the cache extended before validation, a crashing
    transform escaped as something other than a transform failure, and
    main() exited 0."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="rg3-fail-")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.inp = os.path.join(self.tmp, "in")
        os.makedirs(self.inp)
        with open(os.path.join(self.inp, "good.csv"), "w") as fh:
            fh.write("item\n1\n2\n")
        self.rules = os.path.join(self.tmp, "rules.toml")
        with open(self.rules, "w") as fh:
            fh.write('[transforms]\nitem = "round2"\n')
        self.out = os.path.join(self.tmp, "out")
        self.cache_path = os.path.join(self.tmp, "cache", "state.json")

    def snapshot(self):
        snap = {}
        for p in (os.path.join(self.out, "report.json"),
                  os.path.join(self.out, "report.html"),
                  self.cache_path):
            with open(p, "rb") as fh:
                snap[p] = fh.read()
        return snap

    def seed_good_run(self):
        reportgen.run(self.rules, self.inp, self.out, self.cache_path)
        return self.snapshot()

    def add_bad_input(self):
        with open(os.path.join(self.inp, "bad.csv"), "w") as fh:
            fh.write("item\nnope\n")

    def test_failure_leaves_previous_outputs_and_cache_intact(self):
        before = self.seed_good_run()
        self.add_bad_input()
        with self.assertRaises(reportgen.ValidationError):
            reportgen.run(self.rules, self.inp, self.out, self.cache_path)
        self.assertEqual(before, self.snapshot())

    def test_failure_does_not_cache_incomplete_pass(self):
        self.seed_good_run()
        self.add_bad_input()
        with self.assertRaises(reportgen.ValidationError):
            reportgen.run(self.rules, self.inp, self.out, self.cache_path)
        state = cache.load_state(self.cache_path)
        self.assertNotIn("bad.csv", state)

    def test_main_exits_1_on_transform_failure(self):
        self.add_bad_input()
        with self.assertRaises(SystemExit) as cm:
            reportgen.main(["--rules", self.rules, "--input", self.inp,
                            "--output", self.out, "--cache", self.cache_path])
        self.assertEqual(cm.exception.code, 1)
        self.assertFalse(os.path.exists(os.path.join(self.out, "report.json")))
        self.assertFalse(os.path.exists(os.path.join(self.out, "report.html")))
        self.assertFalse(os.path.exists(self.cache_path))

    def test_crashing_transform_is_a_transform_failure(self):
        before = self.seed_good_run()

        def boom(value):
            raise RuntimeError("transform crashed")

        transforms.REGISTRY["boom"] = boom
        self.addCleanup(transforms.REGISTRY.pop, "boom", None)
        with open(self.rules, "w") as fh:
            fh.write('[transforms]\nitem = "boom"\n')
        with self.assertRaises(reportgen.ValidationError):
            reportgen.run(self.rules, self.inp, self.out, self.cache_path)
        self.assertEqual(before, self.snapshot())

    def test_cached_entry_with_skipped_rows_is_recomputed_not_reused(self):
        # A cache poisoned by an older buggy run (entry carrying an
        # incomplete pass) must heal: recompute, don't brick or reuse.
        reportgen.run(self.rules, self.inp, self.out, self.cache_path)
        with open(self.cache_path) as fh:
            state = json.load(fh)
        state["good.csv"]["summary"]["skipped_rows"] = [
            {"row": 2, "column": "item", "reason": "stale"}]
        with open(self.cache_path, "w") as fh:
            json.dump(state, fh)
        report = reportgen.run(self.rules, self.inp, self.out, self.cache_path)
        self.assertEqual(report["files"]["good.csv"]["summary"]["skipped_rows"],
                         [])
        state = cache.load_state(self.cache_path)
        self.assertEqual(state["good.csv"]["summary"]["skipped_rows"], [])


if __name__ == "__main__":
    unittest.main()
