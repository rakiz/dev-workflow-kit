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
    """GOAL item 1: the `boolean` transform."""

    def test_affirmative_forms_report_one(self):
        for raw in ("yes", "YES", "Yes", "true", "TRUE", "True"):
            self.assertEqual(transforms.apply("boolean", raw), 1.0)

    def test_negative_forms_report_zero(self):
        for raw in ("no", "NO", "No", "false", "FALSE", "False"):
            self.assertEqual(transforms.apply("boolean", raw), 0.0)

    def test_any_other_input_raises(self):
        for raw in ("maybe", "", "1", "0", "y", "n", "yes no"):
            with self.assertRaises(transforms.TransformError):
                transforms.apply("boolean", raw)

    def test_boolean_end_to_end(self):
        tmp = tempfile.mkdtemp(prefix="rg3-bool-")
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        inp = os.path.join(tmp, "in")
        os.makedirs(inp)
        with open(os.path.join(inp, "flags.csv"), "w") as fh:
            fh.write("id,flag\n1,Yes\n2,no\n3,TRUE\n4,False\n")
        rules_path = os.path.join(tmp, "rules.toml")
        with open(rules_path, "w") as fh:
            fh.write('[transforms]\nflag = "boolean"\n')
        report = reportgen.run(
            rules_path, inp, os.path.join(tmp, "out"),
            os.path.join(tmp, "cache", "state.json"))
        cols = report["files"]["flags.csv"]["summary"]["columns"]
        self.assertEqual(cols["flag"]["distinct"], 2)
        self.assertEqual(cols["flag"]["numeric_sum"], 1.0)  # over distinct
        self.assertEqual(cols["flag"]["sample"], [0.0, 1.0])


class FutureSchemaCacheTests(unittest.TestCase):
    """GOAL item 2: a state file from a future schema version must not
    crash the run; the cache is treated as empty and rewritten valid."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="rg3-future-")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.out = os.path.join(self.tmp, "out")
        self.cache_path = os.path.join(self.tmp, "cache", "state.json")
        os.makedirs(os.path.dirname(self.cache_path))

    def run_tool(self):
        return reportgen.run(RULES, INPUT_DIR, self.out, self.cache_path)

    def test_future_top_level_version_treated_as_empty(self):
        with open(self.cache_path, "w") as fh:
            json.dump({"version": int(cache.REGISTRY_VERSION) + 96,
                       "files": {"small_transactions.csv": {"rows": 999}}}, fh)
        report = self.run_tool()  # must not crash
        self.assertEqual(report["total_rows"], 12012)  # full run happened
        state = cache.load_state(self.cache_path)
        self.assertNotIn("version", state)
        self.assertEqual(set(state), {
            "big_transactions.csv", "small_devices.csv",
            "small_employees.csv", "small_transactions.csv"})
        for entry in state.values():
            self.assertEqual(entry["registry_version"], cache.REGISTRY_VERSION)

    def test_future_entry_registry_version_treated_as_empty(self):
        digest = cache.file_digest(
            os.path.join(INPUT_DIR, "small_transactions.csv"))
        rules_fp = cache.rules_fingerprint(reportgen.load_rules(RULES))
        with open(self.cache_path, "w") as fh:
            json.dump({"small_transactions.csv": {
                "digest": digest, "rows": 999, "generated_from": 999,
                "rules_fp": rules_fp,
                "registry_version": str(int(cache.REGISTRY_VERSION) + 1),
                "summary": {"columns": {}, "skipped_rows": []}}}, fh)
        report = self.run_tool()  # must not crash
        self.assertEqual(report["files"]["small_transactions.csv"]["rows"], 4)
        state = cache.load_state(self.cache_path)
        self.assertEqual(state["small_transactions.csv"]["registry_version"],
                         cache.REGISTRY_VERSION)
        self.assertEqual(state["small_transactions.csv"]["rows"], 4)


class RegistryVersionLookupTests(unittest.TestCase):
    """Regression: transforms.py promises the registry version stamped on
    an entry is compared at lookup, but run() never compared it, so an
    entry from an older registry was reused."""

    def test_old_registry_entry_not_reused(self):
        tmp = tempfile.mkdtemp(prefix="rg3-ver-")
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        out = os.path.join(tmp, "out")
        cache_path = os.path.join(tmp, "cache", "state.json")
        reportgen.run(RULES, INPUT_DIR, out, cache_path)
        state = cache.load_state(cache_path)
        entry = state["small_transactions.csv"]
        entry["registry_version"] = "1"
        entry["rows"] = 999
        with open(cache_path, "w") as fh:
            json.dump(state, fh)
        report = reportgen.run(RULES, INPUT_DIR, out, cache_path)
        self.assertEqual(report["files"]["small_transactions.csv"]["rows"], 4)
        state = cache.load_state(cache_path)
        self.assertEqual(state["small_transactions.csv"]["registry_version"],
                         cache.REGISTRY_VERSION)


class FailurePolicyTests(unittest.TestCase):
    """Regression: a transform failure used to overwrite report.html and
    poison the cache before validation ran, and the CLI still exited 0.
    Policy: exit 1, emit nothing new, previous artifacts byte-for-byte
    intact — for caught failures and unhandled crashes alike."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="rg3-fail-")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.inp = os.path.join(self.tmp, "in")
        os.makedirs(self.inp)
        self.out = os.path.join(self.tmp, "out")
        self.cache_path = os.path.join(self.tmp, "cache", "state.json")
        self.rules_path = os.path.join(self.tmp, "rules.toml")
        with open(os.path.join(self.inp, "nums.csv"), "w") as fh:
            fh.write("n\n1\n2\n")
        self.write_rules("round2")
        self.argv = ["--rules", self.rules_path, "--input", self.inp,
                     "--output", self.out, "--cache", self.cache_path]
        self.assertEqual(reportgen.main(self.argv), 0)
        self.before = self.artifact_bytes()

    def write_rules(self, transform):
        with open(self.rules_path, "w") as fh:
            fh.write('[transforms]\nn = "%s"\n' % transform)

    def artifact_bytes(self):
        blobs = {}
        for p in (os.path.join(self.out, "report.json"),
                  os.path.join(self.out, "report.html"),
                  self.cache_path):
            with open(p, "rb") as fh:
                blobs[p] = fh.read()
        return blobs

    def test_caught_transform_failure_exits_1_and_emits_nothing(self):
        with open(os.path.join(self.inp, "nums.csv"), "w") as fh:
            fh.write("n\n1\noops\n")  # round2 catches-and-carries this
        self.assertEqual(reportgen.main(self.argv), 1)
        self.assertEqual(self.artifact_bytes(), self.before)
        self.assertEqual(sorted(os.listdir(self.out)),
                         ["report.html", "report.json"])

    def test_unhandled_transform_crash_exits_1_and_emits_nothing(self):
        def boom(value):
            raise RuntimeError("transform crashed")
        transforms.REGISTRY["boom"] = boom
        self.addCleanup(transforms.REGISTRY.pop, "boom", None)
        self.write_rules("boom")
        with self.assertRaises(RuntimeError):  # propagates: CLI exits 1
            reportgen.main(self.argv)
        self.assertEqual(self.artifact_bytes(), self.before)


