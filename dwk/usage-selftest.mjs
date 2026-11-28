#!/usr/bin/env node
// dwk/usage-selftest.mjs — deterministic check of the child-context telemetry.
//
//   node dwk/usage-selftest.mjs      exits 0 when every check passes, 1 otherwise
//
// Feeds a synthetic opencode event stream through the real plugin hooks
// (plugin/dwk-usage.js) into a temp usage directory, then reads the JSONL back
// and runs dwk/stats.mjs --context over it. Covers: peak, compaction by the
// drop heuristic, compaction by the session.compacted event (no double count),
// threshold crossings, per-project config (valid, invalid JSON, absent), a call
// with no token data, root sessions (no ctx fields), the dispatch-threshold note.

import { mkdtempSync, mkdirSync, readFileSync, readdirSync, rmSync, writeFileSync } from "node:fs";
import { execFileSync } from "node:child_process";
import { tmpdir } from "node:os";
import { join, dirname } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));
const PLUGIN = join(HERE, "..", "plugin", "dwk-usage.js");
const STATS = join(HERE, "stats.mjs");

const TMP = mkdtempSync(join(tmpdir(), "dwk-usage-selftest-"));
const DATA = join(TMP, "usage");
const PROJ_DEFAULT = join(TMP, "proj-default"); // no dev-workflow.json
const PROJ_CAP = join(TMP, "proj-cap"); // usage.child_context_cap = 50000
const PROJ_BROKEN = join(TMP, "proj-broken"); // malformed dev-workflow.json
const PROJ_DISPATCH = join(TMP, "proj-dispatch"); // usage.dispatch_threshold = 3 (cap left at default)
for (const d of [PROJ_DEFAULT, PROJ_CAP, PROJ_BROKEN, PROJ_DISPATCH]) mkdirSync(d, { recursive: true });
writeFileSync(join(PROJ_DISPATCH, "dev-workflow.json"), JSON.stringify({ usage: { dispatch_threshold: 3 } }));
writeFileSync(join(PROJ_CAP, "dev-workflow.json"), JSON.stringify({ usage: { child_context_cap: 50000 } }));
writeFileSync(join(PROJ_BROKEN, "dev-workflow.json"), "{ not json");

// The plugin reads its directory at import time: set it before importing.
process.env.DWK_USAGE_DIR = DATA;
const { DwkUsage } = await import(pathToFileURL(PLUGIN).href);
const hooks = await DwkUsage({});

let n = 0;
const failures = [];
function check(name, cond, detail = "") {
  n++;
  if (cond) console.log(`ok   ${name}`);
  else { console.log(`FAIL ${name}${detail ? ` — ${detail}` : ""}`); failures.push(name); }
}

let seq = 0;
const tick = () => Date.now() + seq++ * 1000; // strictly increasing ms timestamps
const sess = (id, parentID, directory) => hooks.event({ event: { type: "session.created", properties: { info: { id, parentID, directory, title: id } } } });
const compacted = (sessionID) => hooks.event({ event: { type: "session.compacted", properties: { sessionID } } });
let mid = 0;
// One completed assistant call. tokens: {input, read, write} (cache ones optional).
function call(sessionID, tok, cost = 0) {
  const t = tick();
  const info = {
    id: `msg-${++mid}`, role: "assistant", sessionID, time: { created: t - 500, completed: t },
    providerID: "p", modelID: "m", agent: "build", finish: "stop", cost,
  };
  if (tok) info.tokens = { input: tok.input || 0, output: 500, reasoning: 0, cache: { read: tok.read || 0, write: tok.write || 0 } };
  return hooks.event({ event: { type: "message.updated", properties: { info } } });
}

// ---- synthetic stream --------------------------------------------------------
await sess("P", undefined, PROJ_DEFAULT);
// C1: heuristic only. ctx 60k, 120k (rise over 100k), 150k (peak), 40k (drop from 150k), 120k (rise again).
await sess("C1", "P", PROJ_DEFAULT);
await call("C1", { input: 20000, read: 40000 });
await call("C1", { input: 30000, read: 40000, write: 50000 });
await call("C1", { input: 25000, read: 125000 });
await call("C1", { input: 10000, read: 30000 });
await call("C1", { input: 20000, read: 100000 });
// C2: host event. ctx 130k (rise), event, then a drop that must not be counted twice.
await sess("C2", "P", PROJ_DEFAULT);
await call("C2", { input: 30000, read: 100000 });
await compacted("C2");
await call("C2", { input: 20000 });
// C3: a completed call with a cost but no token data: no ctx, no crash.
await sess("C3", "P", PROJ_DEFAULT);
await call("C3", null, 0.5);
// C4: project cap 50k. ctx 60k (rise over 50k), 20k (drop, 20k < 30k, previous 60k > 50k).
await sess("C4", "P", PROJ_CAP);
await call("C4", { input: 60000 });
await call("C4", { input: 20000 });
// C5: malformed config falls back to the 100k default: 60k never crosses, 20k never flagged.
await sess("C5", "P", PROJ_BROKEN);
await call("C5", { input: 60000 });
await call("C5", { input: 20000 });
// dispatch_threshold = 3 in PROJ_DISPATCH: PD has 3 children (fires), PE has 2 (does not).
// CD mirrors C1's stream: its counters must match C1's, the key must not change them.
await sess("PD", undefined, PROJ_DISPATCH);
for (let i = 0; i < 3; i++) { await sess(`D${i}`, "PD", PROJ_DISPATCH); await call(`D${i}`, { input: 1000 }); }
await sess("PE", undefined, PROJ_DISPATCH);
for (let i = 0; i < 2; i++) { await sess(`E${i}`, "PE", PROJ_DISPATCH); await call(`E${i}`, { input: 1000 }); }
await sess("CD", "PF", PROJ_DISPATCH);
await call("CD", { input: 20000, read: 40000 });
await call("CD", { input: 30000, read: 40000, write: 50000 });
await call("CD", { input: 25000, read: 125000 });
await call("CD", { input: 10000, read: 30000 });
await call("CD", { input: 20000, read: 100000 });

