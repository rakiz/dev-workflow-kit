---
description: Usage stats from the dev-workflow-kit recorder (/dwk stats, /dwk live)
agent: cheap-mech
---

Run the usage script and print its output exactly, without commentary.

Arguments given: `$ARGUMENTS`

- If the arguments start with `live`, run `node "$DWK_HOME/dwk/stats.mjs" live` and tell the user to stop it with Ctrl-C.
- Otherwise run `node "$DWK_HOME/dwk/stats.mjs" $ARGUMENTS` (empty arguments = this month, by model).

`$DWK_HOME` is the kit checkout the roster was installed from; if unset, look for `dwk/stats.mjs` under `~/dev-workflow-kit`.

Accepted forms: `today`, `week`, `month`, `range YYYY-MM-DD YYYY-MM-DD`, each with optional `--project PATH` and `--by model|agent|task`, and `--prune` (deletes usage files older than 13 months).

Show the script's output unchanged. If it reports `$?`, say that a model has no price in models.json yet (the cost is unknown, not zero).
