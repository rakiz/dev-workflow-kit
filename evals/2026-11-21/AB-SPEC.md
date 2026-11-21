# AB-SPEC — Étape 4: workflow ROI A/B (pre-registration)

**Status: pre-registered before any arm runs. Spec v2, 2026-11-21. No result yet.**
v2 supersedes v1 with the review fix set M1–M8 / m1–m9 (fix log §8).
Source: `PROTOCOL.md` §7 (smoke A/B) + `NEXT-SESSION.md` item 5. An **ops
experiment**, not a bench.

**The question (M1 scope).** This design tests **"does the pipeline deliver
comparable work for less API money"** — **not** the full human-cost claim: the
experiment is autonomous, so operator interventions are **zero by construction**
for all arms. `total$ = api$ + H × human_touches` with `human_touches = 0`; the
H = $2/$10 pricing stays in the metrics table for future reuse.

**The claim under test (A vs B).** `score` = mean over **delivered** cells (M6);
delivery = task count (x/5, m6). A wins iff `score_A − score_B ≥ 2.0` **and**
`delivery_A − delivery_B ≥ 1` **and** `api$_A < api$_B`; ordered verdicts in §4.

---

## 1. The 5 tasks (new; not from any bench fixture)

Five fresh throwaway repos, one per task, Python 3.10 stdlib only, no network,
no hints. Layout:

```
evals/2026-11-21/ab/tasks/T<n>/start/     ← copied into each cell, byte-identical
evals-keys/ab-2026-11-21/required/T<n>/   ← PRIVATE: hidden required tests + reference answer
```

