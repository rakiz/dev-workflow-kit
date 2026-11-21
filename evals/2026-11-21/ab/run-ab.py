#!/usr/bin/env python3
"""Étape 4 A/B runner (AB-SPEC v2 §2, §5). Scripted; no model in the loop.
    run-ab.py <arm A|B|C> [T1..T5 ...]   runs the arm's cells sequentially (private cells dir)
Session titles ab-<arm>-t<k>[-step]; spend = DB roll-up by title prefix (+ token estimate for misc models).
Per-arm poller kills at 2x cap; campaign stops above $25; 30-min wall per cell (watchdog -> DNF)."""
import os, re, shutil, sqlite3, subprocess, sys, time, json
HERE = os.path.dirname(os.path.abspath(__file__))
KEYS = os.environ.get("AB_KEYS", os.path.join(HERE, "..", "..", "..", "..", "evals-keys", "ab-2026-11-21"))
KEYS = os.path.realpath(KEYS)
TASKS = os.path.join(HERE, "tasks")
CELLS = os.path.join(KEYS, "cells")
DB = os.path.expanduser("~/.local/share/opencode/opencode.db")
CAP = {"A": 3.0, "B": 5.0, "C": 7.0}
CAMPAIGN_CAP = 25.0
CELL_WALL = 30 * 60
POLL = 15
SONNET = "github-copilot/claude-sonnet-5.5"
LOG = os.path.join(HERE, "RUNLOG.tsv")
MISC_LOW = (0.22, 0.66, 0.007)   # plugin catalog, deepseek-v4p1-flash ($/1M in, out, cache-read)

def q(sql, args=()):
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True, timeout=30)
    try: return con.execute(sql, args).fetchall()
    finally: con.close()

def db_cost(pattern):
    return float(q("SELECT COALESCE(SUM(cost),0) FROM session WHERE title LIKE ? OR parent_id IN "
                   "(SELECT id FROM session WHERE title LIKE ?)", (pattern, pattern))[0][0])

def misc_est(pattern):
    """Token-priced estimate for ai-gateway-misc (opencode records cost 0 for custom providers)."""
    tot = 0.0
    for (data,) in q("SELECT m.data FROM message m JOIN session s ON m.session_id = s.id "
                     "WHERE s.title LIKE ? AND json_extract(m.data,'$.role')='assistant' "
                     "AND json_extract(m.data,'$.providerID')='ai-gateway-misc'", (pattern,)):
        j = json.loads(data); t = j.get("tokens") or {}; c = t.get("cache") or {}
        tot += ((t.get("input",0)*MISC_LOW[0]) + ((t.get("output",0)+t.get("reasoning",0))*MISC_LOW[1]) + c.get("read",0)*MISC_LOW[2]) / 1e6
    return tot

def adj_spend():
    """Adjudicator sessions run in their per-arm DBs (sandboxed, holdout-arm): sum them into the campaign roll-up."""
    tb = os.path.realpath(os.environ.get("TMPDIR", "/tmp")).rstrip("/")
    root = os.path.join(tb, "holdout-xdg")
    total = 0.0
    if os.path.isdir(root):
        for t in os.listdir(root):
            if not t.startswith("ab-ADJ-"): continue
            path = os.path.join(root, t, "opencode", "opencode.db")
            if not os.path.isfile(path): continue
            con = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=30)
            try:
                total += float(con.execute("SELECT COALESCE(SUM(cost),0) FROM session").fetchone()[0])
            finally:
                con.close()
    return total

def spend(pattern):
    extra = adj_spend() if pattern == "ab-%" else 0.0
    return db_cost(pattern) + misc_est(pattern) + extra

def log(row):
    new = not os.path.exists(LOG)
    with open(LOG, "a") as fh:
        if new: fh.write("time\tarm\ttask\tsession\tstatus\trc\tseconds\tnote\n")
        fh.write("\t".join(str(x) for x in row) + "\n")

def session_text(title):
    rows = q("SELECT m.id FROM message m JOIN session s ON m.session_id=s.id WHERE s.title=? "
             "AND json_extract(m.data,'$.role')='assistant' ORDER BY m.time_created DESC LIMIT 1", (title,))
    if not rows: return ""
    parts = q("SELECT json_extract(data,'$.text') FROM part WHERE message_id=? AND json_extract(data,'$.type')='text' ORDER BY id", (rows[0][0],))
    return "\n".join(p[0] or "" for p in parts)

