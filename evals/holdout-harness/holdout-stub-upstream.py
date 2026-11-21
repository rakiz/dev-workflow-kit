#!/usr/bin/env python3
"""Self-test stub upstream (TLS). Replies AUTH-OK only if the credential header equals --expect.
It never echoes the header value back, so the self-test cannot leak the real credential to the client.
    holdout-stub-upstream.py --port P --cert C --key K --header NAME --expect VALUE
"""
import argparse, http.server, ssl

ap = argparse.ArgumentParser()
ap.add_argument("--port", type=int, required=True)
ap.add_argument("--cert", required=True); ap.add_argument("--key", required=True)
ap.add_argument("--header", required=True); ap.add_argument("--expect", required=True)
A = ap.parse_args()


class H(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def do_GET(self):
        ok = self.headers.get(A.header) == A.expect
        body = (b"AUTH-OK" if ok else b"AUTH-BAD")
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass


srv = http.server.ThreadingHTTPServer(("127.0.0.1", A.port), H)
ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
ctx.load_cert_chain(A.cert, A.key)
srv.socket = ctx.wrap_socket(srv.socket, server_side=True)
srv.serve_forever()
