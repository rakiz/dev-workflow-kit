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
  * ai-gateway-misc (owner ruling 11-21): opencode records cost 0 for these providers, so zero-cost assistant
    messages are priced from their token counts x the catalog per-MTok price (`opencode models ai-gateway-misc
    --verbose`, re-fetched at every --self-check and launch). Status lines show recorded and estimated_misc
    separately, the estimate labelled "(estimated)". A price drift vs the last launch (<stem>.prices.json) is
    refused unless --prices-accepted; a catalog fetch failure or an unpriced model refuses (fail closed).
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
RUNNERS = {"run-eval-v4.sh", "run-eval-v5.sh", "run-eval-v6.sh"}
ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
MODEL_RE = re.compile(r"^[A-Za-z0-9_./-]+$")
VARIANT_RE = re.compile(r"^[A-Za-z0-9._-]*$")
TOKEN_RE = re.compile(r"^[A-Za-z0-9-]+$")
# ai-gateway-misc pricing (owner ruling 11-21): opencode records cost 0 for custom providers, so these sessions are
# priced from their token counts with the catalog's per-MTok prices, re-fetched at every self-check and launch.
MISC_PREFIX = "ai-gateway-misc/"
CATALOG_CMD = ["opencode", "models", "ai-gateway-misc", "--verbose"]
PRICE_FIELDS = ("input", "output", "cache_read", "cache_write")
PRICE_STATE_SUFFIX = ".prices.json"
PRICES = {}   # "ai-gateway-misc/<id>" -> {input, output, cache_read, cache_write} USD per 1M tokens (set at launch)

LOCK = threading.Lock()
STATE = {"stop": False, "reserved": 0.0, "procs": set()}
# HOLDOUT-SPEC §5.6: per-arm opencode data dirs (XDG_DATA_HOME) live under this root
TMPBASE = os.path.realpath(os.environ.get("TMPDIR", "/tmp")).rstrip("/")
HOLDOUT_TITLE_RE = re.compile(r"-(HO2|HOD)-")

SPEND_Q = (
    "SELECT COALESCE(SUM(cost),0) FROM session WHERE time_created >= ? AND ("
    " title LIKE ? OR title LIKE 'panel-%' OR parent_id IN ("
    "  SELECT id FROM session WHERE time_created >= ? AND (title LIKE ? OR title LIKE 'panel-%')))"
)
EXACT_Q = (
    "SELECT COALESCE(SUM(cost),0) FROM session WHERE title = ? OR parent_id IN "
    "(SELECT id FROM session WHERE title = ?)"
)
# session scopes (same sets as SPEND_Q / EXACT_Q) for the misc token estimate
SCOPE_Q = (
    "SELECT id FROM session WHERE time_created >= ? AND (title LIKE ? OR title LIKE 'panel-%' OR parent_id IN ("
    " SELECT id FROM session WHERE time_created >= ? AND (title LIKE ? OR title LIKE 'panel-%')))"
)
ARM_SCOPE_Q = "SELECT id FROM session WHERE time_created >= ?"
EXACT_SCOPE_Q = "SELECT id FROM session WHERE title = ? OR parent_id IN (SELECT id FROM session WHERE title = ?)"
MISC_MSG_Q = (
    "SELECT m.data FROM message m WHERE m.session_id IN ({scope}) AND "
    "json_extract(m.data,'$.providerID')='ai-gateway-misc' AND json_extract(m.data,'$.role')='assistant'"
)


class CampaignError(Exception):
    pass


def db_query(q, args=()):
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True, timeout=30)
    try:
        return con.execute(q, args).fetchall()
    finally:
        con.close()


def arm_db(title):
    """Per-arm opencode DB for a held-out title (HOLDOUT-SPEC §5.6), else the global DB."""
    if HOLDOUT_TITLE_RE.search(title):
        return os.path.join(TMPBASE, "holdout-xdg", title, "opencode", "opencode.db")
    return DB


def db_query_at(path, q, args=()):
    con = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=30)
    try:
        return con.execute(q, args).fetchall()
    finally:
        con.close()