class Route:
    def __init__(self, arm, task, cell):
        self.arm, self.task, self.cell = arm, task, cell
        self.deadline = time.time() + CELL_WALL
        self.sessions = 0; self.status = "ok"; self.note = []; self.t0 = time.time()
        self.pattern = f"ab-{arm}-t{task}%"
        self.last_text = ""

    def stopped(self, reason):
        self.status = self.status if self.status != "ok" else reason
        self.note.append(reason)
        return None

    def run(self, step, cwd, prompt, agent=None, model=None, variant=None, max_sessions=None):
        if max_sessions and self.sessions >= max_sessions: return self.stopped("TRUNCATED:session-cap")
        if spend(f"ab-%") >= CAMPAIGN_CAP: return self.stopped("TRUNCATED:campaign-cap")
        if spend(f"ab-{self.arm}-%") >= CAP[self.arm]: return self.stopped("TRUNCATED:arm-cap")
        self.sessions += 1
        title = f"ab-{self.arm}-t{self.task}" + ("" if step == "impl" else f"-{step}")
        cmd = ["opencode", "run", "--dir", cwd, "--title", title, "--auto"]
        if agent: cmd += ["--agent", agent]
        if model: cmd += ["--model", model]
        if variant: cmd += ["--variant", variant]
        cmd.append(prompt)
        logf = os.path.join(self.cell, f"session-{step}.log")
        t = time.time(); status = "ok"
        with open(logf, "w") as lf:
            p = subprocess.Popen(cmd, stdout=lf, stderr=subprocess.STDOUT, start_new_session=True)
            while p.poll() is None:
                time.sleep(POLL)
                if time.time() > self.deadline: status = "DNF:watchdog"; break
                if spend(self.pattern) > 2 * CAP[self.arm] or spend(f"ab-{self.arm}-%") > 2 * CAP[self.arm]:
                    status = "TRUNCATED:costcap-kill"; break
            if p.poll() is None:
                try: os.killpg(p.pid, 15)
                except ProcessLookupError: pass
                time.sleep(3)
            rc = p.poll()
        if status == "ok" and rc not in (0, None): status = f"DNF:rc{rc}"
        log([time.strftime("%H:%M:%S"), self.arm, f"T{self.task}", title, status, rc, int(time.time()-t), step])
        if status != "ok":
            self.status = status; self.note.append(status)
            return None
        self.last_text = session_text(title)
        return self.last_text

PROD = ("Work alone; no subagents. Read TASK.md in this directory and implement it completely in this directory. "
        "Then write REPORT.md summarizing the changes and the executed test results. Finish with a short final answer.")
REVIEW = ("Review the work in this directory against TASK.md. Run `python3 -m unittest` in this directory. "
          "Write REVIEW.md with your findings. Your final line must be exactly `VERDICT: major` or `VERDICT: minor`.")
FIX = ("Read TASK.md and REVIEW.md in this directory. Fix the findings with the smallest change, keep the test suite green, "
       "and update REPORT.md. Work alone. Finish with a short final answer.")
DESIGN = ("Work alone. Read TASK.md. Write DESIGN-prune.md (at most one page) with the four headed sections named in TASK.md. "
          "Finish with a short final answer.")

def verdict(text):
    lines = [l.strip() for l in (text or "").splitlines() if l.strip()]
    if lines:
        m = re.fullmatch(r"VERDICT:\s*(major|minor)", lines[-1], re.I)
        if m: return m.group(1).lower()
    return None   # absent/malformed: treated as minor by the route (ledgered)

def ledger(line):
    with open(os.path.join(HERE, "DEVIATIONS.md"), "a") as fh: fh.write(line + "\n")

def code_route(r, cell, task):
    """AB-SPEC §2 arm A code route (T1/T3/T4, and the T5 implementation stage)."""
    t = r.run("impl", cell, PROD, agent="cheap-code", max_sessions=(8 if task == 5 else 5))
    if t is None: return
    esc = "ESCALATE-CANDIDATE" in t
    cap = 8 if task == 5 else 5
    v1 = verdict(r.run("review1", cell, REVIEW, agent="cheap-review", max_sessions=cap))
    if v1 is None and r.status == "ok": ledger(f"A T{task} review1 VERDICT absent -> treated as minor")
    if esc or v1 == "major":
        if r.run("fix1", cell, FIX, agent="strong-code", max_sessions=cap) is None: return
        v2 = verdict(r.run("review2", cell, REVIEW, agent="strong-review", max_sessions=cap))
        if v2 is None and r.status == "ok": ledger(f"A T{task} review2 VERDICT absent -> treated as major (doubt)")
        if v2 == "major" or v2 is None:
            r.run("fix2", cell, FIX, agent="strong-code-alternative", max_sessions=cap)
    else:
        r.run("fix1", cell, FIX, agent="cheap-code", max_sessions=cap)