`start/` is what the arm receives; the required test is **never** shipped. The
builder runs `python3 -m unittest` in `start/` (green, except T3's red repro) and
records the hashes (§6). **Escaped defect (m1) = one failing required test
METHOD (each method has ≥1 assert), not one assertion.**

| # | Type | Start repo (≤150 code lines + tests) | Definition of done | Required test (hidden) | Trap |
|---|---|---|---|---|---|
| **T1** | small feature add | `wordtop.py` (CLI: `--top N`, positional files, casefold + punctuation strip), `test_wordtop.py` (green), `README.md`, `data/sample.txt` | (1) `--min-length K` (default 0) drops normalized words shorter than K; (2) `--json` prints exactly `{"top":[{"word","count"}],"total_words"}`, **`total_words` counted after filtering**; (3) ties count-desc then word-asc; (4) `--min-length 0` equals default; invalid K → exit 2 + stderr line; (5) existing flags unchanged | test methods over a fixture corpus: filtering, JSON shape (incl. `total_words` post-filter), tie order, K=0, exit 2, unchanged `--top` | tie order; `K=0` |
| **T2** | mechanical refactor | `csvsort.py`: `sort_rows(rows, key, reverse=False)` and `sort_rows_stable(rows, key)` sharing a copy-pasted ~40-line block; CLI; `test_csvsort.py` (green); `data/{a,b,c}.csv` | one shared helper; both functions delegate; **signatures pinned exactly as above**; stdout byte-identical on a/b/c; same exit codes and error text; the duplicated block appears once | golden stdout ×3 + error text + `inspect.signature` equality on both functions + **sentinel count ≤ 1** | the error text; stable-sort tie order |
| **T3** | bug fix with a repro | `durutil.py` `parse_duration(text) -> int or None`; shipped bugs: `90m→None`, `1h30→None`, `10sx→10`; `test_durutil.py` with **3 red repro tests**; `REPRO.md` | the 3 repro tests green; the grammar (below) holds; no other behavior changes | **12 test methods = the full grammar table** (below) | reject trailing junk; trim whitespace |
| **T4** | test writing | `intervals.py` `merge(intervals)` documented to merge overlapping **and adjacent** intervals, unsorted input, sorted output; shipped code misses adjacency; `test_intervals.py` with 2 trivial green tests; `CONTRACT.md` | the arm writes/extends **`test_intervals.py`**; the DoD is exactly **the suite passes on the unmutated tree AND fails on mutant M** (the shipped adjacency defect must be fixed in one line for the suite to pass — explicitly allowed and reported) | runner runs `test_intervals.py` unmutated (must PASS) then with `intervals.py` swapped for the frozen `mutant_M.py` (must FAIL) | the adjacency edge = exactly M |
| **T5** | design + impl | `prune.py` (lists `notes/`), `notes/` with 12 dated files, `test_prune.py` (green), `README.md` | **`DESIGN-prune.md`** (≤1 page) with four headed sections — Policy, Ordering, Dry-run, Failure end state; `--keep N` keeps the newest N **by mtime, tie by name ascending**, deletes the rest oldest-first; `--dry-run` prints the would-delete list and **touches nothing** (no unlink, **no mtime change**); an unreadable note is skipped, the run continues, exit 1 with a one-line summary; deletions are whole-file unlinks (crash = deleted prefix, stated in the design) | dry-run: hashes **and** mtimes unchanged; exact keep-N set under the mtime rule; unreadable file → exit 1 with the other deletions done; the four DESIGN headings present | dry-run must not touch mtimes; exit 1 with partial progress |

**T3 grammar — all 12 hidden cases (the brief shows only 4 of them):**
`45s→45` · `90m→5400` · `1h30m→5400` · `1h30→5400` · `2h→7200` · `" 2h "→7200` ·
`0s→0` · `1h0m→3600` · `10sx→None` · `""→None` · `1x→None` · `30→None`.
The brief's visible subset: `45s`, `90m`, `1h30m`, `10sx→None`.

**T2 sentinel (M8).** `start/` carries the named comment
`# AB-SENTINEL: shared-core` in **both** duplicated blocks; it is exempt from
the flaw-comment ban (it is the refactor's measurable marker, not a hint). The
required test counts its occurrences (≤ 1 after the refactor).

---

## 2. The 3 arms (exactly these; nothing else runs)

Same tasks, same start trees, **30 min wall per task per arm** (watchdog kill →
DNF, §5), no human in the loop. Session titles are **`ab-<arm>-t<k>`** (m2:
e.g. `ab-A-t3`), so the DB roll-up by the `ab-` prefix scopes the campaign spend.

| Arm | Route, in order | Session cap (M4) |
|---|---|---|
| **A — kit pipeline** | **T1/T3/T4 code:** `cheap-code` (haiku-5.5 default) → `cheap-review` (minimax-m3p1 xhigh) → *minor*: one `cheap-code` fix → stop; *major*: `strong-code` (minimax xhigh) fix → **`strong-review` (sonnet-5.5 medium) final review** → if *major*/doubt: `strong-code-alternative` (haiku-5.5 high) fix once → stop. `ESCALATE-CANDIDATE` from the producer after 2 fruitless attempts → `strong-code` → `strong-review`. **T2:** `cheap-mech` (deepseek-v4.1-flash) → `cheap-review` → one fix. **T5:** `cheap-design` (haiku medium) → `cheap-design-review` (minimax medium) → one `cheap-design` fix → then the T5-impl code route. | T1/T3/T4 ≤ **5** · T5 ≤ **8** |
| **B — sonnet alone** | `claude-sonnet-5.5` **high**, one session, no review. | 1 |
| **C — sonnet + one review** | `claude-sonnet-5.5` high implements → `strong-review` seat: `claude-sonnet-5.5` **medium** reviews once → if findings, one sonnet-high fix; no second review. | ≤3 |

- **Lineage (M2).** The route names the rule: `PROTOCOL.md` §2 rule 7 — *impl and
  review are never the same family*. `cheap-code`/`cheap-mech` (claude/deepseek)
  are reviewed by `cheap-review` (minimax); a `strong-code` fix (minimax) is
  reviewed by **`strong-review` (claude)**, never by `cheap-review`. Arm A is
  lineage-legal **by that rule**, not by assertion.
- **Verdict line (M3).** Both arms' review briefs require one final line
  `VERDICT: major` or `VERDICT: minor`. Arm C's fallback: absent/malformed
  verdict → treat as **minor** → one fix round, recorded in the deviation
  ledger. The scripted driver routes mechanically on the line.
- **Truncation (M4).** A route that would exceed its cap stops at the cap; the
  cell records `TRUNCATED: <reason>` in the report and the deviation ledger.
  An `ESCALATE-CANDIDATE` or a strong-code doubt consumes the same cap.
- The arm's report is the runner's capture (`final-report.md`, v6 machinery);
  the blind bundle carries it as `REPORT.md` (M5). Latency = summed session
  wall time; cost = DB roll-up.

---

## 3. Adjudication (blind, two adjudicators, kappa)

**Bundle (M7).** Each of the 15 cells is copied to `blind/<id>/` with **only**:
the delivered tree, `REPORT.md`, the task's DoD text, the required test, and the
baseline `start/` tree (for `clean`). Vendor/model/effort/agent names stripped;
paths carry only the ID.

**IDs (m5, frozen).** IDs are drawn **once** at build with
`python3 -c 'import secrets;print(secrets.token_hex(3))'`, recorded in
`evals-keys/ab-2026-11-21/id-map.tsv` (sealed), never regenerated; the runner
uses the frozen map.

**Presentation order (2×2, exact arrays).**
`J1: T1[A,B,C] · T2[B,C,A] · T3[C,A,B] · T4[A,B,C] · T5[B,C,A]`
`J2: T1[C,B,A] · T2[A,C,B] · T3[B,A,C] · T4[C,B,A] · T5[A,C,B]`.

**Checklist (per cell; bounded integers).**

| Dim | Scale | Rule |
|---|---|---|
| `test` | 0 / 2 / 3 | 3 = every required test method passes; 2 = core methods pass, the trap method fails; 0 = a core method fails or the test cannot run |
| `dod` | 0 / 1 | every DoD bullet demonstrably present |
| `clean` | 0 / 1 | 1 = no unrequested abstraction/dependency/API change **relative to the baseline tree**; 0 = overengineering flag |
| `escaped` | 0..5 | count of **failing required test methods** (the trap is the last method); reported, not scored |
| `score` | 0..5 | `test + dod + clean` |

**Procedure.** Both adjudicators score all 15 cells independently, each
re-running the required test in their copy (executed evidence). Sheets lock
together, then **κ per variable** (`core_pass`, `trap_pass`, `dod`, `clean`)
over the 15 cells: all-agree → **κ = 1** (degenerate, recorded); κ ≥ 0.6
acceptable; κ < 0.6 → one reconciliation round on the flagged cells only
(builder as executor, never scorer); persisting divergence → conservative
values + a κ warning.

**T4/T5 pinned files (M7/M8).** T4's suite is `test_intervals.py`; T5's design
is `DESIGN-prune.md`. **T4 test injection (m8):** the runner copies the
delivered tree, swaps `intervals.py` for the frozen `mutant_M.py` (hash
recorded at freeze), runs `test_intervals.py` (expects FAIL), restores the
original, runs again (expects PASS).

**Disagreement rule (pre-registered order).** 1) `test`: a third party (the
builder, execution only) re-runs; the executable result wins. 2) `dod`/`clean`:
conservative (lower) value, cell flagged. 3) if it changes a verdict branch,
the owner rules, both sheets attached.

