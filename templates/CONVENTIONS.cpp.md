# C++ conventions (optional template)

<!-- OPTIONAL, opt-in template — NOT installed by init.sh. Unlike CONVENTIONS.md
     (always copied) or RULES.md (opt-in via --with-rules/prompt but still
     script-supported), this file is never copied automatically by any
     mechanism: it is a language-specific reference (C++, and
     JS where noted) following a mature C++ codebase's conventions, meant for
     a project that wants them. A project that wants it copies this file
     itself, then either (a) references it from its own CONVENTIONS.md's
     "Project rules" section with a one-line pointer, or (b) appends its
     content directly into that section. Its MUST/SHOULD/MAY keywords are
     used as in RFC 2119. -->

## 1. Comments

Prefer self-explanatory code; a comment never replaces clean code.

- **No duplication** — if the code is clear, restating it adds nothing.
  Bad: `i = i + 1; // Add one to 'i'`.
- **No excuse for unclear code** — put the information in the code instead.
  Bad: `Node n; // best node candidate`; good: `Node bestNode;`.
- **Explain the unusual** — non-obvious or tricky code gets a rationale
  comment; if a reviewer had to ask, the answer belongs in the code.

Formatting: comments are complete sentences (capital letter, final
punctuation), wrapped at 100 columns, forming prose paragraphs separated by
a blank comment line. Variable and enum-case names are quoted with single
quotes; function names end with empty parentheses `()`.

- **File comments** — a file declaring several items opens with a comment
  describing the collection (after the license header, before the includes),
  e.g. `/** Declares plan-executor factory functions for query types. */`
- **Class/struct comments** — `/** */` style, describing what the class
  does, why it is needed and how to use it (entry points; a usage example
  only for tricky classes). With a `.h`/`.cpp` split, the comment lives in
  the header.
- **Function comments** — `/** */` style, describing *what* the function
  does, not *how* (that is the body's job). May be skipped for simple,
  obvious accessors. Mention: inputs/outputs (quoting argument names),
  pre/post-conditions, performance guarantees, non-obvious side effects,
  whether a pointer/reference argument is retained beyond the call,
  null-pointer behavior, and whether output/in-out arguments are appended
  to or overwritten.
  - *Virtual overrides*: comment only what the override adds over the base
    comment; nothing to add → no comment.
  - *Constructors/destructors*: skip trivial ones ("destroys this object"
    says nothing); document non-obvious construction/destruction work
    (e.g. why a copy constructor is deleted or defaulted).
  - *Function templates*: comment like a regular function, plus the
    template parameters' type requirements.
  - *Lambdas*: comment when the purpose is not obvious; simple
    callback-style lambdas may skip it.
- **Function argument comments** — literal constants are hard to read at
  call sites. Bad: `calculateProduct(values, 7, false, nullptr)`. In order
  of preference: named constants for each value; an enum replacing `bool`
  arguments (especially several of them); inline `/* name */` comments.
- **Variable comments** — member variables are commented only for what the
  type and name don't already say (special values, relationships, lifetime
  requirements). Global, static-member and namespace-scope variables MUST
  all have a comment: what they are, what for, and why they exist at that
  scope.
- **Inline/implementation comments** — explain tricky code: what it does
  (when non-obvious), why it is correct, why this approach over an
  alternative. Standalone-line comments use `//` style; trailing comments
  also use `//`, must fit on the line without wrapping, and may skip
  capitalization and punctuation.
- **TODO comments** — for temporary, short-term or knowingly imperfect
  code; MUST include the ticket ID and a description:
  `// TODO PROJ-12345: Remove this after the 2047q4 compatibility window expires.`

## 2. Naming

- Names are descriptive, succinct, specific; obscure acronyms are avoided
  (well-known ones — `HTTP`, `SQL`, `RAII` — are fine); single letters are
  acceptable for iterators and similar.
- Unused function parameters MAY omit their name.
- Classes: CamelCase nouns. Pure abstract classes are prefixed `I`
  (e.g. `ICostEstimator`).
- Constants: `k`-prefixed camelCase (`kDaysPerWeek`), not ALL_CAPS.
- Namespaces: entirely lowercase snake_case, closed with a comment:
  `}  // namespace myproject::sync`. Free functions live in a nested namespace
  rather than polluting `::myproject`.
- Anonymous namespaces: used for internal (translation-unit-local)
  linkage.
- Functions: camelCase starting lowercase (`myFreeFunction()`,
  `MyClass::myMemberFunction()`); private methods MAY begin with `_`.
- Unit tests MAY use underscores:
  `SuiteName_StateOrConditions_ExpectedBehavior`.
