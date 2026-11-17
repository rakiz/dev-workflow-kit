Wrote `DESIGN-d1.md` at the repo root.

It covers atomic snapshot publication, per-source run locks plus per-snapshot reader leases, crash/corrupt-index recovery, vanished/unreadable-file semantics, hardlink-based incremental backups, retention safety, explicit scaling bounds, and a measured 1 GiB/20k-file performance budget. Grounding cites the reused and overridden `synccli.py`/`snaputil.py` functions with line numbers and verified defects.
