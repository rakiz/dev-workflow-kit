`collect_stale` in `synccli.py` started its loop at index `1` (`range(1, len(items))`), skipping the first item. Changing it to `range(len(items))` fixes the bug.

### Diff

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

### Final Test Results

```text
test_first_item_stale_is_included (test_synccli.TestCollectStale) ... ok
test_fresh_items_skipped (test_synccli.TestCollectStale) ... ok
test_seen_is_respected (test_synccli.TestCollectStale) ... ok
test_scan_sorted_relative (test_synccli.TestScanFiles) ... ok
test_second_sync_is_noop (test_synccli.TestSync) ... ok
test_sync_copies_and_writes_manifest (test_synccli.TestSync) ... ok

----------------------------------------------------------------------
Ran 6 tests in 0.004s

OK
```