# Python conventions (optional template)

<!-- OPTIONAL, opt-in template — NOT installed by init.sh (same status as
     CONVENTIONS.cpp.md): a language-specific reference (Python) following a
     mature Python codebase's conventions, meant for a project that wants
     them. A project that wants it copies this file itself, then either
     (a) references it from its own CONVENTIONS.md's "Project rules" section
     with a one-line pointer, or (b) appends its content directly into that
     section. Its MUST/SHOULD/MAY keywords are used as in RFC 2119.
     CONVENTIONS.md's two default rules (comments describe intent, not code;
     comments describe the current state, not its history) always apply
     underneath everything here. -->

## 1. Comments

Prefer self-explanatory code; a comment never replaces clean code, and the
CONVENTIONS.md defaults (intent over restatement, no history narration)
apply as written.

- **Explain the unusual** — a non-obvious decision gets a rationale comment:
  why the code is correct, why this approach over an alternative, what
  posture the failure mode follows. Bad: `# parse the document`. Good:
  `# Fail closed: a shape violation rejects the WHOLE document — no partial
  delivery.`
- **Cite the contract** — when the code implements an external specification
  (a cross-repo contract, a wire format), the comment names it by path and
  section (e.g. `docs/WIRE_FORMAT.md §6`), so the next reader can
  diff code against the contract's own text.
- Formatting: comments are complete sentences (capital letter, final
  punctuation), wrapped at 100 columns, forming prose paragraphs separated
  by a blank `#` line. Names are quoted with backticks (`store.meta()`);
  constants and env vars appear verbatim in caps (`MAX_RETRIES`).
- Standalone-line comments use `#`; trailing comments must fit on the line
  without wrapping and may skip capitalization and punctuation.
- **TODO comments** — for temporary, short-term or knowingly imperfect code;
  MUST include the ticket/TODO.md reference and a description:
  `# TODO PROJ-122: drop the v2 advisory once dep v0.9 is the floor.`

## 2. Naming

- Names are descriptive, succinct, specific; obscure acronyms are avoided
  (well-known ones — `HTTP`, `SQL`, `URI` — are fine). Single letters are
  acceptable for tiny comprehension scopes (`k`, `v` in a comprehension).
- Modules and file names: snake_case (`mcp_server.py`, `ingest.py`) — the
  file name never mixes camelCase in.
- Classes: PascalCase nouns (`GraphStore`, `IncompatibleStoreError`).
- Functions, methods, variables: lower_snake. A test name is a full
  snake_case sentence stating the pinned behavior:
  `test_expired_cache_entries_render_the_stale_placeholder`.
- Constants: SCREAMING_SNAKE, declared at module top after the imports;
  module-private constants keep the underscore (`_ZERO_MATCH_LINE`).
- Module-private members (helpers a surface layer must not import): a
  leading `_` (`_kill_tree`, `_parse_field`) — MUST for anything that is
  not part of the module's contract.
- Type aliases for injectable callables: PascalCase (`Runner`, `Which`).
- Abbreviations count as one word in PascalCase: `HttpServer`, not
  `HTTPServer`.
- No type-in-name redundancy: `users: list[User]`, not `lst_users`.

## 3. Type hints

- Every function, method, dataclass field and module-level constant carries
  a hint (MUST). Every module starts with `from __future__ import annotations`.
- Modern syntax only: `str | None` unions, builtin generics (`list[str]`,
  `dict[str, str]`) — never `Optional`/`List`/`Dict`.
- Accept the widest sensible READ-ONLY type in signatures: `Mapping[str,
  str]` for env/meta-like parameters (never `dict` when the function only
  reads), `Sequence[str]` for read-only ordered input (never `list`);
  return the concrete built type (`list[str]`).
- Options that only tune behavior are keyword-only, after a bare `*`
  (`def query_lines(meta, symbols, *, env=None, which=shutil.which)`).
- At trust boundaries (parsing a third-party document), check types with
  `isinstance` and remember `True == 1`: an integer field MUST reject a
  bool explicitly (`isinstance(v, bool) or not isinstance(v, int)`).
- A value validated-and-ignored is a documented decision (`name`/`anchors`
  are type-checked then never consumed) — never silently dropped.

## 4. Docstrings

- Every module opens with a docstring stating its role, the design
  decisions, the failure posture of each failure mode, and the external
  contract it implements (by path + section). This is where the WHY lives —
  in prose, not scattered over the body.
- Public functions document *what* and the GUARANTEES: the return shape per
  failure mode ("returns `[]` whenever the feature is off"), whether it
  can raise ("never a raise — the zero-change guarantee"), argument
  semantics quoted by name, side effects.
