#!/usr/bin/env python3
"""run-campaign.py — generic eval-campaign driver (stdlib only).

Consolidates the /tmp driver patterns (driver*.py) into one fail-closed tool.

    python3 run-campaign.py <campaign.json> --self-check   # validate, no launch
    python3 run-campaign.py <campaign.json>                # launch

Campaign file (JSON, unknown keys are rejected):
  {
    "id": "smoke-o-haiku-2026-11-20",        # [a-z0-9-], used in titles/tags
    "date": "2026-11-20",                    # MUST equal today (runners title with `date +%F`)
    "budget_usd": 0.10,                      # hard stop on campaign-relative spend
    "parallelism": 1,
    "timeout_default": 900,                  # wall-clock seconds per arm
    "benches": {                             # BENCH -> runner + title token (data, not code)
      "O": {"runner": "run-eval-v5.sh", "task": "T1", "title_token": "T1"}
    },
    "arms": [
      {"bench": "O", "model": "github-copilot/claude-haiku-5.5",
       "variant": "", "cap": 0.10, "attempts": 1,      # attempts optional (default 2)
       "timeout": 900}                                 # optional per-arm override
    ]
  }

Outputs, next to the campaign file (stem = file name without .json):
  <stem>.status.txt   one line per arm attempt: time, job, arm, status, campaign spend
  <stem>.logs/        one runner log per attempt

Behaviour (fail closed):
  * preflight: sqlite3 on PATH, opencode DB readable, session.cost/parent_id/title/
    time_created present; every runner exists in this directory.
  * spend = SUM(cost) of sessions created since this campaign started whose title
    matches eval-<date>% or panel-%, plus their children (parent_id roll-up).
    The campaign date is the key; panel-% sessions carry no date, so the start
    timestamp scopes them (unscoped panel-% = $17+ of history).
  * admission: an arm launches only if spend + reserved + cap <= budget_usd.
    Once refused, every remaining job is recorded as SKIP-STOPPED.
  * the first attempt runs alone; it must produce a session with the exact
    expected title AND a date-pattern match, else the campaign aborts.
  * per arm: cost poller on the exact title (driver kills at 2x cap), wall-clock
    watchdog (arm timeout or timeout_default). The runners also enforce both.
  * final-report capture is done by the runners themselves (run-eval-v4/v5.sh).
"""
import argparse, json, os, re, shutil, signal, sqlite3, subprocess, sys, threading, time
from concurrent.futures import ThreadPoolExecutor

EVALS = os.path.dirname(os.path.abspath(__file__))
DB = os.path.expanduser("~/.local/share/opencode/opencode.db")
POLL_SECS = 30
KILL_GRACE = 5
TOP_KEYS = {"id", "date", "budget_usd", "parallelism", "timeout_default", "benches", "arms"}
BENCH_KEYS = {"runner", "task", "title_token"}
ARM_KEYS = {"bench", "model", "variant", "cap", "attempts", "timeout"}
RUNNERS = {"run-eval-v4.sh", "run-eval-v5.sh"}
ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
MODEL_RE = re.compile(r"^[A-Za-z0-9_./-]+$")
VARIANT_RE = re.compile(r"^[A-Za-z0-9._-]*$")
TOKEN_RE = re.compile(r"^[A-Za-z0-9-]+$")

LOCK = threading.Lock()
STATE = {"stop": False, "reserved": 0.0}

SPEND_Q = (
    "SELECT COALESCE(SUM(cost),0) FROM session WHERE time_created >= ? AND ("
    " title LIKE ? OR title LIKE 'panel-%' OR parent_id IN ("
    "  SELECT id FROM session WHERE time_created >= ? AND (title LIKE ? OR title LIKE 'panel-%')))"
)
EXACT_Q = (
    "SELECT COALESCE(SUM(cost),0) FROM session WHERE title = ? OR parent_id IN "
    "(SELECT id FROM session WHERE title = ?)"
)


class CampaignError(Exception):
    pass


