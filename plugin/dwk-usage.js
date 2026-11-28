// dwk-usage — opencode plugin: records one usage line per completed assistant
// message and one per session, to an append-only monthly JSONL file.
//
// Location: ${XDG_DATA_HOME:-~/.local/share}/dev-workflow-kit/usage/YYYY-MM.jsonl
// Errors:   .../usage/errors.log
//
// Contract (plan §3.8): never blocks or fails a session. Every hook body is
// wrapped; any failure is appended to errors.log and swallowed. A message is
// recorded once, when it reports completion (time.completed set); earlier
// message.updated writes for the same id are ignored (verified A3: the event
// fires several times per message). Cost 0 (subscription providers) is kept as
// the provider's value and flagged; the estimate is computed by stats, not here.
//
// Record shapes (append-only JSONL, one object per line):
//   {t:"msg", ts, start_ts, msg_id, session, parent_session, agent, provider,
//    model, variant, tokens:{in,out,reasoning,cache_read,cache_write}, cost, finish}
//     ts        = time.completed (ISO, the end of the message; back-compat key)
//     start_ts  = time.created (ISO, the start of the message), or null when the
//                 host reported no time.created. Records written before the
//                 start_ts field have NO start_ts key at all (not null).
//     span      = ts - start_ts (computed by stats, not stored)
//   {t:"session", ts, session, parent_session, project_root, title}
//   Child sessions (parent_session set) also carry context fields on each msg
//   record (absent on records written before them, and on root sessions):
//     ctx          = context tokens of this call = input + cache.read + cache.write
//                    (null when the host reported no prompt tokens)
//     ctx_peak     = max ctx seen so far in the session (running value)
//     ctx_compacted= compactions seen so far (running value)
//     ctx_crossings= rises above usage.child_context_cap so far (running value)
//   The running values are monotone within a plugin process run; a restart resets
//   the running counters (peak survives via stats' per-session max; compaction and
//   crossing counts may undercount across a restart).
// Compaction signal: the host's session.compacted event (preferred). Sessions
// that never received one fall back to the drop heuristic: a call whose ctx is
// under half of the previous call's ctx, while that previous ctx was above the cap.
// Config: dev-workflow.json "usage" of the session's project (read once per
// process; absent or invalid keys fall back to the defaults below).
// Dedup state (not a record): usage/recorded-ids.txt, the ids of recorded msgs.
import { appendFileSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { homedir } from "node:os";
import { join } from "node:path";

// DWK_USAGE_DIR redirects the recorder alone (tests); XDG_DATA_HOME would also move opencode's own data dir and its credentials.
const USAGE_DIR = process.env.DWK_USAGE_DIR || join(process.env.XDG_DATA_HOME || join(homedir(), ".local", "share"), "dev-workflow-kit", "usage");

function ensureDir() { mkdirSync(USAGE_DIR, { recursive: true }); }

function logError(where, err) {
  try {
    ensureDir();
    const line = `${new Date().toISOString()} ${where}: ${err && err.stack ? err.stack : String(err)}\n`;
    appendFileSync(join(USAGE_DIR, "errors.log"), line);
  } catch (_) { /* nothing more can be done without blocking */ }
}

function write(record) {
  const month = new Date().toISOString().slice(0, 7); // YYYY-MM (UTC)
  ensureDir();
  appendFileSync(join(USAGE_DIR, `${month}.jsonl`), JSON.stringify(record) + "\n");
}

// Ids already recorded, persisted in usage/recorded-ids.txt (one id per line,
// capped at SEEN_CAP): a completion event can repeat, also after a restart.
const SEEN_FILE = join(USAGE_DIR, "recorded-ids.txt");
const SEEN_CAP = 10000;
function loadRecorded() {
  let ids;
  try { ids = readFileSync(SEEN_FILE, "utf8").split("\n").filter(Boolean); } catch (_) { return new Set(); }
  if (ids.length > SEEN_CAP) {
    ids = ids.slice(-SEEN_CAP);
    try { writeFileSync(SEEN_FILE, ids.join("\n") + "\n"); } catch (_) { /* cap is best effort */ }
  }
  return new Set(ids);
}
const recorded = loadRecorded();
// Sessions already recorded in this process.
const sessionsSeen = new Set();
// session id -> { dir, parent } from the session events (parent null = root).
const sessionMeta = new Map();

// ---- child context telemetry -------------------------------------------------
const USAGE_DEFAULTS = { child_context_cap: 100000 };
const configCache = new Map(); // project root -> usage config
function usageConfig(root) {
  if (!root) return USAGE_DEFAULTS;
  if (configCache.has(root)) return configCache.get(root);
  let cfg = USAGE_DEFAULTS;
  try {
    const u = JSON.parse(readFileSync(join(root, "dev-workflow.json"), "utf8"))?.usage || {};
    const pick = (v, dflt) => (typeof v === "number" && Number.isFinite(v) && v > 0 ? v : dflt);
    cfg = { child_context_cap: pick(u.child_context_cap, USAGE_DEFAULTS.child_context_cap) };
  } catch (_) { /* absent or malformed config: defaults */ }
  configCache.set(root, cfg);
  return cfg;
}

const num = (v) => (typeof v === "number" && Number.isFinite(v) ? v : 0);
// Context of one call (see header). null = no prompt tokens reported.
function contextOf(tokens) {
  if (!tokens) return null;
  const c = tokens.cache || {};
  const n = num(tokens.input) + num(c.read) + num(c.write);
  return n > 0 ? n : null;
}

// Per child session: last ctx, peak, compacted, crossings, and whether the host
// has sent a compaction event for it (then the drop heuristic is off for it).
const ctxState = new Map();
function stateOf(sid) {
  let st = ctxState.get(sid);
  if (!st) { st = { last: null, peak: 0, compacted: 0, crossings: 0, eventSeen: false }; ctxState.set(sid, st); }
  return st;
}
// Folds one call's ctx into the session state; returns the running totals.
function observeContext(sid, ctx, cap) {
  const st = stateOf(sid);
  if (ctx != null) {
    if (!st.eventSeen && st.last != null && st.last > cap && ctx < st.last / 2) st.compacted++;
    if (ctx > cap && (st.last ?? 0) <= cap) st.crossings++;
    st.peak = Math.max(st.peak, ctx);
    st.last = ctx;
  }
  return { peak: st.peak, compacted: st.compacted, crossings: st.crossings };
}
function onCompacted(sid) {
  if (!sid) return;
  const st = stateOf(`${sid}`);
  st.compacted++;
  st.eventSeen = true;
}

function onMessage(info) {
  if (!info || info.role !== "assistant") return;
  if (!info.time || !info.time.completed) return; // not finished yet (A3)
  if (info.error) return; // a failed call is not spend (it returned no answer)
  if (recorded.has(info.id)) return;
  const t = info.tokens || {};
  const c = t.cache || {};
  // A completed turn with no tokens and no cost is routing noise (e.g. a command
  // dispatch), not spend: skip the message. Its session record is still written.
  const spent = num(t.input) + num(t.output) + num(t.reasoning) + num(c.read) + num(c.write);
  if (spent === 0 && !(typeof info.cost === "number" && info.cost > 0)) return;
  recorded.add(info.id);
  // Context fields: child sessions only (a session known to be a root gets none).
  const meta = sessionMeta.get(`${info.sessionID}`);
  let ctxFields = {};
  if (!(meta && meta.parent === null)) {
    const ctx = contextOf(t);
    const snap = observeContext(`${info.sessionID}`, ctx, usageConfig(meta && meta.dir).child_context_cap);
    ctxFields = { ctx, ctx_peak: snap.peak, ctx_compacted: snap.compacted, ctx_crossings: snap.crossings };
  }
  write({
    ...ctxFields,
    t: "msg",
    ts: new Date(info.time.completed).toISOString(),
    start_ts: info.time.created ? new Date(info.time.created).toISOString() : null,
    msg_id: info.id,
    session: info.sessionID,
    parent_session: null, // filled from the session record (see onSession)
    agent: info.agent || info.mode || null, // A2: equal in practice; mode is the fallback
    provider: info.providerID || null,
    model: info.modelID || null,
    variant: info.variant || null,
    tokens: { in: t.input || 0, out: t.output || 0, reasoning: t.reasoning || 0, cache_read: c.read || 0, cache_write: c.write || 0 },
    cost: typeof info.cost === "number" ? info.cost : null,
    finish: info.finish || null,
  });
  appendFileSync(SEEN_FILE, `${info.id}\n`);
}

function onSession(s) {
  if (!s || !s.id) return;
  const key = `${s.id}`;
  sessionMeta.set(key, { dir: s.directory || null, parent: s.parentID || null });
  if (sessionsSeen.has(key)) return;
  sessionsSeen.add(key);
  write({
    t: "session",
    ts: new Date().toISOString(),
    session: s.id,
    parent_session: s.parentID || null,
    project_root: s.directory || null,
    title: s.title || null,
  });
}

export const DwkUsage = async () => ({
  event: async ({ event }) => {
    try {
      const p = event && event.properties ? event.properties : {};
      if (event.type === "message.updated") onMessage(p.info);
      else if (event.type === "session.created" || event.type === "session.updated") onSession(p.info);
      else if (event.type === "session.compacted") onCompacted(p.sessionID);
    } catch (err) {
      logError("event", err);
    }
  },
});

export default DwkUsage;
