The failure comes from `collect_stale` starting at index 1, which skips the first item. I’ll fix the loop and leave `test_synccli.py` untouched.

Fixed `collect_stale` in `synccli.py`: the loop skipped the first item by starting at index 1. It now iterates over every item. `test_synccli.py` was not modified.

### Diff

```diff
diff --git a/synccli.py b/synccli.py
index ae41a1e..f5a8c75 100644
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

### Final test results

```text
$ python3 -m unittest -v
test_first_item_stale_is_included (test_synccli.TestCollectStale) ... ok
test_fresh_items_skipped (test_synccli.TestCollectStale) ... ok
test_seen_is_respected (test_synccli.TestCollectStale) ... ok
test_scan_sorted_relative (test_synccli.TestScanFiles) ... ok
test_second_sync_is_noop (test_synccli.TestSync) ... ok
test_sync_copies_and_writes_manifest (test_synccli.TestSync) ... ok

----------------------------------------------------------------------
Ran 6 tests in 0.005s

OK
```