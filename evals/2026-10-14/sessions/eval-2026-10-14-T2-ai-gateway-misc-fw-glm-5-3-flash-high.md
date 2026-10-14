The bug is in `collect_stale` (synccli.py:55) — the loop starts at index 1, skipping the first item.

All 6 tests pass.

**Diff** — `collect_stale` started iterating at index 1, silently skipping the first item:

```diff
--- a/synccli.py
+++ b/synccli.py
@@ -52,8 +52,7 @@ def collect_stale(items, seen=None):
     if seen is None:
         seen = set()
     stale = []
-    for i in range(1, len(items)):
-        path, fresh = items[i]
+    for path, fresh in items:
         if path not in seen and not fresh:
             stale.append(path)
     return stale
```

**Test results:**
```
test_first_item_stale_is_included ... ok
test_fresh_items_skipped ... ok
test_seen_is_respected ... ok
test_scan_sorted_relative ... ok
test_second_sync_is_noop ... ok
test_sync_copies_and_writes_manifest ... ok

Ran 6 tests in 0.004s

OK
```