---

## 4. Metrics and the verdict

| Metric | Definition |
|---|---|
| `delivery` | delivered cells, **count** x/5 (scoreable tree + report within budget) |
| `reruns` | automated re-runs (DNFs), ops data — **not** human touches |
| `agent_sessions` | Σ sessions per cell (ops data) |
| `escaped` | Σ failing required test methods across delivered cells |
| `score` | mean cell score **over delivered cells** (M6); delivery is primary, score secondary |
| `latency` | median and max wall time per cell |
| `api$` | DB roll-up, parent + children |
| `human_touches` | actual human/operator interventions — **0 by construction** (M1) |
| `human$` | `H × human_touches` (H = $2 / $10 kept for future reuse) |
| `total$` | `api$ + human$` (= `api$` here) |

**Ordered decision table (m7).** Evaluate top-down; first match wins.

| # | Condition | Verdict |
|---|---|---|
| R1 | `score_C ≥ score_A` **and** `delivery_C ≥ delivery_A` **and** `api$_C ≤ api$_A` | **DOMINATED** (by C; reported, no roster change) |
| R2 | floor met **and** `api$_A ≥ api$_B` | **REFUTED** (better work, no saving) |
| R3 | floor not met **and** `api$_A ≥ api$_B` | **REFUTED** (neither better nor cheaper) |
| R4 | floor not met **and** `api$_A < api$_B` | **TIE** (cheaper, not better; no roster change) |
| R5 | floor met **and** `api$_A < api$_B` | **A WINS** |
| — | *floor* = `score_A − score_B ≥ 2.0` (over delivered cells) **and** `delivery_A − delivery_B ≥ 1` (counts, m6) | |