def per_arm_spend(spec, t0):
    """Sum cost of every per-arm held-out DB created for this campaign (sessions since t0).
    Returns (recorded, estimated_misc)."""
    root = os.path.join(TMPBASE, "holdout-xdg")
    if not os.path.isdir(root):
        return 0.0, 0.0
    recorded = estimated = 0.0
    for title in os.listdir(root):
        if not title.startswith(f"eval-{spec['date']}-"):
            continue
        path = os.path.join(root, title, "opencode", "opencode.db")
        if os.path.isfile(path):
            recorded += float(db_query_at(path, "SELECT COALESCE(SUM(cost),0) FROM session WHERE time_created >= ?", (t0,))[0][0])
            estimated += misc_estimate(path, ARM_SCOPE_Q, (t0,))
    return recorded, estimated


def count_sessions(title, t0, exact, date):
    """Sessions since t0 for the exact title (or the date pattern) in the DB the arm actually writes to.
    Fail closed: an unreadable/missing DB counts as 0, which makes the first-attempt check abort."""
    path = arm_db(title)
    if exact:
        q, args = "SELECT COUNT(*) FROM session WHERE time_created >= ? AND title = ?", (t0, title)
    else:
        q, args = "SELECT COUNT(*) FROM session WHERE time_created >= ? AND title LIKE ?", (t0, f"eval-{date}%")
    try:
        return int(db_query_at(path, q, args)[0][0])
    except sqlite3.Error:
        return 0


def safe_parts(spec, t0):
    """Status-line spend: NaN (printed as 'unreadable') instead of crashing the driver mid-campaign."""
    try:
        return spend_parts(spec, t0)
    except (sqlite3.Error, OSError, CampaignError):
        return float("nan"), float("nan")


def spend_parts(spec, t0):
    """Campaign spend as (recorded, estimated_misc). Recorded = opencode cost column (global + per-arm DBs);
    estimated = ai-gateway-misc tokens x catalog price, zero-cost messages only. Admission uses the sum."""
    eval_pat = f"eval-{spec['date']}%"
    recorded = float(db_query(SPEND_Q, (t0, eval_pat, t0, eval_pat))[0][0])
    estimated = misc_estimate(DB, SCOPE_Q, (t0, eval_pat, t0, eval_pat))
    arec, aest = per_arm_spend(spec, t0)
    return recorded + arec, estimated + aest


def campaign_spend(spec, t0):
    recorded, estimated = spend_parts(spec, t0)
    return recorded + estimated


def spend_text(parts):
    """Status text: the estimate is always labelled, never silently mixed with DB-recorded cost."""
    recorded, estimated = parts
    if recorded != recorded or estimated != estimated:
        return "spent=unreadable"
    return f"spent={recorded + estimated:.4f} recorded={recorded:.4f} estimated_misc={estimated:.4f} (estimated)"


def exact_parts(title):
    path = arm_db(title)
    recorded = float(db_query_at(path, EXACT_Q, (title, title))[0][0])
    return recorded, misc_estimate(path, EXACT_SCOPE_Q, (title, title))


def exact_spend(title):
    return sum(exact_parts(title))


def misc_estimate(path, scope_sql, args):
    """Token-priced estimate of ai-gateway-misc assistant messages in scope. Only messages whose RECORDED cost is zero
    are priced (a message with a recorded cost is already in the DB total). Fail closed: a model with no entry in
    PRICES raises CampaignError, so the spend can never be silently understated."""
    total = 0.0
    for (data,) in db_query_at(path, MISC_MSG_Q.format(scope=scope_sql), args):
        j = json.loads(data)
        if float(j.get("cost") or 0) > 0:
            continue
        key = MISC_PREFIX + str(j.get("modelID"))
        price = PRICES.get(key)
        if price is None:
            fail(f"unpriced ai-gateway-misc model in campaign scope: {key} (fail closed: no price table entry)")
        t = j.get("tokens") or {}
        c = t.get("cache") or {}
        n = lambda x: float(x or 0)
        total += (n(t.get("input")) * price["input"] + (n(t.get("output")) + n(t.get("reasoning"))) * price["output"]
                  + n(c.get("read")) * price["cache_read"] + n(c.get("write")) * price["cache_write"]) / 1e6
    return total


