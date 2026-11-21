#!/usr/bin/env bash
# holdout-ca.sh <campaign dir> <host> [host...] — one CA per campaign plus one leaf per allowlisted host.
#   ca.key            0600, the CA private key. Lives in the campaign dir only: never copied into an arm,
#                     never inside a sandbox-readable path (the sandbox also denies the campaign dir).
#   ca.pem            public CA certificate. Copied into each arm's config dir (read-only inside the sandbox).
#   <host>.key/.pem   leaf key (0600) and leaf cert (SAN = host) signed by ca.key.
# Idempotent: existing files are kept, so one campaign keeps one CA.
set -euo pipefail
DIR="$1"; shift
umask 077
mkdir -p "$DIR"; chmod 700 "$DIR"
if [ ! -f "$DIR/ca.key" ]; then
  openssl genrsa -out "$DIR/ca.key" 2048 2>/dev/null
  chmod 600 "$DIR/ca.key"
  openssl req -x509 -new -key "$DIR/ca.key" -sha256 -days 2 -subj "/CN=holdout-campaign-ca" \
    -addext "basicConstraints=critical,CA:TRUE" -addext "keyUsage=critical,keyCertSign,cRLSign" \
    -out "$DIR/ca.pem" 2>/dev/null
fi
for host in "$@"; do
  [ -f "$DIR/$host.pem" ] && continue
  openssl genrsa -out "$DIR/$host.key" 2048 2>/dev/null
  chmod 600 "$DIR/$host.key"
  openssl req -new -key "$DIR/$host.key" -subj "/CN=$host" -out "$DIR/$host.csr" 2>/dev/null
  printf 'subjectAltName=DNS:%s\nbasicConstraints=CA:FALSE\nkeyUsage=digitalSignature,keyEncipherment\nextendedKeyUsage=serverAuth\n' "$host" > "$DIR/$host.ext"
  openssl x509 -req -in "$DIR/$host.csr" -CA "$DIR/ca.pem" -CAkey "$DIR/ca.key" -CAcreateserial \
    -days 2 -sha256 -extfile "$DIR/$host.ext" -out "$DIR/$host.pem" 2>/dev/null
  rm -f "$DIR/$host.csr" "$DIR/$host.ext"
done
rm -f "$DIR"/*.srl
echo "campaign CA ready: $DIR"
