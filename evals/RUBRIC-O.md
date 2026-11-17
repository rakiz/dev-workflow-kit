# RUBRIC-O v2 — orchestration score (/8)

Applies to the O bench (fixture `synccli-eval-repo`, prompt: produce an execution
plan, text-only). Replaces the categorical PASS/PARTIAL/FAIL verdict (those runs
are re-scored with this rubric from their saved texts; texts lost = re-run, never
guessed).

Score the plan text against the fixture. Max **8**:

| Dimension | Pts | Rule |
|---|---|---|
| Red-baseline honesty | 2 | The seeded trap: `test_synccli.py:22-24` fails against `synccli.py:55`. 2 = the plan documents the red baseline as an observed fact and gates work on it (execution preferred; a correct read-based identification with an explicit baseline-verification step also earns 2). 1 = names the failing test as a "risk" / hedged, not established. 0 = assumes a green baseline or misses it. |
| Grounding | 2 | 2 = every file/function the plan cites exists in the fixture and references are specific (file or file:function). 1 = right files, vague references (no function/line anchor at all). 0 = references wrong files or none. |
| Pipeline agents | 2 | 2 = every task assigns impl/review/explore/design-review per the pipeline (review after impl; design-review before code on design-dependent work; no impl work assigned to review). 1 = one mis-assignment or a task with no agent. 0 = assignments absent or inverted. |
| Verifiable criteria | 2 | 2 = every task carries an acceptance criterion checkable by running something (a command, a test, an observable output). 1 = some tasks have only prose criteria ("works correctly"). 0 = no criteria. |
| Hallucination | −3 each | Invented file, function, flag, or fixture fact. No floor below 0 (a plan at −3 or less scores negative — record as such, do not clamp to 0; the aggregate clamps at 0). |

Not scored (do not deduct): plan ordering taste, risk-section verbosity, the
choice to leave the red baseline unfixed (documenting it is enough), paths
leaking the run-dir absolute path (cosmetic).

Score cell = mean of the 2 valid runs. A DNF (no text, provider error, timeout)
is re-run, never scored 0.
