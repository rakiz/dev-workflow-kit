# C++ conventions — C++23 no-exceptions variant (optional template)

<!-- OPTIONAL, opt-in template — NOT installed by init.sh (same status as
     CONVENTIONS.cpp.md): a second, independent C++ reference.  Where
     CONVENTIONS.cpp.md follows a mature database-codebase style
     (exceptions, Status, ticket-allocated error codes, assertion
     machinery), THIS file distills a no-exceptions C++23 systems
     practice: std::expected-based errors, registered user-facing codes,
     versioned persisted formats, observable fallbacks, companion
     documentation files, hot-path discipline, determinism tests,
     spec-cited claims.  A project that wants it copies this file
     itself, then either (a) references it from its own
     CONVENTIONS.md's "Project rules" section with a one-line pointer,
     or (b) appends its content directly into that section.  Its
     MUST/SHOULD/MAY keywords are used as in RFC 2119.  CONVENTIONS.md's
     two default rules (comments describe intent, not code; comments
     describe the current state, not its history) always apply
     underneath everything here. -->

## 1. Language baseline

C++23. The compiler is trusted over bookkeeping:

- **No exceptions** — every fallible operation returns
  `std::expected<T, E>` (typically `E = std::string`).  No `throw`, no
  `try` outside third-party boundaries.
- **No raw `new`/`delete`** — `std::unique_ptr` / `std::make_unique`;
  containers own their data.
- **`std::span`** instead of pointer + size pairs.
- **Rule of zero** — no custom destructor/copy/move unless forced by
  real ownership (a class holding an open resource documents why).
- **`constexpr` over runtime computation** for tables and constants.
- Unsigned types are normal — hardware registers, bus addresses and
  counters ARE bit patterns; do not fight the domain.  Signed only
  where a value can legitimately go negative.