def parse_misc_catalog(text):
    """ai-gateway-misc models from `opencode models ai-gateway-misc --verbose` -> {model: prices in USD per 1M tokens}."""
    dec = json.JSONDecoder()
    out = {}
    for m in re.finditer(r"^(ai-gateway-misc/\S+)\s*$", text, re.M):
        brace = text.find("{", m.end())
        if brace < 0:
            continue
        obj, _ = dec.raw_decode(text, brace)
        cost = obj.get("cost")
        if not isinstance(cost, dict):
            continue
        cache = cost.get("cache") or {}
        out[m.group(1)] = {"input": float(cost.get("input") or 0), "output": float(cost.get("output") or 0),
                           "cache_read": float(cache.get("read") or 0), "cache_write": float(cache.get("write") or 0)}
    return out


def fetch_misc_catalog():
    """Re-verify the ai-gateway-misc prices from the provider catalog (the source `opencode models` reads)."""
    try:
        r = subprocess.run(CATALOG_CMD, capture_output=True, text=True, timeout=120)
    except (OSError, subprocess.TimeoutExpired) as e:
        fail(f"catalog command failed: {e}")
    if r.returncode != 0:
        fail(f"catalog command exit {r.returncode}: {r.stderr.strip()[:200]}")
    fetched_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    try:
        cat = parse_misc_catalog(r.stdout)
    except ValueError as e:
        fail(f"catalog output unparseable: {e}")
    if not cat:
        fail("catalog returned no ai-gateway-misc model with a cost")
    return cat, fetched_at


def misc_models(spec):
    return sorted({a["model"] for a in spec["arms"] if a["model"].startswith(MISC_PREFIX)})


def load_price_state(path):
    """Prices recorded at the last launch (<stem>.prices.json), or None when no launch has recorded any."""
    if not os.path.exists(path):
        return None
    try:
        doc = json.load(open(path))
        models = doc["models"]
        for m, p in models.items():
            [float(p[k]) for k in PRICE_FIELDS]
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as e:
        fail(f"price state {path} unreadable (fail closed): {e}")
    return doc


def write_price_state(path, prices, fetched_at):
    doc = {"recorded_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "fetched_at": fetched_at,
           "source": " ".join(CATALOG_CMD), "models": prices}
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(doc, f, indent=2, sort_keys=True)
    os.replace(tmp, path)


def price_gate(spec, stem, accepted):
    """Price freshness (owner ruling 11-21). Re-fetches the catalog, prints each priced model with its per-MTok
    price and fetched-at, and compares with the last launch's prices. Drift requires --prices-accepted (fail closed).
    Returns (prices, fetched_at); raises CampaignError on fetch failure, missing price, or unaccepted drift."""
    models = misc_models(spec)
    if not models:
        print("PRICE-FRESHNESS: n/a (no ai-gateway-misc arm in this campaign)")
        return {}, None
    state_path = stem + PRICE_STATE_SUFFIX
    try:
        catalog, fetched_at = fetch_misc_catalog()
    except CampaignError as e:
        print(f"WARNING: price catalog fetch failed: {e}")
        fail("PRICE-FRESHNESS REFUSED: catalog fetch failed (fail closed, no launch)")
    missing = [m for m in models if m not in catalog]
    if missing:
        fail(f"PRICE-FRESHNESS REFUSED: no catalog price for {missing} (fail closed, no launch)")
    prices = {m: catalog[m] for m in models}
    print(f"PRICE-FRESHNESS source=`{' '.join(CATALOG_CMD)}` fetched_at={fetched_at} models={len(models)}")
    for m in models:
        p = prices[m]
        print(f"  {m}  input={p['input']:.6f} output={p['output']:.6f} cache_read={p['cache_read']:.6f} "
              f"cache_write={p['cache_write']:.6f} USD/MTok  fetched_at={fetched_at}")
    last = load_price_state(state_path)
    drift = []
    if last is None:
        print(f"  state={state_path}: no prior launch recorded (this launch sets the baseline)")
    else:
        print(f"  state={state_path} last_launch={last['recorded_at']}")
        for m in models:
            old = last["models"].get(m)
            if old is None:
                print(f"  new model, no recorded baseline: {m}")
                continue
            for k in PRICE_FIELDS:
                if round(float(old[k]), 6) != round(prices[m][k], 6):
                    drift.append(f"{m} {k} {float(old[k]):.6f} -> {prices[m][k]:.6f}")
    if drift:
        for d in drift:
            print(f"  WARNING: price drift vs last launch: {d}")
        if not accepted:
            fail("PRICE-FRESHNESS REFUSED: prices drifted since the last launch; re-run with --prices-accepted "
                 "to accept the new prices (fail closed, no launch)")
        print("PRICE-FRESHNESS: drift ACCEPTED (--prices-accepted)")
    else:
        print("PRICE-FRESHNESS: OK (no drift vs last launch)" if last else "PRICE-FRESHNESS: OK (baseline)")
    return prices, fetched_at


