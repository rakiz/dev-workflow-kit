# A1-A5 probe verdict (2026-11-27, opencode 1.19.6)

Probe: probe.js (event + chat.message logger). Raw log: probe.jsonl (sandbox run).
Sessions: 3 headless `opencode run` (ai-gateway-misc/fw-deepseek-v4.1-flash;
github-copilot/claude-haiku-5.5; a command `a5`).

- A1 cost populated: HOLDS. copilot msg cost 0.00481165 (tokens input 4, cache.write 38474);
  ai-gateway msg cost 0.0047137. Estimate fallback not needed for either.
- A2 mode == agent: HOLDS. mode "build" == agent "build" in every assistant record.
- A3 completion once: DOES NOT HOLD in strict form. message.updated fired 3x per assistant
  message (completed null, null, set). Dedupe by message id, last write wins (plan fallback).
- A4 gen/ shape: fields used (parentID, modelID, providerID, tokens.cache) match the gen types.
  The v2 tree was not compared.
- A5 command w/o LLM: DOES NOT HOLD. The `!` shell injection ran (A5_SHELL_RAN_42), but the
  command also produced 9 assistant messages (a model turn). Fallback: status.md pattern.

Decision: GO (A1 holds; A3 is a dedupe requirement, not a blocker).
