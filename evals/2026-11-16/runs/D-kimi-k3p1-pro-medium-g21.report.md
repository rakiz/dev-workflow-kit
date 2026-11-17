Created `DESIGN-d1.md` with the requested `backupctl` design, including:

- Atomic snapshot publication and crash recovery
- Scheduler/manual run locking and safe restore/pruning coordination
- Partial-backup behavior for disappearing or unreadable sources
- Hard-link reuse with explicit change-detection limitations
- Corrupt-index quarantine and payload-based manifest reconstruction
- Retention guarantees
- Grounded references to `synccli.py` and `snaputil.py`
- Explicit CPU, memory, and disk bounds
- A measured 60-second initial-backup budget based on an actual 1 GiB/30,000-file benchmark

Validation: all 6 existing unit tests passed. Temporary benchmark data was removed.
