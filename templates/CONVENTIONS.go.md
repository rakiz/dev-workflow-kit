# Go conventions (optional template)

<!-- OPTIONAL, opt-in template — NOT installed by init.sh (same status as
     CONVENTIONS.python.md / CONVENTIONS.cpp.md): a language-specific reference
     (Go) distilled from the Uber Go Style Guide
     (https://github.com/uber-go/guide/blob/master/style.md), meant for a
     service/CLI project that wants them. A project that wants it copies this
     file itself, then either (a) references it from its own CONVENTIONS.md's
     "Project rules" section with a one-line pointer, or (b) appends its content
     directly into that section. Its MUST/SHOULD/MAY keywords are used as in
     RFC 2119. CONVENTIONS.md's two default rules (comments describe intent, not
     code; comments describe the current state, not its history) always apply
     underneath everything here. -->

## 1. Comments

Prefer self-explanatory code; a comment never replaces clean code, and the
CONVENTIONS.md defaults (intent over restatement, no history narration) apply
as written.

- **Doc comments are the public contract.** Every exported identifier carries a
  doc comment beginning with its name ("`Store` re-ingests a task directory…"),
  stating behavior, guarantees per failure mode, and the external contract it
  implements (by path + section). `godoc`/pkgsite renders it — it is
  documentation, not narration.
- **Explain the unusual** — a non-obvious decision gets a rationale comment:
  why the code is correct, why this approach over an alternative, what posture
  the failure mode follows. Bad: `// parse the document`. Good: `// Fail
  closed: a shape violation rejects the WHOLE document — no partial delivery.`
- **Cite the contract** — when the code implements an external specification,
  the comment names it by path and section (e.g. `docs/design.md §2.2`), so the
  next reader can diff code against the contract's own text.
- Formatting: doc comments and standalone comments are complete sentences,
  wrapped at 100 columns. Trailing comments must fit on the line and may skip
  capitalization.
- **TODO comments** — for temporary, short-term or knowingly imperfect code;
  MUST include the ticket/TODO.md reference and a description:
  `// TODO PROJ-122: drop the v2 advisory once dep v0.9 is the floor.`

## 2. Naming

- **Package names**: lowercase, single-word when possible, no underscores or
  camelCase (`store`, `ingest`, `logv2` — never `mongoStore` or
  `evergreen_ingest`). The package name is what callers type every day; the
  type name does not repeat it (`store.Store` is acceptable Go idiom, but
  prefer a concrete noun: `store.Ledger`, `ingest.Task`).
- Identifiers are `MixedCaps` (Go never uses snake_case for names): exported
  `PascalCase`, unexported `camelCase`. Abbreviations keep their usual case:
  `ID`, `URL`, `HTTP`, `ServerHTTP` → `HTTPServer` style rules apply
  (`ServeHTTP`, `userID`).
- **Avoid built-in names**: never `len`, `cap`, `new`, `max`, `min`, `type`,
  `range` as identifiers.
- Interfaces with one method are named the verb + `er` (`Reader`, `Ledgerer`);
  the implementation name is a concrete noun, never `ReaderImpl` by default —
  name it after what it *is* (`fileLedger`, `duckStore`).
- Error values: exported `ErrXxx`, unexported `errXxx`; custom error types end
  in `Error` (`ParseError`).
- Getters take no `Get` prefix (`s.Hosts()`, not `s.GetHosts()`); setters use
  `SetXxx`.

## 3. Package layout and structure

- One package, one responsibility. A service/CLI project uses: `cmd/<binary>`
  for `main` packages (thin — flags, wiring, exit codes), everything else in
  `internal/` (the surface layer must not import what it must not: parsers
  under `internal/logv2`, the store under `internal/store`, digests under
  `internal/digest`, tools under `internal/tools`), reusable public surface in
  root or `pkg/` only when an external module genuinely imports it.
- The import graph runs ONE direction along the data flow (e.g. fetch → parse
  → store → digest → tools). A parser MUST NOT import the store package; a
  digest MUST NOT import the fetcher. A back-edge couples format-specific code
  to the query layer — split the shared type into a leaf package instead.
- `main` owns: flag parsing, logging setup, context creation, `os.Exit`. A
  library package never calls `os.Exit`, never reads global flags.
- The test file for `internal/store/ledger.go` is `internal/store/ledger_test.go`
  (same directory, same package or `_test` package).

## 4. Interfaces

- **Accept interfaces, return concrete types.** A function that only reads a
  ledger takes a small interface it defines; the constructor returns the
  concrete `*fileLedger`.
- Define interfaces where they are CONSUMED (consumer side), not where they
  are implemented — an interface in the producer's package inverts the
  dependency and forces the consumer to import it.
- Never declare a pointer to an interface; declare the value.
- **Verify interface compliance at compile time** where it matters:
  `var _ Ledger = (*fileLedger)(nil)`.
- Interfaces stay small (one to three methods); a big interface is a smell —
  split it by consumer need.
- Do not export interfaces "for flexibility" before there is a second
  implementation; a concrete type is easier to change later than a published
  interface contract.

## 5. Structs, embedding, and zero values

