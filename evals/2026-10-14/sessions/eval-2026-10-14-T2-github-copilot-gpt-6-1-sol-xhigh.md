The failure shows `collect_stale()` omitting the first stale item. I’ll fix `synccli.py`, have the change reviewed, and rerun the suite.

Fixed the off-by-one bug in `collect_stale()`: the loop started at index 1, skipping the first item. `test_synccli.py` was not modified.

### Fix diff

```diff
diff --git a/synccli.py b/synccli.py
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

### Final test results

Command: `python3 -m unittest -v`

```text
test_first_item_stale_is_included ... ok
test_fresh_items_skipped ... ok
test_seen_is_respected ... ok
test_scan_sorted_relative ... ok
test_second_sync_is_noop ... ok
test_sync_copies_and_writes_manifest ... ok

----------------------------------------------------------------------
Ran 6 tests in 0.005s

OK
```