// Root session: a huge call, but roots get no ctx fields.
await sess("R", undefined, PROJ_DEFAULT);
await call("R", { input: 500000 });
// Dispatch threshold (default 10): a parent with 10 children in the window.
await sess("PX", undefined, PROJ_DEFAULT);
for (let i = 0; i < 10; i++) { await sess(`X${i}`, "PX", PROJ_DEFAULT); await call(`X${i}`, { input: 1000 }); }

// ---- read back ---------------------------------------------------------------
const recs = [];
for (const f of readdirSync(DATA)) {
  if (!/^\d{4}-\d{2}\.jsonl$/.test(f)) continue;
  for (const line of readFileSync(join(DATA, f), "utf8").split("\n")) if (line.trim()) recs.push(JSON.parse(line));
}
const msgsOf = (s) => recs.filter((r) => r.t === "msg" && r.session === s);
const last = (s) => msgsOf(s).at(-1);

const c1 = msgsOf("C1");
check("C1 ctx per call = input + cache.read + cache.write", c1.map((r) => r.ctx).join() === "60000,120000,150000,40000,120000", c1.map((r) => r.ctx).join());
check("C1 peak = 150000", last("C1").ctx_peak === 150000, String(last("C1").ctx_peak));
check("C1 compacted = 1 (drop heuristic, 150k -> 40k)", last("C1").ctx_compacted === 1, String(last("C1").ctx_compacted));
check("C1 crossings = 2 (rise over 100k twice)", last("C1").ctx_crossings === 2, String(last("C1").ctx_crossings));
check("C2 peak = 130000 (ctx of the rise)", last("C2").ctx_peak === 130000, String(last("C2").ctx_peak));
check("C2 compacted = 1 (host event; drop not double-counted)", last("C2").ctx_compacted === 1, String(last("C2").ctx_compacted));
check("C2 crossings = 1", last("C2").ctx_crossings === 1, String(last("C2").ctx_crossings));
check("C3 no token data: ctx null, no flags", msgsOf("C3").length === 1 && last("C3").ctx === null && last("C3").ctx_compacted === 0 && last("C3").ctx_crossings === 0);
check("C4 config cap 50k: 1 crossing, 1 compaction", last("C4").ctx_crossings === 1 && last("C4").ctx_compacted === 1, `${last("C4").ctx_crossings}/${last("C4").ctx_compacted}`);
check("CD dispatch key: peak/compacted/crossings = C1's (150000/1/2)", last("CD").ctx_peak === 150000 && last("CD").ctx_compacted === 1 && last("CD").ctx_crossings === 2, `${last("CD").ctx_peak}/${last("CD").ctx_compacted}/${last("CD").ctx_crossings}`);
check("C5 malformed config: default cap, no flags", last("C5").ctx_crossings === 0 && last("C5").ctx_compacted === 0, `${last("C5").ctx_crossings}/${last("C5").ctx_compacted}`);
check("root session: msg record has no ctx fields", msgsOf("R").length === 1 && !("ctx" in last("R")) && !("ctx_peak" in last("R")));
check("session records still written (parent link kept)", recs.some((r) => r.t === "session" && r.session === "C1" && r.parent_session === "P"));

// Backward compat: a legacy msg record (no ctx keys) must still parse and render.
const legacy = { t: "msg", ts: new Date().toISOString(), msg_id: "legacy-1", session: "L", provider: "p", model: "m", tokens: { in: 1, out: 1, reasoning: 0, cache_read: 0, cache_write: 0 }, cost: null, finish: "stop" };
writeFileSync(join(DATA, `${new Date().toISOString().slice(0, 7)}.jsonl`), JSON.stringify(legacy) + "\n", { flag: "a" });

// ---- stats --------------------------------------------------------------------
const out = execFileSync(process.execPath, [STATS, "--data", DATA, "--context"], { encoding: "utf8" });
const groupRow = out.split("\n").find((l) => l.startsWith("p/m"));
const cols = groupRow ? groupRow.trim().split(/\s+/).slice(-3) : [];
// peak = max over children (150000); compact = sum of per-session totals (C1 1 + C2 1 + C4 1 + CD 1); cross = 2 + 1 + 1 + 2
check("stats --context: group peak/compact/cross = 150000/4/6", cols.join("/") === "150000/4/6", cols.join("/"));
check("stats --context: dispatch note for PX (10 children)", out.includes("parent session PX dispatched 10 child session(s)"));
check("stats --context: no dispatch note for P (5 children)", !out.includes("parent session P dispatched"));
check("stats --context: dispatch_threshold 3 fires for PD (3 children)", out.includes("parent session PD dispatched 3 child session(s)") && out.includes("usage.dispatch_threshold 3"));
check("stats --context: no note for PE (2 children, threshold 3)", !out.includes("parent session PE dispatched"));
const plain = execFileSync(process.execPath, [STATS, "--data", DATA], { encoding: "utf8" });
check("stats without --context: no ctx columns", !plain.includes("compact") && !plain.includes("peak"));

rmSync(TMP, { recursive: true, force: true });
console.log(`\n${n - failures.length}/${n} checks passed`);
process.exit(failures.length ? 1 : 0);
