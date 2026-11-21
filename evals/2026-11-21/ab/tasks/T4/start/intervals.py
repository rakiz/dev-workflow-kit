"""Interval helpers. Intervals are closed (start, end) pairs of integers."""


def merge(intervals):
    """Merge overlapping and adjacent intervals. Input may be unsorted; output is sorted."""
    out = []
    for start, end in sorted(intervals):
        if out and start < out[-1][1]:
            out[-1] = (out[-1][0], max(out[-1][1], end))
        else:
            out.append((start, end))
    return out