**The floor is not an MDE.** No run-to-run noise is measured here; 2.0/1 task
is a deliberately large, pre-registered floor for n = 5. A gap below it is a tie.

---

## 5. Budget, metering, DNF

- **Caps:** A $3.00 · B $5.00 · C $7.00 · adjudicators 2 × $2.50 = $5.00 →
  **$20.00**; **$5.00 reserve** (DNF re-runs **and adjudicator replacements**);
  **campaign hard cap $25.00**.
- **Adjudicator replacements (m4).** Replacement order, non-producer families
  only: neon → **argon** (same family, recorded risk) → **grok-4.7**; qwen →
  **grok-4.7** → **argon**. Neon's DNF risk is budgeted from its 2026-11-20
  record (5/6 delivered; one DNF ≈ $0.16): one neon re-run sits in the $5
  reserve. A second DNF → replacement from the list, recorded.
- **Metering:** `session` DB roll-up by the `ab-` title prefix (parent +
  children); providers absent from the DB are priced from the catalog table
  (`opencode models <provider> --verbose`) with the arithmetic shown. Per-arm
  poller kills at 2×cap; the campaign poller stops above $25.00; admission
  `spend + 2×cap ≤ 25.00`.
- **DNF:** re-run once; a **second DNF → delivery 0**, and `score` never
  averages a DNF cell (it is a mean over delivered cells, §4). DNF cost is
  recorded; DNFs are delivery failures, never "bad work".
- **Expected spend ≈ $4 (range $3.5–6.5):** A ≈ $0.35–0.75 (the strong-review
  final adds ≈ $0.05–0.10/task on the major path); B ≈ $1.00–2.00; C ≈
  $1.50–2.80; adjudication ≈ $0.50–1.00. The caps are the bound, not the
  estimate.

---

## 6. Roles and hygiene

| Role | Who | Constraint |
|---|---|---|
| Builder | one agent (kit `cheap-code` + a review) | builds the 5 start repos, the hidden required tests, the traps, `mutant_M.py`, the reference answers, the blinding; **never adjudicates**; executes tests only |
| Runner | scripted driver (no model) | arm routing, 30-min watchdogs, polls, captures (`final-report.md`), blinding; no human input mid-run |
| Adjudicator 1 | fresh `gemini-4-neon` | blind; prompt contains **zero model/vendor names** |
| Adjudicator 2 | fresh `qwen3p8-2p4t` | blind; same prompt, opposite order array |
| Owner | — | budget approval; reads the verdict; rules only on step-3 disagreements |

