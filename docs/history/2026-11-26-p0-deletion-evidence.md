# P0 deletion evidence — 2026-11-26

Record of the verification performed before the P0 deletions (CHANGELOG 0.8.1).
Written after the fact; it states only what is known.

## Claim

Before deletion, the 17 deployed session-roster agents in
`~/.config/opencode/agent/<name>.md` had bodies identical to the kit's
`roster/global-agent/<name>.md`.

## Method

Body identity = SHA-256 of the file content after removing the injected lines:
`model:` lines, `variant:` lines, and `# Model family:` comment lines. This is the
same normalization `init.sh` applies (`_body_hash`, init.sh:657). Command shape:

    grep -vE '^(model|variant):|^# Model family:' FILE | shasum -a 256

The owner's run on 2026-11-26 reported 17/17 identical. The per-file hash output was
not recorded, so the 17-file claim cannot be re-audited from this note.

## Independent re-verification (reviewer)

A reviewer re-ran the same comparison on the 16 surviving roster agents after the
deletions: 16/16 identical (post-deletion, against the kit's roster). The 17th file
could not be re-checked (see next section).

## What is NOT verifiable

The 17th file, `strong-design-review-alternative2.md`, was deleted on both sides
(the deployed copy and the kit's tracked copy, which carried the stale
`grok-4.7` mapping). No copy was kept, so its body identity cannot be verified
post-hoc. The record of its identity is the owner's 17/17 claim above, and nothing
more.

The deleted rung is recoverable from git history: the kit's tracked copy is in the
commit before `a187dec` (`git show a187dec^:roster/global-agent/strong-design-review-alternative2.md`).
The deployed copy was never tracked and is not recoverable.
