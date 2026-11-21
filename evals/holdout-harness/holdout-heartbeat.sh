#!/usr/bin/env bash
# holdout-heartbeat.sh <file> <interval-seconds> — liveness heartbeat for a poller (MINOR 6).
# Writes once immediately, then every interval. A dead poller stops updating the file.
set -u
f="$1"; iv="$2"
while :; do date +%s > "$f"; sleep "$iv"; done