HOLDOUT_BYTE_CAP = int(os.environ.get("HOLDOUT_BYTE_CAP", "200000000"))            # per arm (proxy --cap-bytes)
HOLDOUT_CAMPAIGN_BYTE_CAP = int(os.environ.get("HOLDOUT_CAMPAIGN_BYTE_CAP", "2000000000"))


def meter_bytes(title):
    """Egress bytes metered by the arm's proxy (owner amendment: the meter is the egress budget)."""
    path = os.path.join(TMPBASE, "holdout-tmp", title, "proxy.json")
    try:
        m = json.load(open(path))
        return int(m.get("bytes_up", 0)) + int(m.get("bytes_down", 0))
    except (OSError, ValueError):
        return 0


def campaign_meter_bytes(spec):
    root = os.path.join(TMPBASE, "holdout-tmp")
    if not os.path.isdir(root):
        return 0
    return sum(meter_bytes(t) for t in os.listdir(root) if t.startswith(f"eval-{spec['date']}-"))


def poller_once(spec, t0, hb_path):
    """One campaign kill-poller cycle (HOLDOUT-SPEC §5.6 #3): refresh heartbeat, stop on overspend."""
    try:
        spent = campaign_spend(spec, t0)
    except sqlite3.Error:
        spent = None
    except CampaignError:
        spent = float("inf")   # unpriced misc spend cannot be bounded: fail closed, stop the campaign
    with open(hb_path, "w") as f:
        f.write(f"{int(time.time())} spent={spent}\n")
    over_meter = campaign_meter_bytes(spec) > HOLDOUT_CAMPAIGN_BYTE_CAP
    if (spent is not None and spent > float(spec["budget_usd"])) or over_meter:
        with LOCK:
            STATE["stop"] = True
            procs = list(STATE["procs"])
        for proc in procs:
            try:
                os.killpg(proc.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
        return True
    return False


def poller_loop(spec, t0, hb_path, interval, done):
    """Campaign-level kill poller (30 s by default); a heartbeat is written every cycle."""
    while not done.wait(interval):
        if poller_once(spec, t0, hb_path):
            return


def title_for(spec, arm, attempt, rr=False):
    bench = spec["benches"][arm["bench"]]
    tag = f"{spec['id']}-a{attempt}" + ("-rr" if rr else "")
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


def status_line(path, job, status, parts):
    line = (f"{time.strftime('%H:%M:%S')} {job['idx']:03d} {arm_label(job['arm'], job['attempt'])} "
            f"{status} {spend_text(parts)}")
    with LOCK:
        with open(path, "a") as f:
            f.write(line + "\n")
    print(line, flush=True)


def run_arm(spec, job, t0, status_path, logdir):
    arm, k = job["arm"], job["attempt"]
    title, tag = title_for(spec, arm, k, rr=job.get("rr", False))
    cap = float(arm["cap"])
    timeout = int(arm.get("timeout", spec["timeout_default"]))
    bench = spec["benches"][arm["bench"]]
    cmd = [os.path.join(EVALS, bench["runner"]), bench["task"], arm["model"], arm.get("variant", ""), tag]
    env = dict(os.environ, EVAL_ARM_CAP=str(cap), EVAL_TIMEOUT_SECS=str(timeout))
    # admission (hard stop): reserve the cap, refuse if the budget cannot cover it
    parts = (0.0, 0.0)
    with LOCK:
        if STATE["stop"]:
            admitted, reason = False, "SKIP-STOPPED"
        else:
            try:
                parts = spend_parts(spec, t0)
                spent = parts[0] + parts[1]
            except (sqlite3.Error, OSError, CampaignError) as e:
                STATE["stop"] = True
                admitted, reason, spent = False, f"STOP-SPEND-UNREADABLE({type(e).__name__})", None
            if spent is None:
                pass
            elif spent + STATE["reserved"] + 2 * cap > float(spec["budget_usd"]):
                STATE["stop"] = True
                admitted, reason = False, "STOP-BUDGET"
            else:
                STATE["reserved"] += 2 * cap
                admitted, reason = True, None
    if not admitted:
        status_line(status_path, job, reason, parts if reason == "STOP-BUDGET" else (0.0, 0.0))
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
            except CampaignError:
                kill_group("unpriced-driver")
                return
            if c > 2 * cap:
                kill_group("costcap-driver")
                return
            if HOLDOUT_TITLE_RE.search(title) and meter_bytes(title) > HOLDOUT_BYTE_CAP:
                kill_group("meter-driver")
                return

    with LOCK:
        STATE["procs"].add(proc)
    threading.Thread(target=poller, daemon=True).start()
    try:
        rc = proc.wait(timeout=timeout + 300)  # runner watchdog fires first; this is the backstop
    except subprocess.TimeoutExpired:
        kill_group("timeout-driver")
        rc = proc.wait()
    finally:
        with LOCK:
            STATE["procs"].discard(proc)
        done.set()
        with LOCK:
            STATE["reserved"] -= 2 * cap
    if flags.get("meter-driver"):
        status = "meter-driver"
    elif flags.get("costcap-driver"):
        status = "costcap-driver"
    elif flags.get("timeout-driver"):
        status = "timeout-driver"
    elif flags.get("unpriced-driver"):
        status = "unpriced-driver"
    elif rc == 0:
        status = "ok"
    elif rc == 125:
        status = "costcap"
    elif rc == 124:
        status = "timeout"
    else:
        status = f"rc{rc}"
    status_line(status_path, job, status, safe_parts(spec, t0))
    return status


def is_dnf(spec, job, status):
    """HOLDOUT-SPEC §7.3: a run without final-report.md is a DNF (also any kill/timeout/nonzero exit)."""
    if spec["benches"][job["arm"]["bench"]]["runner"] != "run-eval-v6.sh":
        return False          # DNF re-runs are for held-out benches only (OPEN-16)
    if status != "ok":
        return True
    title, _ = title_for(spec, job["arm"], job["attempt"], rr=job.get("rr", False))
    report = os.path.join(TMPBASE, "holdout-work", title, "final-report.md")
    return not os.path.isfile(report)


def run_with_rerun(spec, job, t0, status_path, logdir):
    """One DNF arm gets exactly ONE re-run (-rr title), admitted by the normal budget rule (§7.3)."""
    status = run_arm(spec, job, t0, status_path, logdir)
    if status not in ("STOP-BUDGET", "SKIP-STOPPED") and not job.get("rr") and is_dnf(spec, job, status):
        status = run_arm(spec, dict(job, rr=True), t0, status_path, logdir)
    return status


def self_check(spec, jobs, stem, accepted):
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
    price_gate(spec, stem, accepted)     # raises CampaignError on drift / fetch failure (fail closed)
    print("SELF-CHECK OK (no launch)")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("campaign", nargs="?")
    ap.add_argument("--self-check", action="store_true", help="validate the campaign + runners + DB; do not launch")
    ap.add_argument("--prices-accepted", action="store_true",
                    help="accept ai-gateway-misc price drift vs the last launch (required after a WARNING)")
    ap.add_argument("--poller-selftest", action="store_true", help="prove the campaign kill poller writes a heartbeat; no launch")
    args = ap.parse_args()
    if not args.poller_selftest and not args.campaign:
        ap.error("the campaign file is required")
    if args.poller_selftest:
        import tempfile
        hb = os.path.join(tempfile.mkdtemp(), "hb")
        done = threading.Event()
        spec = {"date": time.strftime("%Y-%m-%d"), "budget_usd": 1e9}
        threading.Timer(1.0, done.set).start()
        poller_loop(spec, int(time.time() * 1000), hb, 0.2, done)
        ok = os.path.isfile(hb) and os.path.getsize(hb) > 0
        print("POLLER-HEARTBEAT " + ("OK" if ok else "MISSING"))
        return 0 if ok else 1
    try:
        spec = load_spec(args.campaign)
        jobs = build_jobs(spec)
        stem = os.path.splitext(os.path.abspath(args.campaign))[0]
        if args.self_check:
            self_check(spec, jobs, stem, args.prices_accepted)
            return 0
        preflight_db()
        prices, fetched_at = price_gate(spec, stem, args.prices_accepted)   # fail closed before any arm
        if prices:
            write_price_state(stem + PRICE_STATE_SUFFIX, prices, fetched_at)
        PRICES.clear()
        PRICES.update(prices)
        status_path = stem + ".status.txt"
        logdir = stem + ".logs"
        os.makedirs(logdir, exist_ok=True)
        t0 = int(time.time() * 1000)
        # campaign-level kill poller (HOLDOUT-SPEC §5.6 #3): backstop for a dead per-arm poller
        poll_done = threading.Event()
        threading.Thread(target=poller_loop, daemon=True,
                         args=(spec, t0, stem + ".poller.hb", POLL_SECS, poll_done)).start()
        with open(status_path, "a") as f:
            f.write(f"# campaign {spec['id']} date={spec['date']} budget_usd={spec['budget_usd']:.2f} "
                    f"start_ms={t0} jobs={len(jobs)}\n")
        # first attempt alone: it must produce the exact title AND the date-pattern sessions
        first = jobs[0]
        run_arm(spec, first, t0, status_path, logdir)
        title0, _ = title_for(spec, first["arm"], first["attempt"])
        # held-out titles are counted in the arm's own DB (the one the arm writes); legacy in the global DB
        n_exact = count_sessions(title0, t0, True, spec["date"])
        n_pat = count_sessions(title0, t0, False, spec["date"])
        if n_exact == 0 or n_pat == 0:
            with LOCK:
                STATE["stop"] = True
            status_line(status_path, {"idx": 0, "arm": {"bench": "-", "model": "-", "variant": ""}, "attempt": 0},
                        f"ABORT-no-session(exact={n_exact},pattern={n_pat})", safe_parts(spec, t0))
        else:
            with ThreadPoolExecutor(max_workers=spec["parallelism"]) as ex:
                list(ex.map(lambda j: run_with_rerun(spec, j, t0, status_path, logdir), jobs[1:]))
        poll_done.set()
        final = spend_text(safe_parts(spec, t0))
        with LOCK:
            print(f"CAMPAIGN DONE id={spec['id']} {final} budget_usd={spec['budget_usd']:.2f}", flush=True)
        with open(status_path, "a") as f:
            f.write(f"# done {final} budget_usd={spec['budget_usd']:.2f}\n")
        return 0
    except CampaignError as e:
        sys.stdout.flush()   # keep the preflight block ahead of the refusal when both go to one pipe
        print(f"ERROR: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
