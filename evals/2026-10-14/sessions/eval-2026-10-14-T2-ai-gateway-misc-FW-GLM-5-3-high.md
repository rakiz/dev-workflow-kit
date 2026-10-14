The bug is in `collect_stale` (synccli.py:55): `range(1, len(items))` skips the first item.

Fixed. `collect_stale` iterated from index 1, dropping the first item; now it iterates all items directly.

**Diff:**
```diff
-    for i in range(1, len(items)):
-        path, fresh = items[i]
+    for path, fresh in items:
```

**Tests:** Ran 6 tests in 0.005s — **OK** (all pass).