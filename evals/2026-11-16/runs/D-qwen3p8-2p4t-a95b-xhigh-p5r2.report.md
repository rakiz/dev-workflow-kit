`DESIGN-d1.md` written (868 lines), worked alone, existing code untouched (suite still green).

Key points:
- **Grounded**: every reuse cites exact file:line (`synccli.py` / `snaputil.py`); 12 named overrides (O1–O12), each backed by an executed verification — including real defects found: `safe_snapshot_path` leading-`..` escape, silently-skipped files never retried (`synccli.py:68-69` + `:85-86`), `prune_snapshots(keep=0)` deleting the newest.
- **Design**: flock single-writer + hidden staging + atomic whole-dir rename publish + immutable snapshots + hard-link dedup + rename-to-trash/claim-aware retention + discard-and-re-derive index recovery.
- **Budget measured, not guessed**: 1.024 GB / 20k-file full backup via the existing engine: 7.74–10.34 s → budget ≤ 30 s (≈3× worst), with the derivation formula and all constants (Appendix A).
