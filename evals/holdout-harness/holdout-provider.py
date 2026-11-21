#!/usr/bin/env python3
"""Per-arm provider wiring for the held-out arms (HOLDOUT-SPEC §5.6 M11; OPEN-12).

    holdout-provider.py config --model M --template T --out F   write the arm's opencode.json
    holdout-provider.py meta   --model M                        print {"host","header","builtin"} as JSON

The live grove plugin (~/.config/opencode/plugins/grove-gateway.js) is NOT loaded inside an arm (the arm
config has no plugins; the global tree is unreadable). So the arm config carries the provider definitions
itself, with the same endpoints the plugin uses:
  ai-gateway-misc  custom @ai-sdk/openai-compatible at https://ai-gateway.corp.mongodb.com/openai/v1, key header x-api-key
                   (plugin: providerTemplates[misc], CREDENTIAL_HEADER)
  fireworks-ai     opencode built-in, https://api.fireworks.ai/inference/v1 (the endpoint the opencode binary ships)
  github-copilot   opencode built-in, https://api.githubcopilot.com
The arm's apiKey is only the non-secret placeholder "placeholder:<provider>". The REAL credential is
added by the TLS proxy (holdout-proxy.py) from a 0600 file the sandbox cannot read.
"""
import argparse, json, re, sys

PROVIDERS = {
    "ai-gateway-misc": {"host": "ai-gateway.corp.mongodb.com", "base": "https://ai-gateway.corp.mongodb.com/openai/v1",
                        "npm": "@ai-sdk/openai-compatible", "name": "AI Gateway Misc",
                        "header": "x-api-key", "builtin": False},
    "fireworks-ai": {"host": "api.fireworks.ai", "base": "https://api.fireworks.ai/inference/v1",
                     "npm": None, "name": None, "header": "Authorization", "builtin": True},
    # Copilot models are served by the OpenAI-compatible chat route at the host root: /chat/completions
    # (verified: the route answers; /v1/chat/completions is 404 on the live host)
    "github-copilot": {"host": "api.githubcopilot.com", "base": "https://api.githubcopilot.com",
                       "npm": None, "name": None, "header": "Authorization", "builtin": True},
}


# ai-gateway-misc models: the gateway expects groveModelId in the request, not the catalog key. Values from
# the grove plugin catalog (the plugin builds { id: groveModelId, name: displayName } per model). Unknown key -> refuse.
MISC_MODELS = {
    "fw-deepseek-v4.1-flash": ("FW-DeepSeek-V4.1-Flash", "FW DeepSeek V4.1 Flash"),
    "fw-glm-5.3-flash": ("FW-GLM-5.3-Flash", "FW GLM 5.3 Flash"),
}


def split(model):
    prov, _, mid = model.partition("/")
    if prov not in PROVIDERS or not mid:
        sys.exit(f"holdout-provider: unsupported model namespace: {model!r} (allowed: {sorted(PROVIDERS)})")
    return prov, mid


def provider_block(model):
    prov, mid = split(model)
    p = PROVIDERS[prov]
    # no apiKey here: opencode must resolve the key from the arm's own auth.json copy (the plugin that normally
    # substitutes a placeholder is not loaded inside an arm, and a placeholder overrides the auth store)
    if prov == "ai-gateway-misc":
        if mid not in MISC_MODELS:
            sys.exit(f"holdout-provider: no groveModelId mapping for {mid!r} (add it from the grove catalog)")
        gid, disp = MISC_MODELS[mid]
        models = {mid: {"id": gid, "name": disp}}
    else:
        models = {mid: {"name": mid}}
    # github-copilot: NO baseURL override. Its Claude models use the catalog route (@ai-sdk/anthropic at /v1/messages,
    # verified: /v1/messages accepts claude-haiku-5.5 — the error is about messages, not the model). Overriding the base
    # changed the SDK path (404 at /messages, /v1/chat/completions) in earlier iterations.
    options = {} if prov == "github-copilot" else {"baseURL": p["base"]}
    entry = {"options": options, "models": models}
    if not p["builtin"]:
        entry = {"npm": p["npm"], "name": p["name"], **entry}
    return {prov: entry}


def write_config(model, template, out):
    doc = json.load(open(template))
    doc["model"] = model
    doc["provider"] = provider_block(model)
    import os
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w") as fh:
        json.dump(doc, fh, indent=2, sort_keys=True)
        fh.write("\n")


def strip_jsonc(text):
    """Comment-stripping for jsonc parse checks (string-aware, no trailing-comma support)."""
    out, i, n, in_str = [], 0, len(text), False
    while i < n:
        c = text[i]
        if in_str:
            out.append(c)
            if c == "\\":
                out.append(text[i + 1]); i += 2; continue
            if c == '"':
                in_str = False
        elif c == '"':
            in_str = True; out.append(c)
        elif text.startswith("//", i):
            while i < n and text[i] != "\n":
                i += 1
            continue
        elif text.startswith("/*", i):
            j = text.index("*/", i + 2); i = j + 2; continue
        else:
            out.append(c)
        i += 1
    return "".join(out)


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("config"); c.add_argument("--model", required=True)
    c.add_argument("--template", required=True); c.add_argument("--out", required=True)
    m = sub.add_parser("meta"); m.add_argument("--model", required=True)
    a = ap.parse_args()
    if a.cmd == "config":
        write_config(a.model, a.template, a.out)
    else:
        prov, _ = split(a.model)
        p = PROVIDERS[prov]
        print(json.dumps({"provider": prov, "host": p["host"], "header": p["header"], "builtin": p["builtin"]}))


if __name__ == "__main__":
    main()
