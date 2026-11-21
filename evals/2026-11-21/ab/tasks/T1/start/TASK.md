# Task T1 — wordtop: minimum length and JSON output

Extend `wordtop.py` (Python 3.10 stdlib only; no network; no new dependencies).

Definition of done:
1. `--min-length K` (default 0) drops normalized words shorter than K characters.
2. `--json` prints exactly one JSON object `{"top":[{"word":W,"count":C},...],"total_words":N}`.
   `top` honours `--top`. `total_words` counts the words that remain after the `--min-length` filter.
3. Ordering, in both text and JSON output: count descending, then word ascending.
4. `--min-length 0` behaves exactly like the default. An invalid K (not an integer, or negative)
   exits with status 2 and writes a one-line message to stderr.
5. Existing flags and the text output format are otherwise unchanged.

`test_wordtop.py` must stay green. Keep the change minimal.
