## Defects in HEAD (`0bd5659`, new `incremental.py`)

**Major — `filter_excluded` uses a mutable default argument** (`incremental.py:9`)
`excluded=[]` is shared across every call. Each invocation appends to the same list, so a later call returns paths excluded by *previous* calls. E.g. `filter_excluded(["a.py"])` then `filter_excluded(["b.py"])` returns `["a.py", "b.py"]`. Cross-call state leak → wrong exclusion set (a caller could skip valid files).

**Major — `copy_many` silently reports partial/failed copies as done** (`incremental.py:17-26`)
It swallows every exception (`except Exception: continue`) and returns only the destinations it believes succeeded. Worse, it delegates to `synccli.copy_file`, which opens the destination `wb` *before* reading the source and swallows `OSError`: a mid-read failure leaves a truncated/corrupted destination, yet `copy_many` still appends that `dst` to `done`. Net effect: undetected data corruption plus silent loss of failed transfers (no error, no count).

**Minor — `merge_manifest` compares only `mtime`, not `size`** (`incremental.py:37`)
`old[rel]["mtime"] <= state["mtime"]` contradicts the documented mtime+size change detection (`changed_files` uses full-dict equality). A size change with an equal/older mtime (clock skew, timestamp granularity) is discarded. Also raises `KeyError` if any entry lacks an `"mtime"` key.

**Minor — `merge_manifest` API contract mismatch** (`incremental.py:30-38`)
Named/documented as merging "into the destination manifest," but it never writes `dst_manifest_path`; it only returns a dict. A caller expecting persistence silently gets nothing written.

**Minor — exclusion matches only the first path component** (`incremental.py:9-12`)
`p.split(os.sep)[0] in EXCLUDE_TOP_DIRS` misses nested `.git/…`/`__pycache__/…` and depends on `os.sep`, so absolute or foreign-separator paths bypass filtering.