- **A type's zero value must be usable** where practical (zero-value mutexes
  are valid; a struct needing a constructor documents `NewXxx` in its doc
  comment and panics-by-doc on illegal zero use).
- **Do not embed types in public structs** — embedding leaks the embedded
  type's methods and fields into the API (including `Mutex`! embed it only in
  unexported structs, and keep it near the fields it protects); use a named
  field for composition you want to be visible.
- Use field tags on any struct that is marshaled (`json:"host_name"` — the tag
  is part of the wire contract, never left default).
- Prefer struct literals with field names; positional literals only for
  2–3-field structs local to the line. Use `&T{Field: v}` at construction;
  `var t T` + assignment only when fields are set conditionally.
- Never use `any`/empty struct fields to smuggle options — use functional
  options (§9).

## 6. Errors — the failure posture

Every failure mode belongs to one of three postures, and the package doc
comment says which:

1. **fail-closed** — parsing third-party input where corruption poisons the
   store: a wrong type or a missing required field rejects the WHOLE input;
   no partial delivery.
2. **silent-skip** — a failed external interaction (network, absent binary,
   one malformed record among millions) degrades to "no contribution",
   recorded in the ledger/log, never surfaced as a crash. Every carve-out from
   silence is deliberate and reasoned in a comment.
3. **default-on-typo** — malformed configuration (a broken env var) uses the
   default silently: a config typo is a zero-change case — never an error,
   never "zero output".

- **Do not panic.** `panic` is for programmer errors only (impossible states,
  broken invariants caught in tests); every anticipated failure is an `error`
  returned to the caller. A parser MUST NOT panic on malformed input — return
  the error; the caller's posture decides skip vs abort.
- **Handle type assertion failures**: `v, ok := x.(T)`; the unchecked form is
  only for cases proven impossible by construction (and says so in a comment).
- Error declarations follow the Uber decision table: caller must match? static
  → exported `var ErrXxx = errors.New(...)`; dynamic → custom error type. No
  matching needed: `errors.New` (static) or `fmt.Errorf` (dynamic).
- **Wrap with context, once per layer**: `fmt.Errorf("new store: %w", err)` —
  use `%w` when callers should match the cause, `%v` to obfuscate. Drop the
  "failed to" prefix pileup: `new store: connection refused`, not
  `failed to create new store: failed to connect: ...`.
- `err != nil` is handled or returned, never discarded (`_ = doX()` is an
  errcheck violation) — a deliberate ignore carries a comment saying why the
  error cannot matter.

## 7. Concurrency and goroutine lifecycle

- **No fire-and-forget goroutines**: every `go func()` has a defined owner
  that waits for it (`sync.WaitGroup`, errgroup, or a done channel) and a
  shutdown path. A goroutine whose lifetime outlives the request leaks.
- Pass `context.Context` as the first argument on anything blocking or
  long-running; goroutines select on `ctx.Done()`. A child goroutine MUST
  respect the parent's cancellation.
- Channels are unbuffered or size one; a larger buffer needs a comment proving
  the bound.
- `defer` for cleanup (unlock, close) — including on error paths; never defer
  in a long-lived loop without checking accumulation.
- **Avoid mutable package-level state.** Globals are read-only after init; a
  package-level `var` that callers mutate is a data race waiting for a test
  run to find it. Shared mutable state lives behind a type with a mutex.
- Use `sync/atomic` (or `go.uber.org/atomic` types) for primitive counters
  accessed across goroutines — never a bare read/write.
- A binary that exits cleanly cancels its root context and waits: stray
  goroutines writing files after exit corrupt the store.

## 8. Time

- **`time.Time` for instants, `time.Duration` for durations — never ints.**
  Store and compare instants as UTC (`t.UTC()`); a `time.Time` read from
  external input is normalized to UTC once, at the boundary (parse time), not
  at every use site.
- Never compare times with `==` (monotonic clock readings); use `t.Equal`,
  `t.Before`, `t.After`.
- Parse and format with explicit constants (`time.RFC3339`) — never a layout
  string guessed at the call site; a repeated layout is a named constant.
- Durations in configs/maps are `time.Duration`, not raw ints with an implied
  unit — `500 * time.Millisecond`, never `500` "which is ms".

## 9. Dependency injection and options

- Testable seams are injected as interfaces or function types, defaulting to
  the real implementation at the wiring site (`cmd/`), not deep in the
  library: `func NewIngestor(f Fetcher, s Store) *Ingestor`.
- Options that only tune behavior use the **functional options pattern**
  (`WithLimit(n) Option`) once a constructor grows past ~3 parameters;
  required parameters stay positional.
- **Avoid `init()`**: it runs before tests can set up fakes, has error
  handling only via panic, and hides ordering dependencies. Registration that
  init() would do happens in an explicit `Register` call from `main` or a
  test.
- `os.Exit` only in `main` (or a test helper asserting exit behavior); a
  library calls a function that returns an error.

## 10. Performance gotchas

- `strconv` over `fmt` for hot-path conversions (`strconv.Itoa`, not
  `fmt.Sprintf("%d")`).
