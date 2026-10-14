Fixed: `collect_stale` skipped the first item (`range(1, ...)` should include index 0).

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

Final test results: `Ran 6 tests ... OK` — all pass.