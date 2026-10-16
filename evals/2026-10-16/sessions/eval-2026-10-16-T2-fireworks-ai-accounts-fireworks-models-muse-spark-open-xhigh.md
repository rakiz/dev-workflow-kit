Your failing test is next — running the suite to pin down the culprit.

Found the culprit — the first item is being skipped. I'll apply the fix next.

All tests pass after fix. Bug was off-by-one in `synccli.py:55` - loop started at `1`, skipping first item.

**Diff of fix:**

```diff
diff --git a/synccli.py b/synccli.py
index ae41a1e..a3760fe 100644
--- a/synccli.py
+++ b/synccli.py
@@ -52,7 +52,7 @@ def collect_stale(items, seen=None):
     if seen is None:
         seen = set()
     stale = []
-    for i in range(1, len(items)):
+    for i in range(len(items)):
         path, fresh = items[i]
         if path not in seen and not fresh:
             stale.append(path)
```

**Final test results (`python3 -m unittest -v`):**

```
test_first_item_stale_is_included (test_synccli.TestCollectStale) ... ok
test_fresh_items_skipped (test_synccli.TestCollectStale) ... ok
test_seen_is_respected (test_synccli.TestCollectStale) ... ok
test_scan_sorted_relative (test_synccli.TestScanFiles) ... ok
test_second_sync_is_noop (test_synccli.TestSync) ... ok
test_sync_copies_and_writes_manifest (test_synccli.TestSync) ... ok

----------------------------------------------------------------------
Ran 6 tests in 0.006s

OK
```