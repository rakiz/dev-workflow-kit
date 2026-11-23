#!/usr/bin/env python3
"""build-ops.py — per-run cost, delivery and latency for the grid2 campaign.

Writes 2026-11-16/run-ops.tsv (one row per grid run: title, bench, model,
effort, tag, status, score, delivered, cost_usd, cost_source, duration_s).
gen-charts.py and the roster read that file, so the HTML never depends on the
local opencode DB and regenerates deterministically.

Sources (keyed, read-only):
  2026-11-16/grid2-costs.tsv       title -> roll-up cost (parent + children)
  2026-11-16/grid2-run-scores.tsv  run -> status / score (delivery)
  opencode.db (sqlite3 -readonly)  for titles missing from the TSV (dated
      >= 2026-11-16) and for the duration of every run (parent session
      time_updated - time_created). Keyed by title only; no scan of message/part.

Tokens (per run) = sum over assistant messages of the parent and its delegated
children, read from message.data.tokens (keyed on session_id). Empty = no token record.

Delivered = a numeric score with status scored|retry. Cost per delivered run
for a cell = total spend over ALL its attempts / delivered runs (failed spend
is included, which is why the chart cost can exceed the mean of valid runs).
"""
import csv, json, os, re, sqlite3, sys
# --- title -> cell parser (grid2 campaign titles) ---
MODEL_KEYS=[  # (substring in title, run-scores model key); order matters
 ("deepseek-v4p1-flash-1017","1017"),("1017","1017"),
 ("claude-haiku-5-5","haiku"),("claude-sonnet-5-5","sonnet"),("claude-opus-5-5","opus"),("claude-fable-5","fable"),
 ("gpt-6-astra","astra"),("gpt-6-2-sol","gpt-6.2-sol"),("gpt-6-1-terra","terra"),("gpt-6-1-sol","sol"),
 ("gemini-4-argon","argon"),("gemini-4-carbon","carbon"),("gemini-4-hydrogen","hydrogen"),("gemini-3-8-flash","gem38"),
 ("glm-5-3-flash","glm"),("deepseek-v4-1-flash","dsflash"),("deepseek-v4p1-flash","dsflash"),
 ("minimax-m3p1-flash","minimax"),("qwen3p8","qwen"),("muse-spark","muse"),("kimi-k3p1","kimi"),
 ("mai-code-2-flash","mai-code-2-flash"),("mai-code-2","mai-code-2"),
]
EFFORTS={"low","medium","high","xhigh"}
def parse(title):
    m=re.match(r"eval-(\d{4}-\d{2}-\d{2})-(.+)$", title)
    if not m: return None
    date, rest = m.group(1), m.group(2)
    toks=rest.split("-")
    # bench code
    # RG4 (IV4 / IV2-RG4) and DR-v3 (T4V3) are separate fixtures: their own bench codes,
    # never merged with RG3 (I2) or DR2 (T4V2).
    if rest.startswith("IV4-") or rest.startswith("IV2-RG4-"): bench="I2-RG4"
    elif rest.startswith("T4V3-"): bench="DR-v3"
    elif rest.startswith("T1-"): bench="O"
    elif rest.startswith("T3-"): bench="IR"
    elif rest.startswith("T4V2-"): bench="DR2"
    elif rest.startswith("IV2-") or rest.startswith("IV2-RG3-"): bench="I2"
    elif rest.startswith("D-D1-") or rest.startswith("D-"): bench="D"
    else: return None   # T2, T4(v1), IV4, T4V3, unknown -> not a grid bench
    model=None
    for sub,key in MODEL_KEYS:
        if sub in rest: model=key; break
    if model is None: return None
    effort="default"
    for t in toks:
        if t in EFFORTS: effort=t
    # tag = last token that looks like a run tag (letter(s)+digits, optional suffix)
    tag=toks[-1] if re.fullmatch(r"[a-z]+\d+[a-z0-9]*", toks[-1]) else ""
    return {"date":date,"bench":bench,"model":model,"effort":effort,"tag":tag,"title":title}


HERE = os.path.dirname(os.path.abspath(__file__))
DAY = os.path.join(HERE, "2026-11-16")
DB = os.path.expanduser("~/.local/share/opencode/opencode.db")
OUT = os.path.join(DAY, "run-ops.tsv")

def read_costs():
    out = {}
    for line in open(os.path.join(DAY, "grid2-costs.tsv")):
        t, c = line.rstrip("\n").split("|")
        out[t] = float(c)
    return out

def db_query(sql, args=()):
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    try:
        return con.execute(sql, args).fetchall()
    finally:
        con.close()

def db_supplement_titles():
    rows = db_query("select distinct title from session where title like 'eval-2026-11-%' and parent_id is null")
    return sorted(r[0] for r in rows if parse(r[0]) and parse(r[0])["date"] >= "2026-11-16")

