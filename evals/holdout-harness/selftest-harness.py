#!/usr/bin/env python3
"""selftest-harness.py — zero-cost checks for the egress proxy (pass-through + metering), provider wiring,
DNF re-run, admission and the meter-driven kill poller. No provider call. Exit 1 on any failure."""
import importlib.util, json, os, shutil, socket, ssl, subprocess, sys, tempfile, time, threading, http.server
HERE = os.path.dirname(os.path.abspath(__file__))
EVALS = os.path.dirname(HERE)
TEMPLATE = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(HERE))), "evals-keys", "holdout-config-template.json")
FAILS = []


def check(ok, msg):
    print(("PASS " if ok else "FAIL ") + msg)
    if not ok:
        FAILS.append(msg)


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod); return mod


hp = load(os.path.join(HERE, "holdout-provider.py"), "hp")
T = tempfile.mkdtemp(prefix="selftest-harness-")

# 1. provider blocks (OPEN-12): parse jsonc-style, rails kept, no plugins, placeholder key only
for model, prov in [("github-copilot/claude-haiku-5.5", "github-copilot"),
                    ("ai-gateway-misc/fw-deepseek-v4.1-flash", "ai-gateway-misc"),
                    ("fireworks-ai/accounts/fireworks/models/minimax-m3p1-flash", "fireworks-ai")]:
    out = os.path.join(T, prov, "opencode", "opencode.json")
    hp.write_config(model, TEMPLATE, out)
    doc = json.loads(hp.strip_jsonc(open(out).read()))
    rails = doc["permission"]["bash"] == {"*git push*": "deny", "*git commit*": "ask"}
    check(doc["model"] == model and list(doc["provider"]) == [prov] and doc["mcp"] == {} and "plugin" not in doc and rails,
          f"arm config parses; provider={prov}; MCP empty; no plugins; rails kept")
    check("apiKey" not in doc["provider"][prov]["options"], f"{prov}: no apiKey in the config (key comes from the auth copy)")
    if prov == "ai-gateway-misc":
        check(doc["provider"][prov].get("npm") == "@ai-sdk/openai-compatible", "custom provider carries its npm package")
    if prov == "fireworks-ai":
        check("npm" not in doc["provider"][prov], "built-in provider carries no npm override")

# 2. proxy: fail-closed start, allowlist, pass-through, meter, byte cap
camp = os.path.join(T, "camp")
subprocess.run(["bash", os.path.join(HERE, "holdout-ca.sh"), camp, "api.test.invalid"], check=True, capture_output=True)


def free_port():
    s = socket.socket(); s.bind(("127.0.0.1", 0)); p = s.getsockname()[1]; s.close(); return p


def start_proxy(cap=1000000, ca_mode=0o600):
    os.chmod(os.path.join(camp, "ca.key"), ca_mode)
    port = free_port(); metrics = os.path.join(T, f"m{port}.json")
    p = subprocess.Popen([sys.executable, "-B", os.path.join(HERE, "holdout-proxy.py"), "--port", str(port),
                          "--allow", "api.test.invalid", "--campaign-dir", camp, "--metrics", metrics,
                          "--cap-bytes", str(cap), "--upstream-override", f"api.test.invalid={UP_ADDR}",
                          "--upstream-ca", os.path.join(UPCA, "ca.pem")], stderr=subprocess.PIPE)
    time.sleep(1.0)
    return p, port, metrics


# stub upstream: echoes whether it received EXACTLY the client's header (pass-through), never a rewritten one
UPCA = os.path.join(T, "upca"); subprocess.run(["bash", os.path.join(HERE, "holdout-ca.sh"), UPCA, "upstream-ca", "api.test.invalid"], check=True, capture_output=True)
seen = []
posted = []


