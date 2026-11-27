#!/usr/bin/env node
// dwk/stats.mjs — reads the dwk-usage JSONL and renders usage summaries.
//
//   node stats.mjs [today|week|month|range FROM TO] [--project PATH]
//                  [--by model|agent|task] [--prune] [--models PATH] [--data DIR]
//   node stats.mjs live            (re-renders the month table every 5 s)
//
// Cost rule (plan §3.8, D-A22): the provider's reported cost is used when it
// is > 0. A 0 cost is estimated from tokens x the models.json "prices" rates and
// labelled "est."; a model with no rate prints "$?" — never a silent 0.
// --prune deletes monthly files older than 13 months (UTC), nothing else.
//
// tok/s = generated tokens (out + reasoning) / span seconds, where span =
// ts (completed) - start_ts (created), summed over the group's messages.
// Messages without start_ts (older records) or with span <= 0 are left out of
// tok/s only; they still count everywhere else.
//
// --by task attributes a message to a task through the project ledger: the
// session's project_root -> its INPROGRESS.md (workflow.inprogress from
// dev-workflow.json when set) -> the dispatch line whose task_id= equals the
// message's session id -> that line's task/step field. Unmatched: "-".
import { readFileSync, readdirSync, statSync, unlinkSync, existsSync, mkdirSync } from "node:fs";
import { homedir } from "node:os";
import { join, dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const args = process.argv.slice(2);
const flag = (name) => args.includes(name);
const opt = (name, dflt) => { const i = args.indexOf(name); return i >= 0 && args[i + 1] !== undefined ? args[i + 1] : dflt; };

const DATA_HOME = process.env.XDG_DATA_HOME || join(homedir(), ".local", "share");
const DATA_DIR = resolve(opt("--data", join(DATA_HOME, "dev-workflow-kit", "usage")));
const HERE = dirname(fileURLToPath(import.meta.url));
const MODELS_PATH = resolve(opt("--models", join(HERE, "..", "roster", "models.json")));
const RETAIN_MONTHS = 13;

// ---- prune -----------------------------------------------------------------
function monthsBetween(a, b) { return (b.getUTCFullYear() - a.getUTCFullYear()) * 12 + (b.getUTCMonth() - a.getUTCMonth()); }

function prune(now = new Date()) {
  if (!existsSync(DATA_DIR)) { console.log("nothing to prune (no usage directory)"); return 0; }
  let removed = 0;
  for (const f of readdirSync(DATA_DIR)) {
    const m = /^(\d{4})-(\d{2})\.jsonl$/.exec(f);
    if (!m) continue;
    const fileMonth = new Date(Date.UTC(+m[1], +m[2] - 1, 1));
    if (monthsBetween(fileMonth, now) >= RETAIN_MONTHS) {
      unlinkSync(join(DATA_DIR, f));
      removed++;
      console.log(`pruned ${f} (older than ${RETAIN_MONTHS} months)`);
    }
  }
  if (!removed) console.log(`nothing to prune (keeping ${RETAIN_MONTHS} months)`);
  return removed;
}

// ---- load ------------------------------------------------------------------
function readRecords() {
  if (!existsSync(DATA_DIR)) return { msgs: [], sessions: new Map(), bad: 0 };
  const msgs = [];
  const sessions = new Map();
  let bad = 0;
  for (const f of readdirSync(DATA_DIR)) {
    if (!/^\d{4}-\d{2}\.jsonl$/.test(f)) continue;
    for (const line of readFileSync(join(DATA_DIR, f), "utf8").split("\n")) {
      if (!line.trim()) continue;
      let r;
      try { r = JSON.parse(line); } catch { bad++; continue; }
      if (r.t === "msg") msgs.push(r);
      else if (r.t === "session") sessions.set(r.session, r);
    }
  }
  // Join the parent session onto each message (the msg record cannot know it).
  for (const m of msgs) {
    const s = sessions.get(m.session);
    m.parent_session = s ? s.parent_session : null;
    m.project_root = s ? s.project_root : null;
  }
  return { msgs, sessions, bad };
}

// ---- task attribution (ledger join) ----------------------------------------
// Dispatch line: `- <attempt> | <task/step> | <role> | ... | task_id=<id> | ...`
// Returns Map(child session id -> task/step label). Read on every render (no
// cache): live mode must see ledger edits on the next tick. Fail-open: a missing
// or unreadable ledger yields an empty map; a malformed dev-workflow.json only
// drops the rename and the default INPROGRESS.md name is used.
function inprogressName(root) {
  try {
    const cfg = join(root, "dev-workflow.json");
    if (!existsSync(cfg)) return "INPROGRESS.md";
    const name = JSON.parse(readFileSync(cfg, "utf8"))?.workflow?.inprogress;
    return typeof name === "string" && name ? name : "INPROGRESS.md";
  } catch { return "INPROGRESS.md"; }
}

function ledgerOf(root) {
  const map = new Map();
  try {
    for (const line of readFileSync(join(root, inprogressName(root)), "utf8").split("\n")) {
      if (!line.startsWith("- ")) continue;
      const fields = line.slice(2).split("|").map((f) => f.trim());
      const idField = fields.find((f) => /^task_id=\S+$/.test(f));
      if (!idField || !fields[1]) continue;
      map.set(idField.slice("task_id=".length), fields[1]);
    }
  } catch { /* missing or unreadable ledger: fail open */ }
  return map;
}

// Sets m.task per message (null when no project root or no ledger line). One
// ledger read per project per call.
function attributeTasks(msgs) {
  const ledgers = new Map();
  for (const m of msgs) {
    if (!m.project_root) { m.task = null; continue; }
    if (!ledgers.has(m.project_root)) ledgers.set(m.project_root, ledgerOf(m.project_root));
    m.task = ledgers.get(m.project_root).get(m.session) || null;
  }
}

// ---- cost ------------------------------------------------------------------
function loadPrices() {
  try { return JSON.parse(readFileSync(MODELS_PATH, "utf8")).prices || {}; } catch { return {}; }
}

// costOf(msg, prices) -> { usd: number|null, est: boolean }
function costOf(m, prices) {
  if (typeof m.cost === "number" && m.cost > 0) return { usd: m.cost, est: false };
  const key = `${m.provider}/${m.model}`;
  const p = prices[key] || prices[m.model];
  const t = m.tokens || {};
  // No price: unknown, shown as "$?". Not an estimate, so est stays false.
  if (!p || p.in == null || p.out == null) return { usd: null, est: false };
  const cacheR = p.cache_read ?? 0, cacheW = p.cache_write ?? 0;
  const usd = ((t.in || 0) * p.in + (t.out || 0) * p.out + (t.reasoning || 0) * p.out
    + (t.cache_read || 0) * cacheR + (t.cache_write || 0) * cacheW) / 1e6;
  return { usd, est: true };
}

function fmtCost(c) {
  if (c.usd == null) return "$?";
  return (c.est ? "est. $" : "$") + c.usd.toFixed(4);
}

// ---- windows ---------------------------------------------------------------
function window(kind) {
  const now = new Date();
  if (kind === "today") {
    const s = new Date(Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), now.getUTCDate()));
    return [s, new Date(s.getTime() + 864e5)];
  }
  if (kind === "week") {
    const s = new Date(Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), now.getUTCDate() - 6));
    return [s, new Date(Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), now.getUTCDate() + 1))];
  }
  if (kind === "month") {
    return [new Date(Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), 1)),
            new Date(Date.UTC(now.getUTCFullYear(), now.getUTCMonth() + 1, 1))];
  }
  if (kind === "range") {
    const i = args.indexOf("range");
    const from = args[i + 1], to = args[i + 2];
    const s = new Date(`${from}T00:00:00Z`), e = new Date(`${to}T00:00:00Z`);
    if (isNaN(s) || isNaN(e)) throw new Error("range expects two dates: range YYYY-MM-DD YYYY-MM-DD");
    return [s, new Date(e.getTime() + 864e5)];
  }
  return null;
}

