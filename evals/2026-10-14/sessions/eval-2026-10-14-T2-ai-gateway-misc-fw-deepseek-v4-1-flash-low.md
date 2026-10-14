The bug is in `collect_stale`: `range(1, len(items))` skips the first item.

Fixed. `collect_stale` was iterating from index 1, silently dropping the first item. Now all 6 tests pass.