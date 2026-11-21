#!/usr/bin/env python3
"""Print the most frequent words of the given text files (or stdin)."""
import argparse
import re
import sys
from collections import Counter

PUNCT = re.compile(r"[^\w\s]")


def normalize(text):
    return PUNCT.sub("", text.casefold()).split()


def count_words(text):
    return Counter(normalize(text))


def read_inputs(paths):
    if not paths:
        return sys.stdin.read()
    parts = []
    for path in paths:
        with open(path, encoding="utf-8") as fh:
            parts.append(fh.read())
    return "\n".join(parts)


def main(argv=None):
    ap = argparse.ArgumentParser(description="Count the most frequent words.")
    ap.add_argument("--top", type=int, default=10, help="how many words to print")
    ap.add_argument("files", nargs="*")
    args = ap.parse_args(argv)
    counts = count_words(read_inputs(args.files))
    for word, n in counts.most_common(args.top):
        print(f"{n} {word}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