- A docstring on a user-facing surface (MCP tool description, CLI help) is
  USER-FACING documentation: written for the caller, describing behavior,
  never the implementation.
- Test docstrings state the pinned behavior AND why the pin exists; a bare
  test name may carry it only when the name truly says it all.
- Present tense, prose, wrapped at 100 columns. History belongs to
  `CHANGELOG.md` (CONVENTIONS.md rule 2).

## 5. Data modelling

- Parsed documents and value objects are frozen dataclasses; fields are
  typed, optional fields default and sort last.
- Files written by the tool are written ATOMICALLY: a temp sibling (unique
  per writer — pid/uuid, never a collision-prone fixed name) + `os.replace`
  — a concurrent reader never sees a half-written file, and a failed write
  never destroys the previous good one. Appends to a shared ledger file
  follow the same rule (read-modify-replace, not blind append) — under the
  single-writer assumption, or with writers serialized by an external lock
  (lockfile / `fcntl`): `os.replace` makes readers safe, it does not
  serialize writers.
- A parser stores only the fields a renderer consumes — "unknown shapes
  never get here"; the raw third-party shape never leaks past the parser.
- Rendered strings live as module-level constants. A templated line keeps
  its template constant and formats at render time — greppable, never
  f-string-duplicated: `_TRUNCATION_LINE = "… +{n} more — search results"`
  → `_TRUNCATION_LINE.format(n=dropped)`.
- External enum vocabularies that may GROW stay plain `str` with the known
  values documented: an unknown value is tolerated and rendered verbatim
  (forward compatibility), not rejected by an `Enum` type. Fail-closed
  rejection is reserved for shape (types, required fields), not vocabulary.

## 6. Error handling — the failure posture

Every failure mode belongs to one of three postures, and the module
docstring says which:

1. **fail-closed** — parsing third-party input: a wrong type or a missing
   required field rejects the WHOLE input; no partial delivery.
2. **silent-skip** — a failed external interaction (subprocess, network,
   absent binary) degrades to "no contribution" (`[]` / `None`), never an
   error surfaced to the user. Every carve-out from silence (e.g. one
   advisory line on a version mismatch) is deliberate, reasoned in a
   comment, and renders exactly one line.
3. **default-on-typo** — malformed configuration (a broken env var) uses
   the default silently: a config typo is a zero-change case — never an
   error, never "zero output".

- `except Exception: return <sentinel>` is allowed ONLY at a documented
  entry-point boundary whose caller is a long-lived host that must not
  crash — with a comment naming the posture. Everywhere else, `except` is
  narrow and re-raises with `from`.
- A subprocess spawned from a stdio-protocol server MUST NOT inherit stdin
  (fd 0 is the JSON-RPC stream — `stdin=DEVNULL`); its stdout is capped
  (overflow = failure, never unbounded buffering); a timeout kills the
  whole process GROUP, not just the direct child.
- **Every subprocess call carries a timeout** — a hung child must never
  block the host (a protocol server, a CLI, a hook). Timeout/missing-binary
  failures map to the module's failure posture (a diagnostic, a sentinel,
  a silent skip), never a traceback. Terminal prompts are disabled
  centrally (`GIT_TERMINAL_PROMPT=0` for git callers) — a hung credential
  prompt is a hung run.
- **Silent to the protocol ≠ invisible to the operator.** The silent-skip
  posture keeps the PROTOCOL surface (stdout) clean; stderr/logging stays
  available and SHOULD carry a warning line (`exc_info=True`) on each skip,
  so a best-effort block that never fires is diagnosable. A best-effort
  channel that logs nothing turns its failures into hours of blind
  debugging — the skip must leave a trail somewhere that is not the
  protocol surface.
- Library code MUST NOT `print()`: libraries return strings/lists, the CLI
  layer prints, servers log to stderr through `logging` — stdout is a
  protocol surface. A swallowed exception inside a best-effort block logs
  at warning with `exc_info=True` (stderr; never pollute the protocol).
- **Logging is configured once, at the entry point.** Modules and libraries
  only call `logging.getLogger(__name__)`; handlers and levels are set up in
  the CLI/server entry point, never at import time and never inside a
  library.

## 7. Functions and structure

- Pure functions own the logic; surface layers (CLI, MCP) are thin
  adapters. The same behavior MUST NOT be forked into one surface — it
  lives once in a shared pure function both call.
- One module, one responsibility; the test file mirrors the module path
  (`src/pkg/foo.py` → `tests/test_foo.py`).
- **Entry-point validation names the cause and the per-cause remedy.** A
  command that takes a path/artifact validates it UP FRONT and refuses
  with a diagnostic that distinguishes the failure causes (missing, wrong
  kind, misconfigured) — each with ITS remedy (the fix to run, the config
  key to set, the argument to pass). One generic "invalid input" for five
  different causes pushes every caller to re-derive the diagnosis.
