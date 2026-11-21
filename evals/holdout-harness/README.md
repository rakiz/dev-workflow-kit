# holdout-harness — isolation, egress metering and provider wiring for held-out arms

Scope: HOLDOUT-SPEC §5.5–§5.7. Nothing here calls a model except `preflight.sh --live`, which runs only on
the owner's authorisation (about $0.001 for A6, plus one GET for the live A8).

## Files

| File | Role |
|---|---|
| `sandbox.sb.tmpl` | sandbox-exec profile: default-deny, per-arm allow-lists, explicit denies after the allows |
| `holdout-arm.sh` | per-arm dirs; config; campaign CA copy; the arm's own `auth.json` copy; fixture copy outside the sandbox; sandboxed exec with env |
| `holdout-provider.py` | per-arm `opencode.json` provider block (OPEN-12) and provider metadata (host) |
| `holdout-ca.sh` | one CA per campaign (`ca.key` 0600) and one leaf cert per provider host |
| `holdout-proxy.py` | TLS-terminating egress proxy: allowlist, pass-through, per-arm meter, byte cap |
| `holdout-stub-upstream.py` | self-test only: a TLS stub that reports whether it received the expected header |
| `preflight.sh` | the fail-closed assertions (A1–A8; `--live` adds A6 and the live A8) |
| `selftest-sandbox.sh`, `selftest-harness.py` | zero-cost self-tests |
| `drive-holdout.sh` | builds the campaign file, creates the campaign CA, runs preflight, calls `run-campaign.py` |

## Egress: pass-through with metering (owner amendment; M10 replaced)

Decision: the proxy does **not** inject or rewrite credentials. Reason: GitHub Copilot's OAuth refresh
runs inside opencode's own plugin, and static injection breaks it. The sandbox cannot discriminate
file reads per process, so the arm's own copy of opencode's auth store is the credential path.

1. The arm's runtime gets `HTTPS_PROXY=http://127.0.0.1:<port>`. The sandbox allows outbound only to that
   port, so direct connections fail.
2. The proxy accepts `CONNECT host:443` only for the arm's provider host. Everything else gets 403, and the
   refusal is metered (`denied`).
3. The proxy terminates TLS with the host's leaf cert, signed by the **campaign CA**. The arm trusts only
   that CA (see below). TLS termination is needed for metering: without it the request bytes are opaque.
4. The request is **forwarded as-is** upstream, including `Authorization` and `x-api-key`. Only hop-by-hop
   headers are dropped and `Connection: close` is forced on both legs.
5. The meter records connects, requests, and bytes up and down, per arm, in `holdout-tmp/<title>/proxy.json`.
   Past `--cap-bytes`, new tunnels get 429.

**The meter is the only egress budget.** The per-arm poller in `run-campaign.py` kills an arm whose meter
exceeds `HOLDOUT_BYTE_CAP` (default 200 MB). The campaign kill poller sums the meters of all held-out arms
and stops the campaign past `HOLDOUT_CAMPAIGN_BYTE_CAP` (default 2 GB). Bytes are a proxy for cost, not
dollars: the USD cap is still enforced from the per-arm DB, and tokens are inside TLS.

What is readable inside the arm sandbox:

| Item | Readable inside? | Why |
|---|---|---|
| The arm's own `auth.json` copy (in its data dir) | Yes | owner amendment: opencode's plugin refreshes OAuth from it |
| Host `~/.local/share/opencode/auth.json` | No | global opencode data dir is denied |
| Campaign CA private key (`ca.key`) | No | campaign dir is denied |
| Campaign CA certificate (`ca.pem`, a copy in the arm config dir) | Yes | public; the only TLS trust the arm gets |

The proxy refuses to start if `ca.key` is not mode 0600, or if the campaign dir lies under an arm directory.

## Why both CA variables are set in the arm env

`NODE_EXTRA_CA_CERTS` and `SSL_CERT_FILE` both point at the arm's copy of the campaign `ca.pem`. The arm's
runtime is Bun, and its SDKs use Node-compatible TLS, so each code path may read a different variable.

- `SSL_CERT_FILE` replaces the trust bundle of OpenSSL-linked code. **Verified here:** with it set to the
  campaign CA, `/usr/bin/curl` trusts the campaign CA. With a clean env it does not (rc 60).
- `NODE_EXTRA_CA_CERTS` adds the campaign CA on top of the default trust. It is the variable Node-based SDK
  clients read. **Not verified here:** that the Bun build of opencode honours it. The live A8 must confirm it.

**Expected failure mode (not yet observed):** if a runtime ignores a variable, its TLS to the proxy fails
with an unknown-issuer error. The arm then fails closed, because the sandbox blocks every other route. A
runtime that ignores both fails the handshake the same way. The live A8 and the first live arm are where
this would show up.

## Preflight assertions

- **A1–A5:** sandbox denies, each with an outside-the-sandbox control. A5 also checks that the arm's own
  `auth.json` copy is present.
- **A6 (live):** one trivial run; exit 0; per-arm DB written; proxy requests > 0.
- **A7a/A7b:** heartbeats for the per-arm poller and the campaign kill poller.
- **A8s (non-live, pass-through):**
  - (a) a non-allowlisted host from inside the sandbox is refused, and the meter's `denied` counter rises;
  - (b) an allowlisted host (stub upstream) receives the client's own bogus `Authorization` header as-is.
    The stub answers `AUTH-OK`, and the meter's request and byte counts rise.
- **A8 (live):** a plain GET to the real provider root with a bogus key, through the proxy, with no model call.
  TLS must verify against the campaign CA, the public trust store must not verify the same chain (host-side,
  clean env), and the request must reach the provider (any HTTP status).

## Provider wiring (OPEN-12)

The live grove plugin is not loaded inside an arm. `holdout-provider.py` writes the provider block itself,
with the endpoints from the plugin and the opencode binary:

| Namespace | Endpoint | Credential header | Kind |
|---|---|---|---|
| `ai-gateway-misc` | `https://ai-gateway.corp.mongodb.com/openai/v1` | `x-api-key` | custom, `@ai-sdk/openai-compatible` |
| `fireworks-ai` | `https://api.fireworks.ai/inference/v1` | `Authorization` | built-in |
| `github-copilot` | `https://api.githubcopilot.com` | `Authorization` | built-in (OAuth, refreshed by opencode) |

The arm config sets **no** `apiKey`. A placeholder overrides opencode's auth store, and the plugin that would
substitute it is not loaded inside an arm, so opencode must read the key from the arm's own `auth.json` copy.

## Known limits (open)

- The live A6/A8 paths have not run; they need the owner's go.
- The Copilot model id in the built-in catalog is not verified live.
- Metering counts bytes, not provider tokens.
