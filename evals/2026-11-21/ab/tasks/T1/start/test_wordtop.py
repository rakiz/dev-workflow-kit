import os
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
CLI = os.path.join(HERE, "wordtop.py")


def run(args, stdin=""):
    return subprocess.run([sys.executable, CLI] + args, input=stdin, capture_output=True, text=True, cwd=HERE)


class Basics(unittest.TestCase):
    def test_counts_casefolded_words(self):
        r = run(["--top", "2"], stdin="The cat. the DOG, the cat!")
        self.assertEqual(r.stdout.split("\n")[:2], ["3 the", "2 cat"])

    def test_punctuation_is_stripped(self):
        r = run(["--top", "1"], stdin="hello, hello; hello!")
        self.assertEqual(r.stdout.strip(), "3 hello")

    def test_reads_files(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "a.txt")
            with open(p, "w") as fh:
                fh.write("x x y")
            r = run(["--top", "1", p])
            self.assertEqual(r.stdout.strip(), "2 x")

    def test_top_limits_output(self):
        r = run(["--top", "1"], stdin="a b c")
        self.assertEqual(len(r.stdout.strip().split("\n")), 1)


if __name__ == "__main__":
    unittest.main()
