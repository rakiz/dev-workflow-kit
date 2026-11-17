Real defects in `incremental.py` (HEAD):

1. **Major — mutable default argument corrupts results across calls.** `filter_excluded(paths, excluded=[])` (incremental.py:10): the default list is created once at function definition, so every call appends into the *same* list. Calling `filter_excluded(a)` then `filter_excluded(b)` returns b's paths **plus a's paths again** — callers get a wrong exclusion set, and with a "return excluded paths" contract, that's silently corrupted sync state.

2. **Major — `copy_many` silently swallows all failures.** (incremental.py:21-27): `except Exception: continue` discards every error; the function returns only successes with no record of which pairs failed. A caller that trusts "the list of dst paths done" (docstring contract) can conclude the batch succeeded and, e.g., overwrite the manifest for files never copied → actual data loss / manifest-vs-disk divergence. It also catches `Exception` broadly (including bugs like `TypeError`), masking real defects.

3. **Minor — `merge_manifest` crashes on malformed/legacy manifest entries.** (incremental.py:39): `old[rel]["mtime"]` assumes every existing entry has an `"mtime"` key; an entry missing it (hand-edited, older schema, or corrupted JSON that still parses) raises `KeyError` and the merge dies mid-way, leaving the caller unable to update the manifest.

4. **Minor — `merge_manifest` never removes stale entries.** Files deleted from the source keep their old state in the merged manifest forever, so they'll never be re-synced and the manifest misrepresents what's actually on the destination. (If intentional, the docstring doesn't say so.)
