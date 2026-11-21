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
rc_mod.subprocess.Popen = lambda cmd, **k: (launches.append(cmd), FakeProc())[1]
job = {"idx": 1, "arm": {"bench": "HO2", "model": "m", "cap": 0.1}, "attempt": 1}
logd = os.path.join(T, "logs"); os.makedirs(logd)


def reset(spent=0.0):
    launches.clear(); rc_mod.STATE.update(stop=False, reserved=0.0, procs=set())
    rc_mod.TMPBASE = tempfile.mkdtemp(dir=T); rc_mod.campaign_spend = lambda s, t0, _v=spent: _v


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
shutil.rmtree(T, ignore_errors=True)
print("HARNESS-SELFTEST " + ("PASS" if not FAILS else f"FAIL ({len(FAILS)})"))
sys.exit(1 if FAILS else 0)
