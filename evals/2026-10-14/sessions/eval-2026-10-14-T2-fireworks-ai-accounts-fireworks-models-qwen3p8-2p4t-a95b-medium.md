

The bug is an off-by-one in `collect_stale`: the loop starts at index 1, skipping the first item.





Bug: `collect_stale` (synccli.py:55) iterated `range(1, len(items))`, skipping the first item. Fixed to iterate all items directly.

**Diff:**
```diff
-    for i in range(1, len(items)):
-        path, fresh = items[i]
+    for path, fresh in items:
```

**Tests:** `Ran 6 tests — OK` (all pass).