- **Destructive operations are plan-then-confirm.** A command that deletes,
  resets or rewrites prints the full plan (WHAT will be discarded, listed)
  and exits with a dedicated code; an explicit flag (`--yes`) executes.
  The plan path is the default; the destructive flag is never implied;
  nothing else in the codebase may call it automatically.
- Testable seams are dependency injection by keyword parameter, defaulting
  to the real implementation: `runner: Runner = run_remote_checks`,
  `which: Which = shutil.which` — a test injects a recording fake, the
  production call site passes nothing.
- Lambdas only as short inline arguments (`key=`, `sort=`); anything with a
  branch or more than a couple of lines is a named function.
- **Async code never blocks the loop**: a coroutine does no blocking I/O or
  CPU-bound work inline (`asyncio.to_thread`/an executor for those); a call
  path is sync or async end to end, not a mix.

## 8. Imports

- Order: `from __future__ import annotations`, stdlib, third-party,
  first-party — blank line between groups.
- Long import lists: one name per line. An aliased import carries a
  trailing comment saying why:
  `from pkg.queries import label as _node_label  # aliased: main() has a local label`.
- No wildcard imports. Type-only cycles import under `TYPE_CHECKING`.

## 9. Tests

- Red/green (MUST): a behavior change or bugfix lands with its failing test
  written FIRST, then made to pass.
- Table-driven `parametrize` matrices for flag/enum/typing semantics
  (unset/`0`/`false`/`1`/`true`; every wrong-type variant) — one test
  function per rule, not one test per case.
- Stub the external world: a stub executable on PATH driven by env vars, or
  an injected runner — never a real install, never the network, never a
  live third-party tool.
- Cross-repo formats are pinned byte-exact: a worked-example test renders
  the contract's own example and asserts the exact string.
- A test MUST NOT derive both sides of an expectation from the same source
  — two values derived together can be wrong together. Pin the expected
  string, or derive the expectation independently.
- A behavior change that obsoletes a pin REWRITES the pin (docstring
  included) to the new rule — never deletes it silently.
- **A diagnostic surface and its user documentation are pinned TWO-WAY.**
  Every error/warning code the code can emit MUST appear in the
  documentation table (cause + remedy), and every documented code MUST
  exist in the code — one test enforces both directions, so the
  troubleshooting table cannot diverge from the behavior.
- Slow or flaky tests are tagged the moment they appear, not put off.

## 10. Formatting and tooling

- `ruff format` + `ruff check --fix` before commit, on the touched files
  ONLY. Never a full-repo reformat inside an unrelated commit — a
  repo-wide format is its own dedicated commit.
- Line length 100.
- **A type checker runs with the linter**: `mypy --strict` (or `pyright` —
  project decision) on the touched files, failing the check like any lint
  error — hints without a checker are documentation that rots.
- Generated code (e.g. protoc bindings) is committed with its
  `DO NOT EDIT` marker, excluded from lint, and regenerated only by the
  pinned toolchain (in a container), never by hand — so nobody needs the
  generator installed to run the project.

## 11. Version compatibility

- Read every optional field as optional: an absent `repeated` field is an
  empty list — "feature not present", never an error. A producer WITHOUT a
  feature and a producer WITH it must both parse without crashing.
- **A foreign store's format is gated by an EXACT version pin.** When the
  tool reads a store/file produced by another tool (a database, a cache, a
  rendered artifact), the reader checks the format version it was learned
  against: an exact match proceeds; a mismatch refuses with a reason naming
  the seen version, the learned one, the direction (older/newer) and the
  remedy (rebuild/re-index) — never a guess, never a silent misread. An
  ABSENT version marker is the documented legacy case: accepted explicitly,
  with the acceptance rule written next to the pin. The producer bumps the
  version IN THE SAME CHANGE as any format change — bumping is the
  governance rule, and the reader's refusal is what makes a forgotten bump
  visible instead of a corruption.
- A compatibility invariant lives as a comment on the constant it protects
  (the schema/format version pins), stating who consumes it and what a
  bump commits the project to.
- Published release tags are never rewritten — a fix ships as a new patch
  release.

## 12. Packaging and environment

- **`pyproject.toml` is the single packaging source** (PEP 621): metadata,
  dependencies, entry points; no `setup.py`/`setup.cfg` leftovers. The
  package version lives in one place, read by the build and by the code.
- **Dependencies are pinned and isolated**: a lock file (uv / pip-tools /
  Poetry — project decision) pins the resolved environment; dev dependencies
  form a separate group; nothing is ever installed into the system
  interpreter.
