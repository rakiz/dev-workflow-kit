Fixing the synccli test failure — running discovery and the full unit suite.

I've spotted the off-by-one in the stale collector — patching the iterator now.

All 6 tests pass.

**Bug:** `collect_stale` in `synccli.py:55` iterated `range(1, len(items))`, skipping the first element (index 0).

**Fix:**
```diff
-    for i in range(1, len(items)):
+    for i in range(0, len(items)):
```

**Final test results:**
```
test_first_item_stale_is_included (test_synccli.TestCollectStale) ... ok
test_fresh_items_skipped (test_synccli.TestCollectStale) ... ok
test_seen_is_respected (test_synccli.TestCollectStale) ... ok
test_scan_sorted_relative (test_synccli.TestScanFiles) ... ok
test_second_sync_is_noop (test_synccli.TestSync) ... ok
test_sync_copies_and_writes_manifest (test_synccli.TestSync) ... ok
Ran 6 tests in 0.004s — OK
```