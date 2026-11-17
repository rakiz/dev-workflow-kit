- **Major — `incremental.py:23-24` (`copy_many`)**: `copy_file()` suppresses `OSError`, so `copy_many()` appends `dst` to `done` even when the copy failed or produced a partial file. Callers receive a false success report and may update manifests or skip retries, leaving missing/corrupted destination data.

- **Minor — `incremental.py:10` (`filter_excluded`)**: The mutable default `excluded=[]` is shared across calls. Results from earlier calls leak into later calls, returning stale paths and accumulating duplicates when the argument is omitted.