class RulesReadOnceTests(unittest.TestCase):
    """Regression: load_rules used to run once per input file; the rules
    file must be read at most once per run."""

    def test_rules_file_read_at_most_once_per_run(self):
        tmp = tempfile.mkdtemp(prefix="rg3-reads-")
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        calls = []
        orig = reportgen.load_rules

        def counting(path):
            calls.append(path)
            return orig(path)

        reportgen.load_rules = counting
        self.addCleanup(setattr, reportgen, "load_rules", orig)
        reportgen.run(RULES, INPUT_DIR, os.path.join(tmp, "out"),
                      os.path.join(tmp, "cache", "state.json"))
        self.assertEqual(calls, [RULES])  # 4 input CSVs, exactly 1 read


class CacheHitReportStabilityTests(unittest.TestCase):
    """Regression: generated_from was computed with one definition on a
    fresh pass (reportgen.generated_from) and another on a cache hit
    (cache.make_entry), so report.json differed between consecutive runs
    over identical inputs."""

    def test_report_json_identical_on_cached_rerun(self):
        tmp = tempfile.mkdtemp(prefix="rg3-stable-")
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        out = os.path.join(tmp, "out")
        cache_path = os.path.join(tmp, "cache", "state.json")
        report = reportgen.run(RULES, INPUT_DIR, out, cache_path)
        with open(os.path.join(out, "report.json"), "rb") as fh:
            first = fh.read()
        reportgen.run(RULES, INPUT_DIR, out, cache_path)  # full cache hit
        with open(os.path.join(out, "report.json"), "rb") as fh:
            second = fh.read()
        self.assertEqual(first, second)
        # small_devices.csv has an all-empty rules-mapped column (status):
        # the value that used to diverge between the two paths.
        self.assertEqual(
            report["files"]["small_devices.csv"]["generated_from"], 1)


class HtmlEscapeTests(unittest.TestCase):
    """Regression (complements test_legacy_report, which covers sample
    values): file names and column names were interpolated unescaped."""

    def test_file_and_column_names_are_escaped(self):
        tmp = tempfile.mkdtemp(prefix="rg3-esc-")
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        inp = os.path.join(tmp, "in")
        os.makedirs(inp)
        with open(os.path.join(inp, "da<ta>.csv"), "w") as fh:
            fh.write("ti<tle>,v\nx & y,1\n")
        out = os.path.join(tmp, "out")
        reportgen.run(RULES, inp, out,
                      os.path.join(tmp, "cache", "state.json"))
        with open(os.path.join(out, "report.html")) as fh:
            html = fh.read()
        self.assertNotIn("da<ta>", html)
        self.assertNotIn("ti<tle>", html)
        self.assertIn("da&lt;ta&gt;.csv", html)
        self.assertIn("ti&lt;tle&gt;", html)
        self.assertIn("x &amp; y", html)


if __name__ == "__main__":
    unittest.main()
