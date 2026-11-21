# Task T2 — csvsort: remove a duplicated block

`csvsort.py` holds two sorting functions, `sort_rows(rows, key, reverse=False)` and
`sort_rows_stable(rows, key)`, that share a copy-pasted block of about forty lines.
Python 3.10 stdlib only; no new dependencies.

Definition of done:
1. One shared helper holds the sorting block; both functions delegate to it.
2. The two signatures stay exactly as they are now.
3. CLI stdout is byte-identical on `data/a.csv`, `data/b.csv`, `data/c.csv` for the same arguments;
   exit codes and the error text stay the same.
4. The duplicated block appears once in the file.
5. `test_csvsort.py` stays green.
