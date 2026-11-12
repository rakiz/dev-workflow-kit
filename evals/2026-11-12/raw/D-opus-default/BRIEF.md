# BRIEF — design `backupctl` (fixture D1)

## Context

This repository's `evals/` workflow accumulates result directories that must
be backed up. Today nothing backs them up. You are designing `backupctl`,
a command-line backup tool for exactly this job.

This directory is your starting point. It already contains working code for
a neighboring problem: `synccli.py` synchronizes a source directory into a
destination using a manifest file (`.sync_manifest.json`), and
`test_synccli.py` is its test suite (run it with `python3 -m unittest`).
`backupctl` will live alongside this code and ship in the same repo.

## What `backupctl` must do

`backupctl` covers a configured set of directories (N directories — a
handful today, a few dozen over time) and produces snapshots:
point-in-time copies of those directories, kept under a backup root.

The evals workflow makes demands a naive "copy everything, every time" loop
does not meet:

- **The scheduler and a person both trigger runs, and the timings can
  collide.** Two runs may execute at the same time, and a restore —
  separate tooling that reads a snapshot and copies it back — may be
  reading a snapshot while a run is writing a new one. No combination of
  these may corrupt a snapshot or each other's work.
- **A reader never asks whether the run that produced a snapshot is
  finished.** Anything that reads a snapshot later — a restore, a human,
  the next run — must see a complete, self-consistent image: never a mix
  of "some files from this run, some from the previous one", and never a
  snapshot index that promises files the snapshot does not contain.
- **The process can die at any point.** Ctrl-C, laptop sleep, a killed
  process — a run may stop mid-flight. An interrupted run must leave
  nothing behind that a later reader could mistake for a complete
  snapshot, and the next run must make progress without manual cleanup.
- **A source file can disappear without warning.** It can vanish between
  listing and copying, or be unreadable when the copy reaches it. The
  design must say what a snapshot then contains and what the run reports —
  the same behavior whether the run was started by the scheduler or by a
  person.
- **The backup root only ever grows.** Snapshots accumulate; a retention
  policy the design defines decides which old ones are deleted. Deletion
  must never leave the user without a usable snapshot, and must be safe
  while something else may be reading the snapshot being deleted.
- **Most files do not change between one run and the next.** After the
  first full backup of a directory, later runs must recognize the files
  that have not changed since the last snapshot instead of copying them
  again. The design must state at what granularity "unchanged" is decided
  and what edits that granularity can miss.
- **The first full backup has a clock on it.** The design must state its
  performance budget for the initial full backup of a ~1 GB tree (on the
  order of tens of thousands of files) and show where the number comes
  from — a measurement or an explicit derivation, not a guess. The
  existing code and tests in this directory may be run to check claims.
- **Three directories today, a few dozen over time.** Say what grows with
  what (per-run work, memory, disk) and what stays flat.

## Grounding

`backupctl` must build on the code in this directory rather than
re-implement it: wherever your design touches scanning, manifests, change
detection, or copying, name the exact existing file and function it builds
on. Where your design must behave differently from what the existing code
does today, say so explicitly and give the reason. A design that could have
been written without reading `synccli.py` is not grounded in this codebase.

## Deliverable and working mode

- Write your design to `DESIGN-d1.md` at the top of this directory.
- Work alone: no subagents, no delegation. Every part of the design is
  yours.
