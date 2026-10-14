

Bug: `collect_stale` skipped `items[0]` (synccli.py:55). Fixed via cheap-mech, reviewed clean by cheap-review; test_synccli.py untouched.

**Diff:**
```diff
--- a/synccli.py
+++ b/synccli.py
@@ -52,7 +52,7 @@ def collect_stale(items, seen=None):
     if seen is None:
         seen = set()
     stale = []
-    for i in range(1, len(items)):
+    for i in range(len(items)):
         path, fresh = items[i]
```

**Tests:** `Ran 6 tests ... OK` (all pass).