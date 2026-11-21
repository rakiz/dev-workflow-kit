# BRIEF — design `ingestctl` (fixture US2)

## Context
This directory contains a small, working content-addressed chunk store
(`chunkstore.py`, `test_chunkstore.py`) and a single-shot uploader built on
it (`uploader.py`). `ingestctl` is a new command-line tool that ships in this
repo and uploads large files to a remote object manifest. It reuses this
code; it does not re-implement what the code already covers.

## What `ingestctl` must do
- Upload a file of any size to a store directory plus a remote manifest of
  objects. Two uploads may run at the same time (same or different files),
  and a garbage-collection run may overlap either.
- A reader of the manifest must never see an object the store cannot serve
  in full. A crash at any point — SIGKILL, power loss — must leave nothing
  behind that a later reader would mistake for a complete object, and the
  next run must make progress without manual cleanup.
- The store only grows: state the store's growth as a function of what is
  uploaded, and define when a chunk may be deleted. Deletion must never
  break a live object, and must be safe while an upload is running.
- Resume: after an interruption, a re-run must not re-upload what is already
  durable. State the granularity at which "durable" is decided, and what an
  edit at that granularity can miss.
- A chunk upload can fail transiently (timeout after the server applied it).
  The run must never double-count, and its reporting must say what actually
  landed.
- State the performance budget for the first upload of a ~1 GB file and show
  where the number comes from (measurement on this machine, or an explicit
  derivation).
- State what grows with what — memory, store size, manifest size, per-run
  work — every claim as an explicit bound (a number, a formula over file
  size/chunk size/object count, or a measured constant). "Stays bounded"
  without the bound is not an answer.
- A chunk may be missing or corrupt when a resume or a read reaches it. Say
  how it is detected and what happens next.

## Grounding
Wherever your design touches chunking, addressing, storage, upload or
retry, name the exact existing file and function it builds on, and what that
function actually does. A reference counts only if the artefact exists and
behaves as you claim (cite file and function; line numbers when you have
them). Where you must behave differently from the shipped code, name the
exact function you override and the reason. A design that could have been
written without opening this code is not grounded in it.

## Deliverable and working mode
- Write the design to `DESIGN-us2.md` in this directory.
- Work alone: no subagents, no delegation. Every part of the design is yours.