def arm_a(r, cell, task):
    if task in (1, 3, 4):
        code_route(r, cell, task)
    elif task == 2:
        if r.run("impl", cell, PROD, agent="cheap-mech", max_sessions=3) is None: return
        v = verdict(r.run("review1", cell, REVIEW, agent="cheap-review", max_sessions=3))
        if v is None and r.status == "ok": ledger("A T2 review1 VERDICT absent -> treated as minor")
        r.run("fix1", cell, FIX, agent="cheap-mech", max_sessions=3)
    elif task == 5:
        if r.run("design", cell, DESIGN, agent="cheap-design", max_sessions=8) is None: return
        if r.run("design-review", cell, REVIEW, agent="cheap-design-review", max_sessions=8) is None: return
        if r.run("design-fix", cell, FIX, agent="cheap-design", max_sessions=8) is None: return
        code_route(r, cell, task)

def arm_b(r, cell, task):
    r.run("impl", cell, PROD, model=SONNET, variant="high", max_sessions=1)

def arm_c(r, cell, task):
    if r.run("impl", cell, PROD, model=SONNET, variant="high", max_sessions=3) is None: return
    v = verdict(r.run("review1", cell, REVIEW, model=SONNET, variant="medium", max_sessions=3))
    if v is None and r.status == "ok": ledger(f"C T{task} review VERDICT absent/malformed -> treated as minor (fallback)")
    r.run("fix1", cell, FIX, model=SONNET, variant="high", max_sessions=3)

def run_cell(arm, task, rerun=False):
    cell = os.path.join(CELLS, f"{arm}-T{task}" + ("-rr" if rerun else ""))
    if os.path.exists(cell): shutil.rmtree(cell)
    os.makedirs(os.path.dirname(cell), exist_ok=True)
    shutil.copytree(os.path.join(TASKS, f"T{task}", "start"), cell, ignore=shutil.ignore_patterns("__pycache__"))
    r = Route(arm, task, cell)
    {"A": arm_a, "B": arm_b, "C": arm_c}[arm](r, cell, task)
    text = r.last_text
    with open(os.path.join(cell, "REPORT.md"), "w") as fh:
        fh.write(text if text else f"NO REPORT ({r.status})\n")
    delivered = r.status == "ok" and os.path.isfile(os.path.join(cell, "REPORT.md")) and bool(text)
    return r.status, delivered, r

def main(argv):
    arm = argv[0]
    if not os.path.exists(os.path.join(HERE, "DEVIATIONS.md")):
        ledger("# DEVIATIONS (AB-SPEC §6 m3)")
        ledger("- BUILD: the start repos, required tests and mutant were built by the orchestrator session (the spec's builder role), not by a cheap-code instance. Recorded per the owner's explicit BUILDER authorisation.")
        ledger("- T2 arm A: the spec names `one fix` without naming the agent; the fix uses the producer agent (cheap-mech).")
        ledger("- grok-4.7 (spec m4 replacement) is absent from the catalog (grok-4.6 exists); only used if a neon/qwen replacement is needed.")
    tasks = [int(a.lstrip("T")) for a in argv[1:]] or [1, 2, 3, 4, 5]
    for task in tasks:
        status, delivered, r = run_cell(arm, task)
        if status.startswith("DNF") and spend("ab-%") < CAMPAIGN_CAP - 2 * CAP[arm]:
            ledger(f"{arm} T{task} DNF ({status}) -> one re-run from the reserve")
            status, delivered, r = run_cell(arm, task, rerun=True)
        log([time.strftime("%H:%M:%S"), arm, f"T{task}", "CELL", status, "", int(time.time()-r.t0), f"delivered={delivered}"])
        print(f"{arm} T{task}: status={status} delivered={delivered} spend_arm={spend(f'ab-{arm}-%'):.4f}", flush=True)
    print("ARM DONE", arm, flush=True)

if __name__ == "__main__":
    main(sys.argv[1:])