def db_query(q, args=()):
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True, timeout=30)
    try:
        return con.execute(q, args).fetchall()
    finally:
        con.close()


def campaign_spend(spec, t0):
    eval_pat = f"eval-{spec['date']}%"
    return float(db_query(SPEND_Q, (t0, eval_pat, t0, eval_pat))[0][0])


def exact_spend(title):
    return float(db_query(EXACT_Q, (title, title))[0][0])


def title_for(spec, arm, attempt):
    bench = spec["benches"][arm["bench"]]
    tag = f"{spec['id']}-a{attempt}"
    model = re.sub(r"[/. ]", "-", arm["model"])
    variant = arm.get("variant", "")
    tok = "-".join(p for p in [model, variant, tag] if p)
    return f"eval-{spec['date']}-{bench['title_token']}-{tok}", tag


def fail(msg):
    raise CampaignError(msg)


def load_spec(path):
    try:
        raw = json.load(open(path))
    except (OSError, ValueError) as e:
        fail(f"cannot read campaign file {path}: {e}")
    if not isinstance(raw, dict):
        fail("campaign file must be a JSON object")
    unknown = set(raw) - TOP_KEYS
    if unknown:
        fail(f"unknown top-level keys: {sorted(unknown)}")
    missing = {"id", "date", "budget_usd", "parallelism", "timeout_default", "benches", "arms"} - set(raw)
    if missing:
        fail(f"missing keys: {sorted(missing)}")
    if not ID_RE.match(str(raw["id"])):
        fail(f"id must match {ID_RE.pattern}: {raw['id']!r}")
    if not DATE_RE.match(str(raw["date"])):
        fail(f"date must be YYYY-MM-DD: {raw['date']!r}")
    today = time.strftime("%Y-%m-%d")
    if raw["date"] != today:
        fail(f"date {raw['date']} != today {today}: runners title with today's date, the campaign key would not match")
    if not isinstance(raw["budget_usd"], (int, float)) or raw["budget_usd"] <= 0:
        fail("budget_usd must be a positive number")
    if not isinstance(raw["parallelism"], int) or raw["parallelism"] < 1:
        fail("parallelism must be an integer >= 1")
    if not isinstance(raw["timeout_default"], int) or raw["timeout_default"] < 1:
        fail("timeout_default must be an integer >= 1 (seconds)")
    benches = raw["benches"]
    if not isinstance(benches, dict) or not benches:
        fail("benches must be a non-empty object")
    for name, b in benches.items():
        if not isinstance(b, dict) or set(b) != BENCH_KEYS:
            fail(f"bench {name}: must have exactly {sorted(BENCH_KEYS)}")
        if b["runner"] not in RUNNERS:
            fail(f"bench {name}: runner must be one of {sorted(RUNNERS)}")
        if not os.path.isfile(os.path.join(EVALS, b["runner"])):
            fail(f"bench {name}: runner file missing: {b['runner']}")
        if not TOKEN_RE.match(b["title_token"]) or not TOKEN_RE.match(b["task"]):
            fail(f"bench {name}: task/title_token must match {TOKEN_RE.pattern}")
    arms = raw["arms"]
    if not isinstance(arms, list) or not arms:
        fail("arms must be a non-empty list")
    seen = set()
    for i, a in enumerate(arms):
        if not isinstance(a, dict) or not set(a) <= ARM_KEYS or not {"bench", "model", "cap"} <= set(a):
            fail(f"arm {i}: needs bench/model/cap, optional variant/attempts/timeout only")
        if a["bench"] not in benches:
            fail(f"arm {i}: unknown bench {a['bench']!r}")
        if not MODEL_RE.match(a["model"]):
            fail(f"arm {i}: model must match {MODEL_RE.pattern}")
        if not VARIANT_RE.match(a.get("variant", "")):
            fail(f"arm {i}: variant must match {VARIANT_RE.pattern}")
        if not isinstance(a["cap"], (int, float)) or a["cap"] <= 0:
            fail(f"arm {i}: cap must be a positive number (USD)")
        if a["cap"] > raw["budget_usd"]:
            fail(f"arm {i}: cap {a['cap']} exceeds budget_usd {raw['budget_usd']}")
        att = a.get("attempts", 2)
        if not isinstance(att, int) or not 1 <= att <= 5:
            fail(f"arm {i}: attempts must be an integer 1..5 (default 2)")
        if "timeout" in a and (not isinstance(a["timeout"], int) or a["timeout"] < 1):
            fail(f"arm {i}: timeout must be an integer >= 1 (seconds)")
        key = (a["bench"], a["model"], a.get("variant", ""))
        if key in seen:
            fail(f"arm {i}: duplicate (bench, model, variant) {key}")
        seen.add(key)
    return raw