- Data members: camelCase; private members SHOULD begin with `_`
  (`_myPrivateMember`).
- Local variables: camelCase, never a leading underscore.
- Enums: named like classes; enum classes are preferred. Plain-enum values
  are named like constants (`kOne`, `kTwo`); enum-class values MAY be
  constants-style or lowerCamelCase (`optionOne`), never ALL_CAPS.
- Abbreviations count as one word in camelCase: `HttpInterface`, not
  `HTTPInterface`.
- File names: snake_case, for C++ and JS alike — even when naming camelCase
  query-language syntax.

## 3. Lambdas

Lambdas are hard to profile and debug (their post-compile names are
generic) and disrupt reading flow when large. A lambda:

- MUST NOT call other project functions (std/utility functions are fine);
- SHOULD NOT exceed ~20 lines;
- MUST NOT excessively allocate objects.

Anything else is extracted into a named function.

## 4. Whitespace

- No consecutive blank lines.
- A new scope (function body, `if` block, ...) MUST NOT begin with a blank
  line; a blank line MAY follow the opening of a namespace.
- Horizontal whitespace is clang-format's business, not a review topic.

## 5. Declaration order

Sections are ordered `public`, `protected`, `private`. Within each section,
the order MUST be: constants; typedefs/nested types; constructors,
factories and assignment operators; destructor; other methods grouped by
functionality; data members. Static methods MAY be grouped before the
constructors, and a type used by a single method MAY be declared next to
it. Out-of-line definitions in a `.cpp` may be in any order.

## 6. Parameter order

Input parameters first, then input-output, then output — the exception
being input parameters with default values. Convention: `RequestContext*`
(or `intrusive_ptr<ExpressionContext>`) comes first; when both are present,
`RequestContext*` precedes `ExpressionContext`.

## 7. Output parameters

Return values SHOULD be preferred over output parameters. When an output
parameter is used, it MAY be passed by non-const reference or non-const
pointer.

## 8. Error codes and log codes

A named code is used only when external code depends on it specifically
(stable semantics across versions). Otherwise, unnamed codes are used,
allocated by PROJ ticket number (ticket PROJ-12345 → codes
`1234500`–`1234599`), never duplicated. log codes share the same space
and the same allocation rule.

## 9. Error messages

`Status` and assertion messages SHOULD NOT end in punctuation.
Good: `throwUserError(1234500, "query planning failed", success);`

## 10. Assertions

- `throwUserError()` — fails a user-facing operation, delivering the error to the
  user.
- `verify()` and `msgAssert()` — banned, MUST NOT be used.
- `debugAssert()` — MAY be used, but other assertion types SHOULD be preferred
  when the assertion is cheap.
- `fatalAssert()` vs `invariant()` — both are process-fatal; `fatalAssert()` for a
  situation possible in practice, `invariant()` for a programmer error.
- `tripwireAssert()` vs `invariant()` — both indicate a programmer error.
  `invariant()` kills the whole server process; `tripwireAssert()` ("tripwire
  assertion") kills only the operation — the process lives on but exits
  non-OK at a safe point, failing the test. Use `invariant()` when
  violating the condition risks data or memory corruption or process-wide
  integrity (e.g. replication-log application, anything that would leak memory); use
  `tripwireAssert()` when only the operation must fail and the server as a whole
  stays in an acceptable state — common in query code, especially relevant
  in multi-tenant environments where one tenant's tripwire must not kill
  everyone. When choosing `invariant()` over `tripwireAssert()`, a comment is
  required explaining why the failure is process-fatal, not just
  operation-fatal. The same guidance applies to `UNREACHABLE` vs
  `UNREACHABLE_TRIPWIRE`.

## 11. Includes and license header

Every source file starts with the license header; include ordering follows
the team's code-style conventions (not reproduced here).

## 12. Casting

C-style casts are forbidden; use `static_cast<T>(...)` and the other
named casts.

## 13. Exceptions vs Status

Prefer exceptions for errors expected to propagate to top-level handlers
(e.g. a malformed user query). Returning `Status` is acceptable when the
caller must branch on the error.

## 14. Unsigned integers

Avoid unsigned types unless representing a bit pattern or needing defined
modulo-2^N overflow. Do not use unsigned to mean "never negative" — use an
assertion instead. (STL container sizes are unsigned, so interacting with
containers may require them.)

## 15. Const placement

`const` is written before the type name, not after:
`void f(const T* t); void g(const U& u);`. A const pointer is also written
left-to-right: `void f(const T* const t); void g(U* const u);`

## 16. IDL command classes

IDL request-parsing classes SHOULD be named `CmdNameCommandRequest`; the
corresponding response classes SHOULD be named `CmdNameCommandReply`.
