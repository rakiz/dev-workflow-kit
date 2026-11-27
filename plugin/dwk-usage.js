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
import { appendFileSync, mkdirSync, readFileSync, existsSync } from "node:fs";
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

// Ids already recorded in this process: a completion event can repeat.
const recorded = new Set();
// Sessions already recorded in this process.
const sessionsSeen = new Set();

function onMessage(info) {
  if (!info || info.role !== "assistant") return;
  if (!info.time || !info.time.completed) return; // not finished yet (A3)
  if (info.error) return; // a failed call is not spend (it returned no answer)
  if (recorded.has(info.id)) return;
  const t = info.tokens || {};
  const c = t.cache || {};
  // A completed turn with no tokens and no cost is routing noise (e.g. a command
  // dispatch), not spend: skip the message. Its session record is still written.
  const spent = (t.input || 0) + (t.output || 0) + (t.reasoning || 0) + (c.read || 0) + (c.write || 0);
  if (spent === 0 && !(typeof info.cost === "number" && info.cost > 0)) return;
  recorded.add(info.id);
  write({
    t: "msg",
    ts: new Date(info.time.completed).toISOString(),
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
}

function onSession(s) {
  if (!s || !s.id) return;
  const key = `${s.id}`;
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
    } catch (err) {
      logError("event", err);
    }
  },
});

export default DwkUsage;
