---
description: Usage stats from the dev-workflow-kit recorder (/dwk stats, /dwk live)
agent: cheap-mech
---

Run the usage script and print its output exactly, without commentary.

Arguments given: `$ARGUMENTS`

Accept only these forms, each token passed as its own double-quoted argument:
- empty (this month, by model), or `today`, `week`, `month`, `live`
- `range YYYY-MM-DD YYYY-MM-DD`
- `--project PATH` (PATH is one double-quoted argument)
- `--by model|agent|task` (`--by task` is the per-task view)
- `--context` (child-context columns: peak, compactions, crossings; combines with `--by`)
- `--prune`

If the arguments contain anything else, do NOT run the script. Tell the user the accepted forms above instead.

Run: `node "$DWK_STATS" --models "$DWK_MODELS" <accepted arguments>`

`live` re-renders every 5 s in an interactive terminal (stop with Ctrl-C); when stdout is not a TTY it renders once and exits.

Show the script's output unchanged. If it reports `$?`, say that a model has no price in models.json yet (the cost is unknown, not zero).