def preflight_db():
    if shutil.which("sqlite3") is None:
        fail("preflight: sqlite3 not on PATH")
    if not os.path.isfile(DB):
        fail(f"preflight: opencode DB missing at {DB}")
    try:
        cols = {r[1] for r in db_query("PRAGMA table_info(session)")}
    except sqlite3.Error as e:
        fail(f"preflight: cannot read session table: {e}")
    need = {"cost", "parent_id", "title", "time_created", "id"}
    if not need <= cols:
        fail(f"preflight: session table lacks columns {sorted(need - cols)}")


def build_jobs(spec):
    jobs = []
    top = max(a.get("attempts", 2) for a in spec["arms"])
    for k in range(1, top + 1):
        for a in spec["arms"]:
            if k <= a.get("attempts", 2):
                jobs.append((a, k))
    return [dict(idx=i + 1, arm=a, attempt=k) for i, (a, k) in enumerate(jobs)]


def arm_label(a, k):
    return f"{a['bench']}/{a['model']}/{a.get('variant') or '-'}/a{k}"


def status_line(path, job, status, spend):
    line = (f"{time.strftime('%H:%M:%S')} {job['idx']:03d} {arm_label(job['arm'], job['attempt'])} "
            f"{status} spent={spend:.4f}")
    with LOCK:
        with open(path, "a") as f:
            f.write(line + "\n")
    print(line, flush=True)


def run_arm(spec, job, t0, status_path, logdir):
    arm, k = job["arm"], job["attempt"]
    title, tag = title_for(spec, arm, k)
    cap = float(arm["cap"])
    timeout = int(arm.get("timeout", spec["timeout_default"]))
    bench = spec["benches"][arm["bench"]]
    cmd = [os.path.join(EVALS, bench["runner"]), bench["task"], arm["model"], arm.get("variant", ""), tag]
    env = dict(os.environ, EVAL_ARM_CAP=str(cap), EVAL_TIMEOUT_SECS=str(timeout))
    # admission (hard stop): reserve the cap, refuse if the budget cannot cover it
    with LOCK:
        if STATE["stop"]:
            admitted, reason = False, "SKIP-STOPPED"
        else:
            spent = campaign_spend(spec, t0)
            if spent + STATE["reserved"] + cap > float(spec["budget_usd"]):
                STATE["stop"] = True
                admitted, reason = False, "STOP-BUDGET"
            else:
                STATE["reserved"] += cap
                admitted, reason = True, None
    if not admitted:
        status_line(status_path, job, reason, campaign_spend(spec, t0) if reason == "STOP-BUDGET" else 0.0)
        return reason
    flags = {}
    done = threading.Event()
    logpath = os.path.join(logdir, f"{job['idx']:03d}-{title}.log")
    with open(logpath, "w") as logf:
        proc = subprocess.Popen(cmd, cwd=EVALS, env=env, stdout=logf, stderr=subprocess.STDOUT,
                                start_new_session=True)

    def kill_group(name):
        flags[name] = True
        for sig in (signal.SIGTERM, signal.SIGKILL):
            try:
                os.killpg(proc.pid, sig)
            except ProcessLookupError:
                return
            time.sleep(KILL_GRACE)

    def poller():
        while not done.wait(POLL_SECS):
            try:
                c = exact_spend(title)
            except sqlite3.Error:
                continue
            if c > 2 * cap:
                kill_group("costcap-driver")
                return

    threading.Thread(target=poller, daemon=True).start()
    try:
        rc = proc.wait(timeout=timeout + 300)  # runner watchdog fires first; this is the backstop
    except subprocess.TimeoutExpired:
        kill_group("timeout-driver")
        rc = proc.wait()
    finally:
        done.set()
        with LOCK:
            STATE["reserved"] -= cap
    if flags.get("costcap-driver"):
        status = "costcap-driver"
    elif flags.get("timeout-driver"):
        status = "timeout-driver"
    elif rc == 0:
        status = "ok"
    elif rc == 125:
        status = "costcap"
    elif rc == 124:
        status = "timeout"
    else:
        status = f"rc{rc}"
    status_line(status_path, job, status, campaign_spend(spec, t0))
    return status


