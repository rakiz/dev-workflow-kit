#!/usr/bin/env python3
"""Étape 4 adjudication, step 1 (AB-SPEC §3, §6): build the blinded bundle and the two adjudicator folders.
    adjudicate.py build    -> KEYS/adj/bundles/blind/<id>/ (15 cells), KEYS/adj/adj-{neon,qwen}/ (ORDER.txt, PROMPT.md)
Vendor/model/agent names are stripped from REPORT.md and text files; paths carry only the ID; the build aborts
if any vendor token survives (grep over the bundle)."""
import os, re, shutil, sys
HERE = os.path.dirname(os.path.abspath(__file__))
KEYS = os.path.realpath(os.path.join(HERE, "..", "..", "..", "..", "evals-keys", "ab-2026-11-21"))
TASKS = os.path.join(HERE, "tasks")
CELLS = os.path.join(KEYS, "cells")
VENDOR = re.compile(r"claude|sonnet|haiku|opus|minimax|deepseek|gemini|qwen|neon|argon|grok|fireworks|copilot|"
                    r"opencode|anthropic|xhigh|--variant|--agent|cheap-(?:code|review|mech|design|design-review)|"
                    r"strong-(?:code|review|design|code-alternative)", re.I)
TEXT = (".md", ".py", ".txt", ".csv", ".json", ".sh", ".tsv", ".cfg")
ARM_ORDER = {  # AB-SPEC §3 exact presentation arrays
    "J1": {1: "ABC", 2: "BCA", 3: "CAB", 4: "ABC", 5: "BCA"},
    "J2": {1: "CBA", 2: "ACB", 3: "BAC", 4: "CBA", 5: "ACB"},
}
ADJ = {"adj-neon": "J1", "adj-qwen": "J2"}
def load_ids():
    ids = {}
    for line in open(os.path.join(KEYS, "id-map.tsv")):
        if line.startswith("task"): continue
        t, a, bid = line.rstrip("\n").split("\t"); ids[(t, a)] = bid
    return ids
def sanitize_text(path):
    with open(path, encoding="utf-8", errors="replace") as fh: txt = fh.read()
    with open(path, "w", encoding="utf-8") as fh: fh.write(VENDOR.sub("[REDACTED]", txt))
def copy_tree(src, dst):
    shutil.copytree(src, dst, ignore=shutil.ignore_patterns("__pycache__", "session-*.log", "REVIEW*.md", "out", "*.pyc"))
def build():
    ids = load_ids(); bundles = os.path.join(KEYS, "adj", "bundles", "blind")
    if os.path.exists(os.path.join(KEYS, "adj")): shutil.rmtree(os.path.join(KEYS, "adj"))
    os.makedirs(bundles)
    for (t, a), bid in sorted(ids.items()):
        task = int(t.lstrip("T")); cell = os.path.join(CELLS, f"{a}-{t}")
        if not os.path.isdir(cell): raise SystemExit(f"missing cell {cell}")
        b = os.path.join(bundles, bid); os.makedirs(b)
        copy_tree(cell, os.path.join(b, "tree"))
        shutil.copy(os.path.join(cell, "REPORT.md"), os.path.join(b, "REPORT.md")); sanitize_text(os.path.join(b, "REPORT.md"))
        shutil.copy(os.path.join(TASKS, t, "start", "TASK.md"), os.path.join(b, "DOD.md"))
        copy_tree(os.path.join(TASKS, t, "start"), os.path.join(b, "baseline"))
        req = os.path.join(b, "required"); os.makedirs(req)
        rq = os.path.join(KEYS, "required", t)
        if t == "T4":
            shutil.copy(os.path.join(rq, "run_t4.py"), req); shutil.copy(os.path.join(rq, "mutant_M.py"), req)
        else:
            shutil.copy(os.path.join(rq, "test_required.py"), req)
        for root, _, files in os.walk(b):
            for f in files:
                if f.endswith(TEXT): sanitize_text(os.path.join(root, f))
        with open(os.path.join(b, "README.txt"), "w") as fh:
            fh.write("Bundle contents: tree/ REPORT.md DOD.md required/ baseline/\n")
    leak = os.popen(f"grep -rliE '{VENDOR.pattern}' '{bundles}' | head -5").read().strip()
    if leak: raise SystemExit("vendor leak in bundle:\n" + leak)
    for adj, order_key in ADJ.items():
        d = os.path.join(KEYS, "adj", adj); os.makedirs(d)
        shutil.copytree(bundles, os.path.join(d, "blind"))
        seq = []
        for task in range(1, 6):
            for arm in ARM_ORDER[order_key][task]:
                seq.append(ids[(f"T{task}", arm)])
        with open(os.path.join(d, "ORDER.txt"), "w") as fh: fh.write("\n".join(seq) + "\n")
        shutil.copy(os.path.join(KEYS, "prompts", "ADJ-PROMPT.md"), os.path.join(d, "PROMPT.md"))
        print(adj, order_key, len(seq), "cells in order")
    print("bundles:", len(os.listdir(bundles)), "clean of vendor tokens")
if __name__ == "__main__":
    if sys.argv[1:] == ["build"]: build()
    else: raise SystemExit("usage: adjudicate.py build")