- **Compiled with `-fno-exceptions` and a warning floor**
  (`-Wall -Wextra -Werror` or the project's documented equivalent): the
  no-exception rule above is enforced by the build, not by goodwill.
- **Third-party exceptions stop at the boundary.**  A library that throws
  (`std::filesystem`, parsers, ...) gets exactly one integration-layer
  wrapper that catches, converts to `std::expected`, and documents which
  exceptions it covers; `catch` appears nowhere else in project code.

## 2. Error handling — two categories, never mixed

**Programmer errors** (broken invariant, impossible branch, wrong
caller) — assert, do not handle:

```cpp
default:
    assert(false && "lane_at() called with LANE_AUTO — caller must resolve first");
    std::unreachable();
```

`assert` fires in debug; `std::unreachable()` eliminates the branch in
release.  A silent fallback (returning a default value) MUST NOT mask a
programmer error.

**Runtime errors** (missing file, bad user input, failed I/O) — values,
not control flow:

```cpp
std::expected<T, std::string> read_file(const std::string& path);
```

**User-facing codes live in one registry.**  When the project emits
stable, human-consumed identifiers (diagnostics, export errors,
validation warnings, protocol message types), every code is registered
in a single table — value, canonical name, severity, doc — and
emitters reference entries by name, never by naked value.  Bind at
compile time: the emitted object carries a `const RegistryEntry&`
into that table, and the named aliases are constexpr-initialized from
a lookup that fails to compile if the entry disappears.  A typo'd or
orphaned code becomes a build error instead of a wrong number in a
bug report, and code, canonical name, doc and severity stay
single-sourced.  Internal-only errors do not pay this cost — a plain
enum and a formatter suffice.

**No silent returns on unimplemented paths.**  Any code path that
returns a fallback because a feature is not yet implemented MUST either:
- emit `LOG_WARN("module", "feature X not implemented — returning
  fallback")` behind a one-shot guard (avoid log spam), or
- emit `LOG_ERROR` and fail cleanly when the missing feature could
  corrupt state.

A bare `return 0` / `return false` with only a comment explaining the
gap is forbidden.  "Out of scope" is recorded in the project's tracker,
not disguised as a working return value.

**A fallback must be observable.**  Whatever degrades (missing
feature, failed load, bad input) must not be invisible in the artifact
the user actually sees: pair the log line required above with a
visible marker of degradation in the output itself — a placeholder, a
distinctive error state, a "broken" indicator.  The log covers the
machine side; the artifact covers the human who never reads logs.  A
fallback indistinguishable from success is a silent return by another
name.

## 3. Logging

```cpp
LOG_DEBUG("NET",   "conn={} rtt={}ms", id, rtt);
LOG_INFO ("FS",    "File saved: {}", path);
LOG_WARN ("AUDIO", "Device lost — default output in use");
LOG_ERROR("PARSE", "Unexpected token at line {}", line);
```

- Tag = component name, PascalCase or ALL_CAPS, consistent per component.
- `DEBUG` = per-event detail, never on by default; `INFO` = user-visible
  events; `WARN` = abnormal but recoverable; `ERROR` = fatal.
- No `printf` / `std::printf` / `std::cout` for runtime messages — ever.
- Log messages do not end in punctuation.

## 4. No magic values

Every constant with hardware or protocol semantics gets a named
identifier, ALL_CAPS:

```cpp
static constexpr uint8_t  BROADCAST_ID = 0xFF;   // all devices on the bus
static constexpr uint16_t DEFAULT_PORT = 0x0000; // well-known entry point
```

State-machine step values use named `constexpr` constants grouped by
family.  Field encodings in a wire format use `enum class` so
parameters are typed at the call site.  Naked literals (`return 0xFF`,
`if (port == 0xBC)`) are forbidden.

## 5. Architecture

- **struct** = plain data, all fields public, no invariants.  **class** =
  stateful behaviour with invariants.  **Free function** = only uses the
  public interface of a type (needs private access → method).
  **Namespace** = grouping only.
- **Inheritance only for runtime polymorphism** — the caller must not
  and cannot know the concrete type.  One level of virtual interface,
  composition otherwise; never inherit to reuse code.
- **Hot paths stay hot**: a per-tick function (called millions of times
  per second) MUST NOT be virtual; no `std::function` on hot paths;
  prefer `constexpr` tables over runtime branching.
- **Platform isolation**: `core/` carries ZERO `#ifdef` — platform
  differences live exclusively in `platform/`.
- **Shared mutable state has one owner.**  Data shared across threads is
  owned by one component and accessed through it (message passing, a
  command queue, or one documented lock); a bare mutex protecting
  "whatever" is a design smell.  No detached threads — every thread is
  owned and joined.
- **Concepts over SFINAE.**  Template constraints are written as
  `concept`s; `std::enable_if_t` acrobatics are legacy, not style.  A
  template instantiated with exactly one type wants to be a function.

## 6. Naming

- Classes / structs / enum types: CamelCase nouns.
- Functions and methods: **snake_case** — `build_render_config()`,
  `TaskRunner::advance_us()`.  Free functions live in a nested
  namespace rather than the project root.
- Constants: ALL_CAPS (`kDaysPerWeek`-style is not used).
- Enum-class values: CamelCase (`SortOrder::Descending`,
  `ResetKind::Hard`).
- Private data members: **trailing underscore** (`profile_`, `t_us_`);
  locals never carry one.
- Namespaces: entirely lowercase; a closing comment is optional (short
  files win over ceremony).
- Files: snake_case, `.hpp`/`.cpp` pairs.
- Test case names are human-readable sentences (may contain spaces and
  punctuation when the test framework supports it — a test name is
  documentation, not an identifier).
- Abbreviations count as one word; single letters only for iterators.

## 7. Companion documentation — the `.md` twin

Every `.cpp` and `.hpp` MUST have a sibling `.md` with the same base
name, containing: **Role** (responsibility, one line), **Relations**
(depends on / used by), **How it works** (high-level, no implementation
detail), and a **Mermaid diagram** of direct dependencies.  The companion
is updated with the change that invalidates it — it is part of the
deliverable, not optional.  Tool scripts (`.sh`/`.py`) carry no
companion: they are self-documenting in their header comment (purpose,
usage, exit codes, non-obvious behaviours).

A review round that skips the docs is incomplete: "review the code"
alone reliably misses documentation drift.

## 8. Comments

Prefer self-explanatory code.  Comments are complete sentences (capital
letter, final punctuation), wrapped at 100 columns, in prose paragraphs.
Variable and enum-case names are quoted with single quotes; function
names end with empty parentheses.

- **Cite the authority.**  A comment or message stating a spec /
  protocol / platform fact names its source: `// POSIX §2.1.4: ...` /
  `// ISO C++ [conv.ptr]: ...` / `// <vendored lib> file.c:307-309`.
  Verbatim quotes beat paraphrase for load-bearing rules.  "I don't
  know" is a valid comment; an uncited claim is not.
- **File comments** — a file with more than a trivial scope opens with a
  `//` prose header: what it is, what belongs (and does not belong)
  here.
- **Function comments** — describe *what* and *how to use* (argument
  names, pre/post-conditions, non-obvious side effects, whether a
  reference argument is retained); not *how* (that is the body's job).
  Overrides comment only what they add over the base.  Trivial
  accessors skip.
- **Literal constants at call sites** — prefer named constants or an
  `enum class`; inline `/* name */` comments as the fallback.
- **TODO comments** — anchored to the project's tracker, not a ticket
  system: `// TODO: <what> — tracked in TODO.md §<item> (<date>)`.

## 9. Layout

- No consecutive blank lines; a new scope does not open with a blank
  line.
- Lines wrap at 100 columns (SHOULD).
- `const` before the type: `const T&`, `const T*`.
- C-style casts are forbidden — `static_cast<T>(...)` and named casts
  only.
- Declaration order: `public`, `protected`, `private`; within a section:
  constants; nested types; constructors/factories; destructor; methods
  grouped by functionality; data members last.
- Parameters: inputs first, then in-out, then output — defaulted
  parameters last.
- Return values over output parameters.
- Includes: own header first in a `.cpp` (self-containment check), then
  project headers, then third-party, then the standard library.
  License headers are optional (project decision) — a file comment
  replaces them.
- A header is **self-sufficient** — it compiles on its own; include what
  you use, never lean on transitive includes.  `#pragma once` over include
  guards; a forward declaration beats an include when the full type is not
  needed.
- **Layout is `clang-format`'s job** — the project's `.clang-format`
  encodes the rules in this section (100 columns, `const` placement,
  declaration order); nobody formats by hand, and horizontal whitespace
  is never a review topic.

## 10. Testing

TDD, order non-negotiable: interface (`.hpp`) first, then failing tests,
then the minimum implementation that passes.  No component is done until
its tests pass.

- **Provenance first line** — a test encoding a documented behaviour
  cites it: `// <spec> §X.Y <component> <variant> (page N):` plus a
  short verbatim quote of the rule, and a cross-reference for
  non-obvious observables.
- **Known-blocked tests stay in the suite** tagged as expected-failure
  with the blocker named (e.g. doctest's `[!shouldfail]`; use the
  project framework's equivalent), plus the blocker class (harness
  limit, dependency-pending, …) — a tracker is better than a deleted
  test.
- **Real assertions over `FAIL()`** — even a `CHECK` against a guessed
  value beats a lazy `FAIL()`: it makes the divergence concrete and
  bisectable.  `FAIL()` only when no observable exists in any API
  surface, with the reason documented.
- **Rewriting a passing test is an admission of error** — requires the
  old CHECK vs new CHECK divergence, the justifying source, and the
  author's explicit validation, before the change.
- **Determinism is a test category.**  When one logical result is
  reachable through several paths (seek vs continuous, replay, re-run,
  editor vs export), tests assert the paths agree value-for-value:
  same input and state, same output, whatever path took it there.
  Path-equivalence is a product guarantee, not an implementation
  detail.
- **Sanitizers stay clean** — an ASan/UBSan suppression or leak-detection
  waiver is scoped to the narrowest unit (a single test binary via its
  runner properties), documented with the reason inline, and leak
  detection stays enabled everywhere else.

## 11. Persisted formats are versioned

Every serialized format (document, blob, config, preset, IPC payload)
has a named version constant — written into the payload at save,
validated at load.  An old file is either read correctly or rejected
with a message that names both versions ("written with format 1, this
build reads 2") — never silently mis-parsed.  A breaking change bumps
the constant; the constant is what makes "can this build still read
old files?" a decidable question instead of folklore.
