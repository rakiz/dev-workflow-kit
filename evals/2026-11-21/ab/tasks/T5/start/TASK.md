# Task T5 — prune: keep the newest N notes, with a dry run, and a design document

`prune.py` lists `notes/`. Python 3.10 stdlib only; no new dependencies. Remain buildable as a CLI:
`python3 prune.py [--keep N] [--dry-run] [DIR]` (DIR defaults to `notes/` next to the script).

Definition of done:
1. Write `DESIGN-prune.md` (at most one page) with four headed sections, named exactly:
   `Policy`, `Ordering`, `Dry-run`, `Failure end state`.
2. `--keep N` keeps the newest N files **by modification time**; ties in mtime are resolved by name
   ascending. The rest are deleted, oldest first.
3. `--dry-run` prints the would-delete list and touches nothing: no unlink, and no file's mtime or contents change.
4. An unreadable file is skipped and the run continues. The run exits 1 with a one-line summary on stderr.
   Deletions already made stay made.
5. Deletions are whole-file unlinks. A crash mid-run leaves a deleted prefix; state this in `DESIGN-prune.md`.
6. `test_prune.py` stays green.