def db_parent(title):
    """(parent id, cost incl. children, duration_s) for a parent session keyed on title."""
    rows = db_query(
        "select p.id, p.cost, p.time_created, p.time_updated from session p "
        "where p.title = ? and p.parent_id is null order by p.time_created", (title,))
    if not rows:
        return None
    pid, pcost, tc, tu = rows[0]
    child = db_query("select coalesce(sum(cost),0) from session where parent_id = ?", (pid,))[0][0]
    return pid, pcost + child, (tu - tc) / 1000.0

TOKEN_KEYS = ("input", "cache_read", "output", "reasoning", "total")

def tokens_for(pid):
    """Token usage of a run = SUM over assistant messages of parent + delegated children.
    Keyed on session_id (message index); never a scan of message/part."""
    sids = [pid] + [r[0] for r in db_query("select id from session where parent_id = ?", (pid,))]
    tot = {k: 0 for k in TOKEN_KEYS}
    seen = False
    for sid in sids:
        for (blob,) in db_query(
                "select json_extract(data,'$.tokens') from message "
                "where session_id = ? and json_extract(data,'$.role') = 'assistant'", (sid,)):
            if not blob:
                continue
            t = json.loads(blob)
            seen = True
            tot["input"] += t.get("input", 0)
            tot["cache_read"] += (t.get("cache") or {}).get("read", 0)
            tot["output"] += t.get("output", 0)
            tot["reasoning"] += t.get("reasoning", 0)
            tot["total"] += t.get("total", 0)
    return tot if seen else None

def completed(pid):
    """Etape 0 completed-run criterion: an assistant message with finish = stop."""
    return db_query("select count(*) from message where session_id = ? and data like ?",
                    (pid, '%"finish":"stop"%'))[0][0] > 0

def read_runs():
    runs = list(csv.DictReader(open(os.path.join(DAY, "grid2-run-scores.tsv")), delimiter="\t"))
    idx = {}
    for r in runs:
        idx.setdefault((r["bench"], r["model"], r["effort"], r["tag"]), []).append(r)
    return idx

def status_for(idx, p, pid=None):
    cands = idx.get((p["bench"], p["model"], p["effort"], p["tag"]), [])
    if not cands:
        # no scoring row: delivery = completed run (finish = stop); score unknown
        if pid is not None and completed(pid):
            return "completed", None
        return "not-completed", None
    # prefer a valid run when several rows share the key
    for r in cands:
        if r["status"] in ("scored", "retry") and r["score"].strip():
            return r["status"], float(r["score"])
    return cands[0]["status"], None

def main():
    costs = read_costs()
    idx = read_runs()
    rows = []
    for title, cost in sorted(costs.items()):
        p = parse(title)
        if not p:
            continue                       # retired / out-of-grid models (see README note)
        dur = db_parent(title)
        st, sc = status_for(idx, p, dur[0] if dur else None)
        tok = tokens_for(dur[0]) if dur else None
        rows.append(dict(p, cost=cost, cost_source="tsv",
                         duration_s=dur[2] if dur else "", status=st, score=sc, tok=tok))
    for title in db_supplement_titles():
        if title in costs:
            continue
        p = parse(title)
        if not p:
            continue                       # RG4 (IV4) / DR-v3 (T4V3) / retired benches
        d = db_parent(title)
        if not d:
            continue
        st, sc = status_for(idx, p, d[0])
        tok = tokens_for(d[0])
        rows.append(dict(p, cost=d[1], cost_source="db", duration_s=d[2], status=st, score=sc, tok=tok))
    rows.sort(key=lambda r: (r["bench"], r["model"], r["effort"], r["date"], r["tag"], r["title"]))
    with open(OUT, "w", newline="") as f:
        w = csv.writer(f, delimiter="\t", lineterminator="\n")
        w.writerow(["title","date","bench","model","effort","tag","status","score","delivered","cost_usd","cost_source","duration_s",
                    "tok_input","tok_cache_read","tok_output","tok_reasoning","tok_total"])
        for r in rows:
            delivered = int((r["score"] is not None and r["status"] in ("scored", "retry"))
                            or r["status"] == "completed")
            w.writerow([r["title"], r["date"], r["bench"], r["model"], r["effort"], r["tag"],
                        r["status"], "" if r["score"] is None else r["score"], delivered,
                        f"{r['cost']:.4f}", r["cost_source"],
                        "" if r["duration_s"] == "" else f"{r['duration_s']:.0f}"]
                       + ([r["tok"][k] for k in TOKEN_KEYS] if r.get("tok") else ["", "", "", "", ""]))
    print(f"wrote {OUT}: {len(rows)} runs")

if __name__ == "__main__":
    main()
