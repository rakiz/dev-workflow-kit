# CONTRACT — intervals.merge

`merge(intervals)` takes closed integer intervals `(start, end)` and returns them merged:
overlapping intervals are merged, adjacent intervals are merged (an interval that starts where the
previous one ends belongs to the same block), input may be unsorted, output is sorted.
