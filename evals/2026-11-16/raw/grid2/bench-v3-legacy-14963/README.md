# syncd

Daemon that keeps a destination directory continuously in sync with a source
directory, using a manifest (`.syncd_manifest.json`) and a journal
(`.syncd_journal.log`). See DESIGN.md for the design it implements.

- `python3 -m syncd SRC DST` to run.
