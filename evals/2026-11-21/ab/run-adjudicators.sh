#!/usr/bin/env bash
cd "$(dirname "$0")"
./run-adj.sh adj-neon github-copilot/gemini-4-neon
./run-adj.sh adj-qwen fireworks-ai/accounts/fireworks/models/qwen3p8-2p4t-a95b
echo "ADJUDICATION DONE"