def self_check(spec, jobs):
    print(f"SELF-CHECK campaign={spec['id']} date={spec['date']} budget_usd={spec['budget_usd']:.2f} "
          f"parallelism={spec['parallelism']} jobs={len(jobs)}")
    for name in sorted(spec["benches"]):
        b = spec["benches"][name]
        print(f"  bench {name}: runner={b['runner']} task={b['task']} title_token={b['title_token']} (exists)")
    for j in jobs:
        title, _ = title_for(spec, j["arm"], j["attempt"])
        print(f"  job {j['idx']:03d} {arm_label(j['arm'], j['attempt'])} cap={j['arm']['cap']:.2f} title={title}")
    preflight_db()
    print("  db: sqlite3 on PATH, DB readable, session cost/parent_id/title/time_created present")
    print("SELF-CHECK OK (no launch)")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("campaign")
    ap.add_argument("--self-check", action="store_true", help="validate the campaign + runners + DB; do not launch")
    args = ap.parse_args()
    try:
        spec = load_spec(args.campaign)
        jobs = build_jobs(spec)
        if args.self_check:
            self_check(spec, jobs)
            return 0
        preflight_db()
        stem = os.path.splitext(os.path.abspath(args.campaign))[0]
        status_path = stem + ".status.txt"
        logdir = stem + ".logs"
        os.makedirs(logdir, exist_ok=True)
        t0 = int(time.time() * 1000)
        with open(status_path, "a") as f:
            f.write(f"# campaign {spec['id']} date={spec['date']} budget_usd={spec['budget_usd']:.2f} "
                    f"start_ms={t0} jobs={len(jobs)}\n")
        # first attempt alone: it must produce the exact title AND the date-pattern sessions
        first = jobs[0]
        run_arm(spec, first, t0, status_path, logdir)
        title0, _ = title_for(spec, first["arm"], first["attempt"])
        n_exact = db_query("SELECT COUNT(*) FROM session WHERE time_created >= ? AND title = ?", (t0, title0))[0][0]
        n_pat = db_query("SELECT COUNT(*) FROM session WHERE time_created >= ? AND title LIKE ?",
                         (t0, f"eval-{spec['date']}%"))[0][0]
        if n_exact == 0 or n_pat == 0:
            with LOCK:
                STATE["stop"] = True
            status_line(status_path, {"idx": 0, "arm": {"bench": "-", "model": "-", "variant": ""}, "attempt": 0},
                        f"ABORT-no-session(exact={n_exact},pattern={n_pat})", campaign_spend(spec, t0))
        else:
            with ThreadPoolExecutor(max_workers=spec["parallelism"]) as ex:
                list(ex.map(lambda j: run_arm(spec, j, t0, status_path, logdir), jobs[1:]))
        final = campaign_spend(spec, t0)
        with LOCK:
            print(f"CAMPAIGN DONE id={spec['id']} spent={final:.4f} budget_usd={spec['budget_usd']:.2f}", flush=True)
        with open(status_path, "a") as f:
            f.write(f"# done spent={final:.4f} budget_usd={spec['budget_usd']:.2f}\n")
        return 0
    except CampaignError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
