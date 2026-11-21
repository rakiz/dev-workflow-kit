# Repro

`python3 -m unittest test_durutil` must go green. Three tests are red on the shipped code:

- `test_repro_minutes`: `90m` returns `None` instead of 5400.
- `test_repro_hours_then_bare_minutes`: `1h30` returns `None` instead of 5400.
- `test_repro_trailing_junk_rejected`: `10sx` returns 10 instead of `None`.
