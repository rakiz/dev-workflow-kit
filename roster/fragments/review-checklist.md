Group the report under three visible axes; each axis ends with an explicit `reviewed` / `not reviewed` statement (so absence of findings never hides an unreviewed axis):

**Contract coverage** — is the task actually covered (not just the nominal path)?

- Do the new tests each map to a use case or acceptance criterion (from the contract brief's acceptance criteria), and assert the actual behavior? A test that would pass even if the behavior regressed — vacuous assertion, tautology, coverage-warming — is a finding, as is a test that exists for its own sake.

**Correctness / compatibility / security**:
- Does the change break existing callers or hidden consumers?
- Correctness under stress: edge cases, failure and rollback paths.
- For a bug fix: red/green evidence in the report — a regression test that failed before and passes after (or a documented exception stating why the bug could not be reproduced at a reasonable boundary); silent absence = **major** finding.
- Safety rules (`workflow.rules`, e.g. `RULES.md`) respected, any violation explicitly marked (`RULE-DEVIATION`) with a reasonable reason — unflagged or unjustified violation = **major** finding.
- Vulnerability classes the touched code can actually hit — examples, not exhaustive, language-specific (check the relevant classes — state which were reviewed, not reviewed, or not applicable): memory (use-after-free, double free, out-of-bounds, integer overflow, uninitialized read), injection (SQL, command, format string, path traversal — untrusted data reaching an interpreter), trust boundaries (external data — file, network, argument, env — validated before use), concurrency (data race, TOCTOU, missing lock), secrets & crypto (hardcoded or logged secret, homegrown crypto, non-constant-time comparison on a secret), resource leaks (fd, memory, handle, unbounded loop or allocation). These per-class states sit inside the axis; the axis still closes with its own `reviewed` / `not reviewed` line.

**Conventions / scope**:
- Are the project's conventions respected (style, structure, .md companions if enabled)?
- Anything added beyond the task? (unrequested abstraction, unneeded dependency, dead code) — `unneeded` means not justified by the task (a reuse per the skill's ladder is not a finding)