- Adjudicator families are **not producers** (producers: claude, minimax,
  deepseek). Replacements per §5 (m4), recorded.
- Private artefacts (`required/`, the reference answers, `mutant_M.py`, the ID
  map) live in `evals-keys/ab-2026-11-21/`; the public tree carries the start
  repos and this spec only.
- **Freeze (m5):** sha256 of the 5 start trees, the 5 required tests,
  `mutant_M.py`, the two adjudicator prompts and `id-map.tsv` in
  `evals-keys/ab-KEY-MANIFEST.tsv` before the first run; **extend
  `evals-keys/holdout-ban.txt`** with `wordtop`, `csvsort`, `durutil`,
  `intervals`, `notesprune` (the holdout lint then covers them).
- **Deviation ledger (m3):** `evals/2026-11-21/ab/DEVIATIONS.md` — one line per
  recorded deviation (VERDICT fallback, TRUNCATED, replacement, exec-error).
- **Novelty:** no identifier shared with the five bench/held-out trees; the
  builder greps the ban list over `ab/`.

---

## 7. Scope, exemptions, what this does not decide

- **One cell per arm by design (M5).** This is a smoke A/B, not a scoring
  campaign: `PROTOCOL.md` §2 rule 1's two-run cell is **exempt** here. No cell
  is a capability estimate; the scores never enter `LEADERBOARD.html`.
- **M1 scope** is the header's: comparable work for less API money; the
  human-cost claim is not tested. **Not an MDE claim** (the floor is judgement,
  §4); **not a roster change** (any edit is a separate owner decision).
- **Blind-vs-unblind residual-bias sample is OUT OF SCOPE for this smoke**
  (m9): it belongs to Étape 3 (`ROADMAP-METHODO.md`) and is not measured here.
- **Freeze rule:** no change to this file, the start repos, the required tests
  or `mutant_M.py` after the first arm runs; a change voids the experiment.

---

## 8. Fix log (v1 → v2, review IDs)

| ID | Applied |
|---|---|
| M1 | `human_touches` = actual interventions (0 by construction); `total$ = api$ + H × human_touches`; ROI = score gap ≥ 2.0 + delivery gap ≥ 1 + `api$_A < api$_B`; H=$2/$10 kept for reuse; scope stated (§header, §4, §7) |
| M2 | arm A's post-`strong-code` review is `strong-review` (claude) — rule named (§2) |
| M3 | both review briefs carry `VERDICT: major/minor`; C fallback = minor + ledger (§2, §6) |
| M4 | caps = route length (5 / 8); truncation rule; `ESCALATE-CANDIDATE` + strong-code-doubt → alternative once, then stop (§2) |
| M5 | exemption clause (§7); DNF 2nd → delivery 0; `final-report.md` → `REPORT.md` naming (§2, §5, §7) |
| M6 | `score` = mean over delivered cells; delivery primary (§4) |
| M7 | exact 2×2 order arrays; κ per variable + degenerate rule; bundle enumerated incl. baseline tree; T4/T5 filenames pinned (§3) |
| M8 | T3 full 12-case grammar + visible subset; T1 `total_words` post-filter; T2 sentinel + signatures; T4 DoD resolved + filename; T5 mtime/tie (§1) |
| m1 | escaped = failing test **method** (≥1 assert) (§1, §3, §4) |
| m2 | titles `ab-<arm>-t<k>`; spend scope by `ab-` prefix (§2, §5) |
| m3 | deviation ledger file named (§6) |
| m4 | adjudicator replacement list + neon DNF budget (§5, §6) |
| m5 | frozen ID procedure + `holdout-ban.txt` extension (§3, §6) |
| m6 | delivery compared as counts x/5 (§4) |
| m7 | ordered verdict table R1–R5 (§4) |
| m8 | T4 mutant-injection procedure pinned (§3) |
| m9 | blind-vs-unblind sample declared out of scope, pointer to Étape 3 (§7) |