- Avoid repeated `string` ↔ `[]byte` conversions in loops — each is a copy.
  At a trust boundary one explicit conversion with validation beats five
  implicit ones.
- Preallocate containers when the size is known: `make([]Event, 0, n)`,
  `make(map[string]Metric, n)` — growth reallocation of million-row slices is
  the classic ingest slowdown.
- Prefer streaming readers (`bufio.Scanner` with a reset buffer bound,
  `json.Decoder`) over loading a multi-GB log into memory; a parser's memory
  ceiling is a documented guarantee.
- Measure before optimizing; a benchmark lives next to the hot path
  (`BenchmarkIngestLine`) and regressing it is a review finding.

## 11. Tests

- Red/green (MUST): a behavior change or bugfix lands with its failing test
  written FIRST, then made to pass.
- **Table-driven tests** (`tests := []struct{ name string; ... }` with
  `t.Run(tc.name, ...)`) for flag/enum/typing semantics — one test function
  per rule, not one test per case.
- Stub the external world: a fake `Fetcher` injected via constructor, a
  `httptest.Server` for HTTP, a temp dir for the store — never a real
  Evergreen, never the network.
- Cross-repo formats are pinned byte-exact: a **golden-fixture** test decodes
  the contract's own example file and asserts the exact result
  (`testdata/*.golden`, updated only with `go test -update`-style intent).
- A test MUST NOT derive both sides of an expectation from the same source —
  pin the expected string, or derive the expectation independently.
- A behavior change that obsoletes a pin REWRITES the pin (comment included)
  to the new rule — never deletes it silently.
- **A diagnostic surface and its user documentation are pinned TWO-WAY**: every
  error/warning the CLI can emit appears in the docs table (cause + remedy),
  and every documented one exists in the code — one test enforces both.
- Use `t.Parallel()` on independent tables; skip it where a shared temp dir or
  global would race. Slow tests get `testing.Short()` guards the day they
  appear.

## 12. Formatting and tooling

- `gofumpt` is the formatter (stricter than gofmt); run it on touched files
  before commit. Never a full-repo reformat inside an unrelated commit — a
  repo-wide format is its own dedicated commit.
- **`golangci-lint run` gates the commit**, with at least: `govet`,
  `staticcheck`, `errcheck`, `gocritic`, `revive`, `gofumpt`, `ineffassign`,
  `unused`, `misspell`, `bodyclose`, `rowserrcheck`, `noctx`,
  `unconvert`, `unparam`, `gosec` (audited severity). Sample `.golangci.yml`:

  ```yaml
  version: "2"
  linters:
    enable:
      - staticcheck
      - errcheck
      - gocritic
      - revive
      - ineffassign
      - unused
      - misspell
      - bodyclose
      - noctx
      - unconvert
      - unparam
      - gosec
  formatters:
    - gofumpt
  issues:
    exclude-dirs: [testdata, internal/pb]  # generated code
  ```

- Suppressions are line-targeted and reasoned: `//nolint:gosec // flags are
  test-only` — never a blanket exclude that hides real findings.
- Generated code (protoc, mockgen) is committed with its `DO NOT EDIT` marker,
  excluded from lint, and regenerated only by the pinned toolchain (a
  `go generate` directive naming the tool), never by hand.

## 13. Version compatibility

- Read every optional field as optional: an absent repeated field is an empty
  slice — "feature not present", never an error. A producer WITHOUT a feature
  and a producer WITH it must both parse without crashing (JSON decoding into
  pointer/`json.RawMessage` fields where presence matters).
- **A foreign store's format is gated by an EXACT version pin.** When the tool
  reads a store/file produced by another tool, the reader checks the format
  version it was learned against: an exact match proceeds; a mismatch refuses
  with a reason naming the seen version, the learned one, the direction
  (older/newer) and the remedy (rebuild/re-index) — never a guess, never a
  silent misread. An ABSENT version marker is the documented legacy case:
  accepted explicitly, with the acceptance rule written next to the pin.
- A compatibility invariant lives as a comment on the constant it protects
  (schema/format version pins), stating who consumes it and what a bump
  commits the project to.
- **External dependencies are commit-pinned**: every `require` in `go.mod` is
  resolved to an exact version (`go mod tidy` + checked-in `go.sum`); a
  dependency whose output is parsed (a decoder, a parser) is additionally
  pinned to a verified commit hash in a comment at the import site. Published
  release tags are never rewritten.

## 14. Packaging and build

- **`go.mod` is the single packaging source**: module path, Go version,
  dependencies. Tool dependencies (linters, generators) are declared via `tool`
  directives (`go get -tool`) so `go tool` runs them at the pinned version —
  nothing is installed globally by hand.
- One module per repository unless binary and library genuinely version
  separately; internal packages are `internal/` and invisible to importers by
  construction.
- `go build ./...` and `go vet ./...` pass at every commit; the CLI binary is
  built with the version injected via `-ldflags "-X main.version=..."` — a
  binary that cannot say what it is cannot be debugged.
- CGO is opt-in, not default: a driver that needs cgo (e.g. go-duckdb) is a
  documented build decision with its build-tag contract written next to the
  import, and pure-Go fallbacks (or documented absence) for cross-compilation.
