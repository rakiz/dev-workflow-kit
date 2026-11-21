#!/usr/bin/env bash
# holdout-arm.sh — per-arm directories, config, fixture copy and sandbox profile (HOLDOUT-SPEC §5.5/§5.6).
#   holdout-arm.sh prepare <title> <fixture dir> <proxy port>   -> creates dirs, copies fixture, writes profile
#   holdout-arm.sh paths   <title>                             -> prints the arm's dirs (sourceable)
#   holdout-arm.sh exec    <title> -- <cmd...>                 -> runs cmd under the arm's sandbox + env
# Egress is metered pass-through (owner amendment): the arm's own auth.json copy travels with the arm.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
REPO="$(cd "$HERE/../../.." && pwd)"          # ~/code_projects/IA-tooling
TMPBASE="$(cd "${TMPDIR:-/tmp}" && pwd -P)"   # realpath: sandbox rules use resolved paths
TMPBASE="${TMPBASE%/}"
GLOBAL_OC_DATA="$HOME/.local/share/opencode"
GLOBAL_OC_CFG="$HOME/.config/opencode"
HOST_AUTH="$HOME/.local/share/opencode/auth.json"

arm_paths() {
  local t="$1"
  ARM_WORK="$TMPBASE/holdout-work/$t"
  ARM_DATA="$TMPBASE/holdout-xdg/$t"            # XDG_DATA_HOME; DB at $ARM_DATA/opencode/opencode.db
  ARM_CFG="$TMPBASE/holdout-cfg/$t"             # XDG_CONFIG_HOME; opencode/opencode.json only
  ARM_TMP="$TMPBASE/holdout-tmp/$t"
  ARM_HOME="$TMPBASE/holdout-home/$t"
}

cmd_prepare() {
  local t="$1" fixture="$2" port="$3"
  arm_paths "$t"
  for d in "$ARM_WORK" "$ARM_DATA" "$ARM_CFG" "$ARM_TMP" "$ARM_HOME"; do
    [ -e "$d" ] && { echo "refusing: arm dir exists: $d (arms are single-use)" >&2; exit 1; }
  done
  mkdir -p "$(dirname "$ARM_WORK")" "$(dirname "$ARM_DATA")" "$(dirname "$ARM_CFG")" \
           "$(dirname "$ARM_TMP")" "$(dirname "$ARM_HOME")"
  mkdir -p "$ARM_DATA/opencode" "$ARM_CFG/opencode" "$ARM_TMP" "$ARM_HOME"
  # fixture copy happens OUTSIDE the sandbox, before the profile is applied (M-n)
  cp -R "$fixture" "$ARM_WORK"
  find "$ARM_WORK" -name __pycache__ -prune -exec rm -rf {} + 2>/dev/null || true
  # per-arm config: rails template + the arm's provider block only (M11, OPEN-12); no plugins, MCP empty
  python3 -B "$HERE/holdout-provider.py" config --model "${ARM_MODEL:?ARM_MODEL required}" \
    --template "$REPO/evals-keys/holdout-config-template.json" --out "$ARM_CFG/opencode/opencode.json"
  # the campaign CA certificate (public) is the only TLS trust the arm gets (OPEN-1)
  cp "${HOLDOUT_CAMP_DIR:?HOLDOUT_CAMP_DIR required}/ca.pem" "$ARM_CFG/ca.pem"
  # owner amendment: the arm carries its own COPY of opencode's auth store (its plugin refreshes OAuth itself)
  if [ -f "$HOST_AUTH" ]; then
    cp "$HOST_AUTH" "$ARM_DATA/opencode/auth.json" && chmod 600 "$ARM_DATA/opencode/auth.json"
  fi
  # the arm's proxy port is fixed at prepare time: exec reads it back, never from ambient env (EPERM fix)
  printf '%s\n' "$port" > "$ARM_TMP/proxy.port"
  # profile
  sed -e "s|{{ARM_TMP}}|$ARM_TMP|g" -e "s|{{ARM_WORK}}|$ARM_WORK|g" -e "s|{{ARM_DATA}}|$ARM_DATA|g" \
      -e "s|{{ARM_CFG}}|$ARM_CFG|g" -e "s|{{ARM_HOME}}|$ARM_HOME|g" -e "s|{{PROXY_PORT}}|$port|g" \
      -e "s|{{REPO}}|$REPO|g" -e "s|{{CAMP_DIR}}|$HOLDOUT_CAMP_DIR|g" -e "s|{{GLOBAL_OPENCODE_DATA}}|$GLOBAL_OC_DATA|g" \
      -e "s|{{GLOBAL_OPENCODE_CONFIG}}|$GLOBAL_OC_CFG|g" -e "s|{{HOST_AUTH}}|$HOST_AUTH|g" \
      "$HERE/sandbox.sb.tmpl" > "$ARM_TMP/profile.sb"
  echo "prepared $t"
}

cmd_paths() { arm_paths "$1"; printf 'ARM_WORK=%q\nARM_DATA=%q\nARM_CFG=%q\nARM_TMP=%q\nARM_HOME=%q\n' "$ARM_WORK" "$ARM_DATA" "$ARM_CFG" "$ARM_TMP" "$ARM_HOME"; }

cmd_exec() {
  local t="$1"; shift; [ "${1:-}" = "--" ] && shift
  arm_paths "$t"
  # cd into the arm work dir: the sandbox's (deny default) makes getcwd EPERM
  # when the invoking cwd is outside the allow-list (Bun: "EPERM: process.cwd").
  cd "$ARM_WORK"
  local port; port="$(cat "$ARM_TMP/proxy.port")"
  exec env -i PATH=/usr/bin:/bin:/opt/homebrew/bin HOME="$ARM_HOME" TMPDIR="$ARM_TMP" \
      XDG_DATA_HOME="$ARM_DATA" XDG_CONFIG_HOME="$ARM_CFG" XDG_CACHE_HOME="$ARM_TMP/cache" \
      XDG_STATE_HOME="$ARM_TMP/state" HTTPS_PROXY="http://127.0.0.1:$port" \
      HTTP_PROXY="http://127.0.0.1:$port" NO_PROXY="" \
      NODE_EXTRA_CA_CERTS="$ARM_CFG/ca.pem" SSL_CERT_FILE="$ARM_CFG/ca.pem" \
      sandbox-exec -f "$ARM_TMP/profile.sb" "$@"
}

case "${1:-}" in
  prepare) shift; cmd_prepare "$@" ;;
  paths)   shift; cmd_paths "$@" ;;
  exec)    shift; cmd_exec "$@" ;;
  *) echo "usage: holdout-arm.sh prepare|paths|exec ..." >&2; exit 2 ;;
esac
