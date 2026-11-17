Created `DESIGN-d1.md` in the repository root as requested.

It includes:
- Atomic publication, locking, crash recovery, and safe retention.
- Explicit handling of missing or unreadable source files.
- File-level change detection and its limitations.
- Grounded references to `synccli.py` and `snaputil.py`.
- Explicit memory, runtime, and disk bounds.
- A measured 1 GiB/30,000-file benchmark of **16.040 s**, supporting a **65-second budget**.

Verification: all **6 existing tests pass**. No existing source files were modified.
