Your design critique is next — first hunting down DESIGN.md.

Located your sync engine plan — now I'll tear apart its assumptions before you write any code.

**Critique: `DESIGN.md:1-31` — Do Not Build As Written**

**Verdict: STOP** — the loop cannot meet its own 500 ms target at stated scale, and it silently diverges `dst` from `src`.

**1. Major risks (will cause data loss / divergence)**
- **Failed copies marked synced:** `synccli.py:83-86` writes `src_manifest` after copy, but `synccli.py:62-69` swallows `OSError` → a failed copy is recorded as fresh, never retried. Design inherits this via "reuse `sync()` directly" (`DESIGN.md:31`).
- **Non-atomic manifest:** `synccli.py:74` does `open(path,"w")` (truncate-then-write). Kill/crash mid-write → corrupt/empty JSON → crash loop or 50k-file re-copy storm. Daemon makes this the common case, not the edge case.
- **No deletion semantics:** `synccli.py:36-42` only yields added/changed; deletes never propagate, `dst` accumulates orphans. `GOAL.md` requirement "keeps dst continuously in sync" is undefined.
- **Head-of-line blocking:** single-thread `DESIGN.md:19` — one large file stalls all detection/copies.

**2. Wrong assumptions**
- `DESIGN.md:15` "mtime always changes on edit" — false: 1s granularity, same-size edits, tools that preserve mtime (`rsync`/`tar`/editors) → silent missed changes. mtime+size is a fast-path, not correctness.
- `DESIGN.md:14` "file is small / no atomicity needed" — at 50k entries `indent=2` it's ~5-15 MB rewritten 2×/s.
- `DESIGN.md:27` "SQLite little gain" — incremental state *is* the gain at this scale (no full rewrite, crash-safe transactions).
- `DESIGN.md:21` hardcode 500 ms — guarantees pegged CPU/disk on slow/network FS, with no adaptive backoff.

**3. What breaks under real load (50k files, few changes/min)**
- `os.walk` + `stat` × 50k + `sorted` + multi-MB `json.dump` per cycle >> 500 ms. Real period = scan+serialize; daemon pegs a core with steady write churn.
- Initial sync (sequential copy) blocks polling for minutes/hours; edits during it batch up.
- Any crash during manifest write → corrupt state; any failed copy → permanent divergence with no retry.

**4. Decisions to change first (prioritized)**
1. **Fix accounting:** only mark synced on successful copy; per-file error channel + retry. Don't reuse `sync()` as-is (frozen signature per `GOAL.md`).
2. **Atomic writes everywhere:** temp file + `os.replace` for both `dst` files and manifest.
3. **Decide delete/rename semantics now** — changes data model.
4. **Replace full-JSON-rewrite state** with incremental manifest or SQLite.
5. **Decouple scan from copy** (scanner loop + bounded worker queue, adaptive sleep).
6. **Content hash as tie-breaker** (periodic verify pass).
7. **Reconsider FSEvents** as primary trigger, polling as fallback — avoids the 500 ms busy-loop entirely.
