# Task T3 — durutil: fix duration parsing

`parse_duration(text)` returns the duration in seconds, or `None` for an invalid string.
Python 3.10 stdlib only. The three repro tests in `test_durutil.py` are red (see `REPRO.md`).

Grammar (fixed):
- An optional hours part `<n>h`, then an optional minutes part, then an optional seconds part `<n>s`,
  in that order. The minutes part is `<n>m`, or a bare `<n>` directly after an hours part (then minutes).
- Examples: `45s` → 45, `90m` → 5400, `1h30m` → 5400, `1h30` → 5400, `2h` → 7200, `0s` → 0.
- Surrounding whitespace is ignored.
- Anything else is invalid and returns `None`: empty text, a bare number with no unit (`30`),
  an unknown unit (`1x`), or trailing characters after a valid duration.

Definition of done: the whole grammar holds, the three repro tests are green, and no other behaviour changes.
Keep the change minimal.
