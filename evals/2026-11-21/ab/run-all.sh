#!/usr/bin/env bash
# run-all.sh — arms A, then B, then C (sequential: budget-safe under the $25 hard cap)
cd "$(dirname "$0")"
for arm in A B C; do python3 -u run-ab.py $arm; done
echo "ALL ARMS DONE" 
