#!/usr/bin/env python3
"""TLS-terminating egress proxy with per-arm metering — PASS-THROUGH (owner amendment, M10 replaced).

    holdout-proxy.py --port P --allow host[,host...] --campaign-dir DIR --metrics FILE --cap-bytes N \\
                     [--upstream-override host=ip:port ...] [--upstream-ca FILE]

Route:
  1. CONNECT host:443. Only allowlisted hosts are accepted; everything else gets 403 (metered as denied).
  2. The proxy answers 200 and terminates TLS with the host's leaf cert, signed by the campaign CA.
  3. The client's request is FORWARDED AS-IS upstream. The proxy neither reads nor rewrites credentials
     (Authorization, x-api-key, ...): the arm carries its own copy of opencode's auth store, and opencode's
     plugin refreshes OAuth itself. Only hop-by-hop headers are dropped and Connection: close is forced.
  4. The response is streamed back with Connection: close.
Metering: connects, requests, bytes up/down per arm, in --metrics (JSON, atomic). The meter is the ONLY
egress budget: once bytes reach --cap-bytes, new requests get 429 and the campaign kill poller reads the
same file (run-campaign.py).

Fail closed: refuses to start if the campaign CA key is not mode 0600, or if the campaign dir lies under an
arm directory (holdout-work/ holdout-xdg/ holdout-cfg/ holdout-tmp/ holdout-home/).
Metering is by bytes, not provider tokens (tokens are inside TLS).
"""
import argparse, json, os, socket, socketserver, ssl, threading

LOCK = threading.Lock()
M = {"connects": 0, "requests": 0, "denied": 0, "refused_cap": 0, "bytes_up": 0, "bytes_down": 0}
ARGS = None
ARM_DIRS = ("holdout-work", "holdout-xdg", "holdout-cfg", "holdout-tmp", "holdout-home")
HOP = {"connection", "keep-alive", "proxy-connection", "proxy-authorization", "te", "trailer",
       "upgrade", "host"}   # content-length is end-to-end: the upstream must see the body length


def fail_closed(msg):
    raise SystemExit("holdout-proxy: refusing to start: " + msg)


def check_outside_arms(path, what):
    real = os.path.realpath(path)
    for d in ARM_DIRS:
        if f"/{d}/" in real + "/":
            fail_closed(f"{what} lies under an arm directory ({d})")


def flush_metrics():
    tmp = ARGS.metrics + ".tmp"
    with open(tmp, "w") as fh:
        json.dump(M, fh, sort_keys=True)
    os.replace(tmp, ARGS.metrics)


def total():
    return M["bytes_up"] + M["bytes_down"]


def count(key, n=0, bytes_up=0, bytes_down=0):
    with LOCK:
        M[key] += n
        M["bytes_up"] += bytes_up
        M["bytes_down"] += bytes_down
        flush_metrics()


def read_head(f):
    line = f.readline(65536)
    if not line:
        return None
    start = line.decode("latin-1").rstrip("\r\n")
    headers, raw = [], [line]
    while True:
        h = f.readline(65536)
        raw.append(h)
        if h in (b"\r\n", b"\n", b""):
            break
        name, _, value = h.decode("latin-1").partition(":")
        headers.append((name.strip(), value.strip()))
    return start, headers, b"".join(raw)


def read_body(f, headers):
    hd = {k.lower(): v for k, v in headers}
    if "chunked" in hd.get("transfer-encoding", "").lower():
        out = []
        while True:
            size_line = f.readline(65536)
            out.append(size_line)
            size = int(size_line.split(b";")[0].strip() or b"0", 16)
            if size == 0:
                while True:
                    t = f.readline(65536)
                    out.append(t)
                    if t in (b"\r\n", b"\n", b""):
                        break
                break
            out.append(f.read(size))
            out.append(f.readline(65536))
        return b"".join(out)
    n = int(hd.get("content-length", "0") or 0)
    return f.read(n) if n else b""


