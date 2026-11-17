Created [DESIGN-d1.md](DESIGN-d1.md), grounded in the existing functions and line references.

It covers atomic snapshots, concurrent runs and readers, crash/index recovery, source failures, incremental reuse, retention, and explicit performance/resource bounds.

Verification: all 6 existing tests pass. Worked alone, with no subagents or delegation.