// ---- render ----------------------------------------------------------------
function keyOf(m, by) {
  if (by === "agent") return m.agent || "-";
  if (by === "task") return m.task || "-"; // ledger join, see attributeTasks
  return `${m.provider}/${m.model}`;
}

// The window keyword is the first non-option token; the token after a
// value-taking flag (--data, --project, --models, --by) is that flag's value and
// is skipped, so a directory named "range" or a project named "today" is never
// read as a keyword. Anything else (or no token) means the month window.
const VALUE_FLAGS = new Set(["--data", "--project", "--models", "--by"]);
const WINDOW_KEYWORDS = ["today", "week", "month", "range"];
function windowKeyword() {
  for (let i = 0; i < args.length; i++) {
    const a = args[i];
    if (VALUE_FLAGS.has(a)) { i++; continue; }
    if (a.startsWith("--")) continue;
    return WINDOW_KEYWORDS.includes(a) ? a : "month";
  }
  return "month";
}

function render() {
  const cmd = windowKeyword();
  const win = window(cmd);
  const by = opt("--by", "model");
  const project = opt("--project", null);
  const { msgs, sessions, bad } = readRecords();
  const prices = loadPrices();
  const pick = msgs.filter((m) => {
    const d = new Date(m.ts);
    if (win && (d < win[0] || d >= win[1])) return false;
    if (project && !(m.project_root || "").startsWith(resolve(project))) return false;
    return true;
  });
  if (by === "task") attributeTasks(pick);
  const groups = new Map();
  let total = 0, unpriced = 0, est = 0, noStart = 0, noRoot = 0, noLine = 0;
  for (const m of pick) {
    const k = keyOf(m, by);
    const g = groups.get(k) || { n: 0, tin: 0, tout: 0, tcache: 0, gen: 0, span: 0, usd: 0, estimated: false, unknown: false };
    const c = costOf(m, prices);
    g.n++; g.tin += m.tokens?.in || 0; g.tout += m.tokens?.out || 0;
    const startMs = m.start_ts ? Date.parse(m.start_ts) : NaN;
    const spanS = (Date.parse(m.ts) - startMs) / 1000;
    if (Number.isFinite(spanS) && spanS > 0) { g.gen += (m.tokens?.out || 0) + (m.tokens?.reasoning || 0); g.span += spanS; }
    else noStart++;
    if (by === "task" && !m.task) { if (m.project_root) noLine++; else noRoot++; }
    g.tcache += (m.tokens?.cache_read || 0) + (m.tokens?.cache_write || 0);
    if (c.usd == null) { g.unknown = true; unpriced++; } else { g.usd += c.usd; total += c.usd; }
    if (c.est) { g.estimated = true; est++; }
    groups.set(k, g);
  }
  const sessCount = new Set(pick.map((m) => m.session)).size;
  console.log(`dwk stats — ${cmd}${project ? ` project=${project}` : ""} by ${by} (usage: ${DATA_DIR})`);
  if (bad) console.log(`note: ${bad} unreadable line(s) skipped`);
  if (!pick.length) { console.log("no completed assistant messages in this window"); return; }
  console.log(`${pick.length} message(s), ${sessCount} session(s)`);
  console.log(`${"group".padEnd(44)} ${"msgs".padStart(5)} ${"in".padStart(9)} ${"out".padStart(8)} ${"cache".padStart(9)}  ${"cost".padEnd(24)} ${"tok/s".padStart(8)}`);
  for (const [k, g] of [...groups.entries()].sort((a, b) => b[1].usd - a[1].usd)) {
    const cost = g.unknown && g.usd === 0 ? "$?" : (g.unknown ? `${g.estimated ? "est. " : ""}$${g.usd.toFixed(4)} + $?` : fmtCost({ usd: g.usd, est: g.estimated }));
    const tps = g.span > 0 ? (g.gen / g.span).toFixed(1) : "-";
    console.log(`${k.slice(0, 44).padEnd(44)} ${String(g.n).padStart(5)} ${String(g.tin).padStart(9)} ${String(g.tout).padStart(8)} ${String(g.tcache).padStart(9)}  ${cost.padEnd(24)} ${tps.padStart(8)}`);
  }
  if (noStart) console.log(`note: ${noStart} message(s) left out of tok/s (no start_ts in the record, or non-positive span)`);
  if (noRoot || noLine) {
    const causes = [];
    if (noRoot) causes.push(`${noRoot} without a session project root`);
    if (noLine) causes.push(`${noLine} without a ledger line with task_id=<session id>`);
    console.log(`note: ${noRoot + noLine} message(s) unattributed (${causes.join(", ")})`);
  }
  console.log(`total: ${total > 0 ? "$" + total.toFixed(4) : "$?"}${est && total > 0 ? "  (includes est. values)" : ""}${unpriced ? `  (${unpriced} message(s) with $? — no price in models.json)` : ""}`);
}

// ---- main ------------------------------------------------------------------
if (flag("--prune")) { prune(); process.exit(0); }
if (args[0] === "live") {
  const tick = () => { process.stdout.write("\x1b[2J\x1b[H"); render(); console.log("\n(live: month view, Ctrl-C to stop)"); };
  tick(); setInterval(tick, 5000);
} else {
  render();
}
