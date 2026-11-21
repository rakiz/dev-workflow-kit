#!/usr/bin/env bash
# reconciliation round (AB-SPEC §3): both adjudicators re-score the single flagged cell under the frozen prompt
cd "$(dirname "$0")"
./run-adj.sh recon-neon github-copilot/gemini-4-neon
./run-adj.sh recon-qwen fireworks-ai/accounts/fireworks/models/qwen3p8-2p4t-a95b
echo "RECON DONE"
