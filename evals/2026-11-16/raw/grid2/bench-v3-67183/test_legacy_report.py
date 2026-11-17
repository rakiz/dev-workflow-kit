"""HTML output checks for the report rendering."""

import os
import shutil
import tempfile
import unittest

import reportgen


class HtmlOutputTest(unittest.TestCase):
    def test_sample_values_do_not_leak_markup(self):
        tmp = tempfile.mkdtemp(prefix="rg3-html-")
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        inp = os.path.join(tmp, "in")
        os.makedirs(inp)
        with open(os.path.join(inp, "labels.csv"), "w") as fh:
            fh.write("item,label\ni1,red <b> & bold\n")
        rules_path = os.path.join(tmp, "rules.toml")
        with open(rules_path, "w") as fh:
            fh.write('[transforms]\nitem = "trim"\n')
        out = os.path.join(tmp, "out")
        reportgen.run(rules_path, inp, out, os.path.join(tmp, "cache", "state.json"))
        with open(os.path.join(out, "report.html")) as fh:
            html = fh.read()
        self.assertNotIn("<b>", html)
        self.assertIn("red &lt;b&gt; &amp; bold", html)


if __name__ == "__main__":
    unittest.main()