class Handler(socketserver.StreamRequestHandler):
    def reply(self, sock, code, text):
        try:
            sock.sendall(f"HTTP/1.1 {code} {text}\r\nContent-Length: 0\r\nConnection: close\r\n\r\n".encode())
        except OSError:
            pass

    def handle(self):
        line = self.rfile.readline(8192).decode("latin-1").strip()
        while True:
            h = self.rfile.readline(8192)
            if h in (b"\r\n", b"\n", b""):
                break
        parts = line.split()
        if len(parts) != 3 or parts[0] != "CONNECT":
            count("denied", 1)
            return self.reply(self.connection, 403, "Forbidden")
        host, _, port = parts[1].rpartition(":")
        if host not in ARGS.allow or port != "443":
            count("denied", 1)
            return self.reply(self.connection, 403, "Forbidden")
        leaf, key = os.path.join(ARGS.campaign_dir, host + ".pem"), os.path.join(ARGS.campaign_dir, host + ".key")
        if not (os.path.isfile(leaf) and os.path.isfile(key)):
            count("denied", 1)
            return self.reply(self.connection, 403, "no leaf certificate for host (fail closed)")
        with LOCK:
            if total() >= ARGS.cap_bytes:
                M["refused_cap"] += 1; flush_metrics()
                return self.reply(self.connection, 429, "Arm byte cap reached")
            M["connects"] += 1; flush_metrics()
        self.connection.sendall(b"HTTP/1.1 200 Connection Established\r\n\r\n")
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.load_cert_chain(leaf, key)
        try:
            client = ctx.wrap_socket(self.connection, server_side=True)
        except (ssl.SSLError, OSError):
            return
        f = client.makefile("rb")
        try:
            head = read_head(f)
            if head is None:
                return
            start, headers, raw_head = head
            body = read_body(f, headers)
            if total() >= ARGS.cap_bytes:
                return self.reply(client, 429, "Arm byte cap reached")
            count("requests", 1, bytes_up=len(raw_head) + len(body))
            self.forward(client, host, start, headers, body)
        except (ssl.SSLError, OSError, ValueError):
            return
        finally:
            try:
                client.close()
            except OSError:
                pass

    def forward(self, client, host, start, headers, body):
        target = ARGS.overrides.get(host, (host, 443))
        out = [start + "\r\n", f"Host: {host}\r\n"]
        for name, value in headers:           # pass-through: every non-hop-by-hop header, credentials included
            if name.lower() in HOP:
                continue
            out.append(f"{name}: {value}\r\n")
        out.append("Connection: close\r\n\r\n")
        ctx = ssl.create_default_context(cafile=ARGS.upstream_ca) if ARGS.upstream_ca else ssl.create_default_context()
        try:
            up = ctx.wrap_socket(socket.create_connection(target, timeout=60), server_hostname=host)
        except OSError:
            return self.reply(client, 502, "Bad Gateway")
        try:
            up.sendall("".join(out).encode("latin-1") + body)
            buf = b""
            while b"\r\n\r\n" not in buf:
                chunk = up.recv(65536)
                if not chunk:
                    break
                buf += chunk
            head, _, rest = buf.partition(b"\r\n\r\n")
            lines = head.split(b"\r\n")
            kept = [lines[0]] + [l for l in lines[1:] if not l.lower().startswith(b"connection:")]
            client.sendall(b"\r\n".join(kept) + b"\r\nConnection: close\r\n\r\n" + rest)
            count("requests", 0, bytes_down=len(head) + 4 + len(rest))
            while True:
                chunk = up.recv(65536)
                if not chunk:
                    break
                client.sendall(chunk)
                count("requests", 0, bytes_down=len(chunk))
        except (ssl.SSLError, OSError):
            pass
        finally:
            up.close()


class Server(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


def main():
    global ARGS
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, required=True)
    ap.add_argument("--allow", required=True)
    ap.add_argument("--campaign-dir", required=True)
    ap.add_argument("--metrics", required=True)
    ap.add_argument("--cap-bytes", type=int, required=True)
    ap.add_argument("--upstream-override", action="append", default=[])
    ap.add_argument("--upstream-ca", default=None)
    ARGS = ap.parse_args()
    ARGS.allow = set(ARGS.allow.split(","))
    key_path = os.path.join(ARGS.campaign_dir, "ca.key")
    if not os.path.isfile(key_path) or os.stat(key_path).st_mode & 0o777 != 0o600:
        fail_closed("campaign CA key missing or not mode 0600")
    check_outside_arms(ARGS.campaign_dir, "campaign dir")
    ARGS.overrides = {}
    for spec in ARGS.upstream_override:   # self-test only: map a host to a local stub
        h, _, addr = spec.partition("=")
        ip, _, p = addr.rpartition(":")
        ARGS.overrides[h] = (ip, int(p))
    flush_metrics()
    with Server(("127.0.0.1", ARGS.port), Handler) as srv:
        srv.serve_forever()


if __name__ == "__main__":
    main()