class H(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    def do_GET(self):
        seen.append(self.headers.get("Authorization"))
        body = b"SEEN"
        self.send_response(200); self.send_header("Content-Length", str(len(body)))
        self.send_header("Connection", "close"); self.end_headers(); self.wfile.write(body)

    def do_POST(self):
        n = int(self.headers.get("Content-Length", "0"))
        posted.append(self.rfile.read(n))
        body = b"POSTED"
        self.send_response(200); self.send_header("Content-Length", str(len(body)))
        self.send_header("Connection", "close"); self.end_headers(); self.wfile.write(body)
    def log_message(self, *a): pass


stub = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
ctx.load_cert_chain(os.path.join(UPCA, "api.test.invalid.pem"), os.path.join(UPCA, "api.test.invalid.key"))
stub.socket = ctx.wrap_socket(stub.socket, server_side=True)
threading.Thread(target=stub.serve_forever, daemon=True).start()
UP_ADDR = f"127.0.0.1:{stub.server_address[1]}"

p, port, metrics = start_proxy()
check(p.poll() is None, "proxy starts with a 0600 CA key (no creds file required)")
r = subprocess.run(["curl", "-sS", "-o", "/dev/null", "-x", f"http://127.0.0.1:{port}", "https://evil.example/"], capture_output=True)
check(json.load(open(metrics))["denied"] >= 1, "non-allowlisted host refused and metered as denied")
r = subprocess.run(["curl", "-sS", "--cacert", os.path.join(camp, "ca.pem"), "--proxy", f"http://127.0.0.1:{port}",
                    "-H", "Authorization: Bearer CLIENT-OWN-KEY", "https://api.test.invalid/", "-o", "/dev/null"], capture_output=True)
m = json.load(open(metrics))
check(r.returncode == 0 and seen and seen[-1] == "Bearer CLIENT-OWN-KEY", "allowlisted host: client's Authorization forwarded AS-IS (no injection)")
check(m["requests"] >= 1 and m["bytes_up"] > 0 and m["bytes_down"] > 0, "meter counts requests and bytes in both directions")
r = subprocess.run(["curl", "-sS", "--cacert", os.path.join(camp, "ca.pem"), "--proxy", f"http://127.0.0.1:{port}",
                    "-H", "Content-Type: application/json", "-d", '{"model":"x","n":42}', "https://api.test.invalid/v1/chat"], capture_output=True)
check(r.returncode == 0 and posted and posted[-1] == b'{"model":"x","n":42}', "POST body and Content-Length reach upstream byte-identical")
p.terminate()

p, port, metrics = start_proxy(cap=300)
for _ in range(3):   # the cap is checked at CONNECT: two requests reach ~430 bytes, the third tunnel gets 429
    subprocess.run(["curl", "-sS", "-o", "/dev/null", "--cacert", os.path.join(camp, "ca.pem"), "--proxy", f"http://127.0.0.1:{port}",
                    "https://api.test.invalid/"], capture_output=True)
check(json.load(open(metrics))["refused_cap"] >= 1, "byte cap: once the meter passes the cap, the next tunnel is refused (429) and metered")
p.terminate()
p, _, _ = start_proxy(ca_mode=0o644)
check(p.wait(timeout=5) != 0 if p.poll() is None else True, "proxy refuses to start with a CA key that is not 0600")
p.kill() if p.poll() is None else None
os.chmod(os.path.join(camp, "ca.key"), 0o600)

# 3. meter-driven kill poller (owner amendment: the meter is the egress budget; the campaign poller reads it)
rc_mod = load(os.path.join(EVALS, "run-campaign.py"), "rc")
rc_mod.TMPBASE = tempfile.mkdtemp(dir=T)
tdate = time.strftime("%Y-%m-%d")
title = f"eval-{tdate}-HO2-SP1-x-holdout-test-a1"
os.makedirs(os.path.join(rc_mod.TMPBASE, "holdout-tmp", title))
json.dump({"bytes_up": 10, "bytes_down": rc_mod.HOLDOUT_CAMPAIGN_BYTE_CAP + 1, "requests": 1},
          open(os.path.join(rc_mod.TMPBASE, "holdout-tmp", title, "proxy.json"), "w"))
spec = {"id": "t", "date": tdate, "budget_usd": 15.0, "parallelism": 1, "timeout_default": 900,
        "benches": {"HO2": {"runner": "run-eval-v6.sh", "task": "HO2", "title_token": "HO2-SP1"},
                    "V4": {"runner": "run-eval-v4.sh", "task": "IV4", "title_token": "IV2-RG4"}}, "arms": []}
rc_mod.campaign_spend = lambda s, t0: 0.0
rc_mod.STATE.update(stop=False, reserved=0.0, procs=set())
check(rc_mod.poller_once(spec, 0, os.path.join(T, "hb")) is True and rc_mod.STATE["stop"] is True,
      "campaign kill poller stops the campaign when the meter exceeds the campaign byte cap")
check(rc_mod.meter_bytes(title) > rc_mod.HOLDOUT_BYTE_CAP, "per-arm meter bytes read from the arm's proxy.json")

# 4. DNF re-run and admission (fake Popen; nothing launches)
class FakeProc:
    pid = 1
    def wait(self, timeout=None): return 0
launches = []
REAL_POPEN = subprocess.Popen   # section 6 restores it: this patch is process-wide
rc_mod.subprocess.Popen = lambda cmd, **k: (launches.append(cmd), FakeProc())[1]
job = {"idx": 1, "arm": {"bench": "HO2", "model": "m", "cap": 0.1}, "attempt": 1}
logd = os.path.join(T, "logs"); os.makedirs(logd)


def reset(spent=0.0):
    launches.clear(); rc_mod.STATE.update(stop=False, reserved=0.0, procs=set())
    rc_mod.TMPBASE = tempfile.mkdtemp(dir=T); rc_mod.spend_parts = lambda s, t0, _v=spent: (_v, 0.0)


reset(); rc_mod.run_with_rerun(spec, job, 0, os.path.join(logd, "a.txt"), logd)
check(len(launches) == 2 and launches[1][-1].endswith("-rr"), f"DNF held-out arm: exactly one re-run with -rr (launches={len(launches)})")
reset(); t, _ = rc_mod.title_for(spec, job["arm"], 1)
os.makedirs(os.path.join(rc_mod.TMPBASE, "holdout-work", t)); open(os.path.join(rc_mod.TMPBASE, "holdout-work", t, "final-report.md"), "w").write("r")
rc_mod.run_with_rerun(spec, job, 0, os.path.join(logd, "b.txt"), logd)
check(len(launches) == 1, "final-report.md present: no re-run")
reset(); job4 = {"idx": 2, "arm": {"bench": "V4", "model": "m", "cap": 0.1}, "attempt": 1}
rc_mod.run_with_rerun(spec, job4, 0, os.path.join(logd, "c.txt"), logd)
check(len(launches) == 1, "legacy v4 bench never re-runs")
reset(spent=12.0); rc_mod.run_with_rerun(spec, job, 0, os.path.join(logd, "d.txt"), logd)
check(len(launches) == 2, "admission: spend 12.0 + 2*0.1 <= 15 admits the arm and its one re-run")
reset(spent=14.9); st = rc_mod.run_arm(spec, job, 0, os.path.join(logd, "e.txt"), logd)
check(not launches and st == "STOP-BUDGET", "admission: spend 14.9 + 2*0.1 > 15 refused, nothing launched")
# 5. per-arm DB accounting (owner fix): held-out titles are counted and costed in the ARM's own DB
import sqlite3
rc_mod = load(os.path.join(EVALS, "run-campaign.py"), "rc_fresh")   # section 4 stubbed campaign_spend: reload
rc_mod.TMPBASE = tempfile.mkdtemp(dir=T)
rc_mod.DB = os.path.join(T, "global.db")
def mk_db(path, rows):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    c = sqlite3.connect(path)
    c.execute("CREATE TABLE session (id TEXT, title TEXT, cost REAL, parent_id TEXT, time_created INTEGER)")
    c.execute("CREATE TABLE message (id TEXT, session_id TEXT, time_created INTEGER, time_updated INTEGER, data TEXT)")
    c.executemany("INSERT INTO session VALUES (?,?,?,?,?)", rows); c.commit(); c.close()
t_arm = f"eval-{tdate}-HO2-SP1-arm-x-a1"
t0 = int(time.time() * 1000) - 60000
mk_db(os.path.join(rc_mod.TMPBASE, "holdout-xdg", t_arm, "opencode", "opencode.db"),
      [("s1", t_arm, 0.30, None, t0 + 1000), ("s2", "child", 0.10, "s1", t0 + 2000), ("old", t_arm, 9.0, None, t0 - 5000)])
mk_db(rc_mod.DB, [])                                   # global DB exists and is empty: held-out sessions never go there
check(rc_mod.count_sessions(t_arm, t0, True, tdate) == 1, "held-out exact-title check reads the ARM DB (1 session, not the global DB)")
check(rc_mod.count_sessions(t_arm, t0, False, tdate) == 1, "held-out date-pattern check counts the arm DB's eval-titled sessions since t0 (child titles are not eval-)")
check(rc_mod.count_sessions(f"eval-{tdate}-HO2-SP1-absent-a1", t0, True, tdate) == 0, "missing arm DB counts as 0 (fail closed)")
check(abs(rc_mod.campaign_spend(spec, t0) - 0.40) < 1e-9, "campaign spend sums the arm DB (0.30 + child 0.10), excludes pre-t0 sessions")
os.chmod(os.path.dirname(os.path.dirname(rc_mod.arm_db(t_arm))), 0o000)
try:
    unreadable = rc_mod.campaign_spend(spec, t0)
except (sqlite3.Error, OSError):
    unreadable = None
os.chmod(os.path.dirname(os.path.dirname(rc_mod.arm_db(t_arm))), 0o755)
rc_mod.spend_parts = lambda s, t0_: (_ for _ in ()).throw(sqlite3.OperationalError("unreadable"))
launches.clear(); rc_mod.STATE.update(stop=False, reserved=0.0, procs=set())
st = rc_mod.run_arm(spec, job, t0, os.path.join(logd, "f.txt"), logd)
check(not launches and st.startswith("STOP-SPEND-UNREADABLE"), "unreadable spend refuses admission (fail closed), nothing launched")
# 6. ai-gateway-misc pricing (owner ruling 11-21): zero-cost rows priced from tokens; fail-closed fetch; drift gate
subprocess.Popen = REAL_POPEN
rc_p = load(os.path.join(EVALS, "run-campaign.py"), "rc_price")
rc_p.TMPBASE = tempfile.mkdtemp(dir=T); rc_p.DB = os.path.join(T, "price-global.db")
GLM = "ai-gateway-misc/fw-glm-5.3-flash"
PR = {"input": 0.1221, "output": 0.407, "cache_read": 0.02442, "cache_write": 0.0}
mk_db(rc_p.DB, [])
pdate = time.strftime("%Y-%m-%d")
p_title = f"eval-{pdate}-HO2-SP1-p-a1"
p_t0 = int(time.time() * 1000) - 60000
p_spec = {"id": "p", "date": pdate, "budget_usd": 15.0, "parallelism": 1, "timeout_default": 900,
          "benches": {"HO2": {"runner": "run-eval-v6.sh", "task": "HO2", "title_token": "HO2-SP1"}},
          "arms": [{"bench": "HO2", "model": GLM, "variant": "high", "cap": 0.1, "attempts": 1}]}
def misc_msg(cost, model="fw-glm-5.3-flash", inp=0, out=0, cread=0):
    return json.dumps({"role": "assistant", "providerID": "ai-gateway-misc", "modelID": model, "cost": cost,
                       "tokens": {"input": inp, "output": out, "reasoning": 0, "cache": {"read": cread, "write": 0}}})
def mk_arm_db(path, sessions, messages):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    c = sqlite3.connect(path)
    c.execute("CREATE TABLE session (id TEXT, title TEXT, cost REAL, parent_id TEXT, time_created INTEGER)")
    c.execute("CREATE TABLE message (id TEXT, session_id TEXT, time_created INTEGER, time_updated INTEGER, data TEXT)")
    c.executemany("INSERT INTO session VALUES (?,?,?,?,?)", sessions)
    c.executemany("INSERT INTO message VALUES (?,?,?,?,?)", messages); c.commit(); c.close()
# arm DB: s1 zero-cost (priced: 1M in, 0.5M out, 2M cache-read); m2 carries a RECORDED cost (0.5, kept as recorded, not re-priced);
# child c1 zero-cost (1M in). Expected estimate = 0.1221 + 0.407*0.5 + 0.02442*2 + 0.1221 = 0.49654
mk_arm_db(os.path.join(rc_p.TMPBASE, "holdout-xdg", p_title, "opencode", "opencode.db"),
          [("s1", p_title, 0.5, None, p_t0 + 1000), ("c1", "child", 0.0, "s1", p_t0 + 2000)],
          [("m1", "s1", p_t0 + 1001, p_t0 + 1001, misc_msg(0, inp=1000000, out=500000, cread=2000000)),
           ("m2", "s1", p_t0 + 1002, p_t0 + 1002, misc_msg(0.5, inp=1000000)),
           ("m3", "c1", p_t0 + 2001, p_t0 + 2001, misc_msg(0, inp=1000000))])
rc_p.PRICES.clear(); rc_p.PRICES.update({GLM: PR})
rec, est = rc_p.per_arm_spend(p_spec, p_t0)
check(abs(est - 0.49654) < 1e-9, f"zero-cost misc rows priced from tokens (estimate {est:.5f}, expected 0.49654); recorded-cost message not re-priced")
check(abs(rec - 0.5) < 1e-9, f"DB-recorded cost stays separate (recorded {rec:.4f})")
check(abs(rc_p.campaign_spend(p_spec, p_t0) - 0.99654) < 1e-9, "campaign spend (admission) = recorded + estimated")
txt = rc_p.spend_text((rec, est))
check("(estimated)" in txt and "estimated_misc=0.4965" in txt and "recorded=0.5000" in txt, "status text labels the misc estimate separately")
rc_p.PRICES.clear()
try:
    rc_p.campaign_spend(p_spec, p_t0); unpriced = False
except rc_p.CampaignError:
    unpriced = True
check(unpriced, "unpriced misc model in scope refuses (fail closed), never silently 0")
rc_p.PRICES.update({GLM: PR})
# catalog fetch failure -> fail-closed refusal (real subprocess that exits 3)
fail_stem = os.path.join(T, "fetchfail")
rc_p.CATALOG_CMD = [sys.executable, "-c", "import sys; sys.stderr.write('catalog down'); sys.exit(3)"]
out_buf = []
try:
    rc_p.price_gate(p_spec, fail_stem, False); refused = False
except rc_p.CampaignError as e:
    refused = "fetch failed" in str(e) or "catalog" in str(e)
check(refused, "catalog fetch failure refuses the launch (fail closed) with a warning")
# drift: a fake catalog printing the opencode --verbose format; last launch recorded a different input price
cat_text = ("ai-gateway-misc/fw-glm-5.3-flash\n" + json.dumps({"id": "fw-glm-5.3-flash", "cost": {
    "input": 0.1221, "output": 0.407, "cache": {"read": 0.02442, "write": 0}}}, indent=2) + "\n"
    "ai-gateway-misc/other-model\n" + json.dumps({"id": "other-model", "cost": {"input": 9, "output": 9, "cache": {"read": 0, "write": 0}}}, indent=2) + "\n")
fake = os.path.join(T, "fake_catalog.py")
open(fake, "w").write("import sys\nsys.stdout.write(" + repr(cat_text) + ")\n")
rc_p.CATALOG_CMD = [sys.executable, fake]
parsed = rc_p.parse_misc_catalog(cat_text)
check(parsed[GLM] == PR and "ai-gateway-misc/other-model" in parsed, "catalog parse: per-MTok prices, cache read/write, all ai-gateway-misc ids")
drift_stem = os.path.join(T, "drift-camp")
rc_p.write_price_state(drift_stem + rc_p.PRICE_STATE_SUFFIX, {GLM: dict(PR, input=0.22)}, "2026-11-20T00:00:00Z")
try:
    rc_p.price_gate(p_spec, drift_stem, False); drifted = False
except rc_p.CampaignError as e:
    drifted = "drifted" in str(e) and "--prices-accepted" in str(e)
check(drifted, "price drift vs last launch refuses without --prices-accepted")
check(rc_p.load_price_state(drift_stem + rc_p.PRICE_STATE_SUFFIX)["models"][GLM]["input"] == 0.22, "a refused gate writes no state (last launch prices kept)")
prices, _ = rc_p.price_gate(p_spec, drift_stem, True)
check(prices[GLM]["input"] == 0.1221, "drift accepted with --prices-accepted: the fresh prices are used")
rc_p.write_price_state(drift_stem + rc_p.PRICE_STATE_SUFFIX, prices, "2026-11-21T00:00:00Z")
prices, _ = rc_p.price_gate(p_spec, drift_stem, False)
check(prices[GLM] == PR, "no drift vs the recorded launch: passes without the flag")
nomisc = dict(p_spec, arms=[{"bench": "HO2", "model": "github-copilot/claude-haiku-5.5", "cap": 0.1}])
rc_p.CATALOG_CMD = [sys.executable, "-c", "import sys; sys.exit(9)"]
check(rc_p.price_gate(nomisc, drift_stem, False) == ({}, None), "no misc arm: no catalog fetch, freshness not applicable")
shutil.rmtree(T, ignore_errors=True)
print("HARNESS-SELFTEST " + ("PASS" if not FAILS else f"FAIL ({len(FAILS)})"))
sys.exit(1 if FAILS else 0)
