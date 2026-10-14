Fixed: `collect_stale` had an off-by-one (`range(1, len(items))`) that skipped the first item — now iterates all items (synccli.py:55).

**Diff:**
```diff
-    for i in range(1, len(items)):
-        path, fresh = items[i]
+    for path, fresh in items:
```

**Final tests:** `Ran 6 tests ... OK` (all pass).