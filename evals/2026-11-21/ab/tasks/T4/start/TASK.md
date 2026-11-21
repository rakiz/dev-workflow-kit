# Task T4 — intervals: write the missing test, then fix the defect it exposes

`intervals.py` documents that `merge` merges overlapping **and adjacent** intervals (see `CONTRACT.md`).
The shipped code has a defect the current tests do not catch. Python 3.10 stdlib only.

Definition of done:
1. Extend `test_intervals.py` (the file is yours to extend) so that it **fails** on the shipped
   `intervals.py` for the defect, and **passes** once the defect is fixed.
2. Fix `intervals.py` (the fix may be a one-line change). The suite must pass on your tree.
3. The suite must still be a test of the contract, not a copy of the implementation.

The reviewer will run `test_intervals.py` on your tree (it must pass) and with a different
`intervals.py` injected (it must fail).
