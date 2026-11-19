#!/usr/bin/env python3
"""Extract eval run artifacts from logs, run dirs and the opencode DB.

Sources (2026-11-17 cleanup brief):
  (a) evals/2026-11-16/raw/grid2/ run dirs
  (b) evals/2026-11-16/scratch/  (snapshot of $TMPDIR; mapped to runs via the
      "run dir:" line of each log in logs/ and logs/grid2/)
  (c) evals/2026-11-12/raw-round2/*-p3/p4 (bench-v3 round-2 pilot, RG3/D1)
  (d) opencode DB (sqlite3 -readonly, title-keyed queries only; the DB is 50 GB,
      message/part are only ever touched through a session_id) for the final
      assistant messages of the IV2-RG3 and D-D1 sessions and the per-run
      scorer-session outputs.

Outputs:
  evals/2026-11-16/runs/            per-run artifacts:
      O   -> <run>.plan.md      (deliverable text)
      IR  -> <run>.review.md
      DR2 -> <run>.critique.md
      I2  -> <run>.diff (+ <run>.report.md, final assistant message)
      D   -> <run>.design.md (DESIGN-d1.md) + <run>.report.md
  evals/2026-11-16/grid2-run-scores.tsv   one row per log / run dir
  evals/2026-11-16/grid2-costs.tsv        regenerated, ALL eval-2026-11-13..17
      titles, cost = parent + delegated children (parent_id roll-up).

Fail-closed: any run that cannot be reconciled (no session, no scorer output,
no DNF evidence) is emitted as status=orphan and the script exits non-zero.
Never invents data: scores come only from scorer-session outputs; DNF reasons
only from arm-kill markers in logs or scorer DNF lines.

Idempotent: a second run over the same sources produces a zero diff.
"""

import csv
import glob
import gzip
import json
import os
import re
import subprocess
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
BASE = os.path.join(ROOT, "2026-11-16")
RUNS = os.path.join(BASE, "runs")
ROUND2 = os.path.join(ROOT, "2026-11-12", "raw-round2")
PRISTINE_I2 = os.path.join(ROOT, "reportgen-eval-repo-i3")   # RG3 (archived protocol)
PRISTINE_I4 = os.path.join(ROOT, "reportgen-eval-repo-i4")   # RG4 (Étape 1, policy A)
OC_DB = os.path.expanduser("~/.local/share/opencode/opencode.db")

# runner code / session-title bench -> decision bench code
BENCH_CODE = {"T1": "O", "T3": "IR", "T4V2": "DR2", "IV2": "I2", "D1": "D",
              "D": "D", "O": "O", "IR": "IR", "DR2": "DR2", "I2": "I2",
              "IV2-RG3": "I2", "IV2-RG4": "I2", "IV2-RG2": "I2", "D-D1": "D",
              "T2": "I-v1", "T4": "DR-v1"}
LEGACY_BENCHES = {"O", "IR", "DR2"}
EFFORTS = {"default", "low", "medium", "high", "xhigh"}
PROVIDERS = ["fireworks-ai-accounts-fireworks-models", "github-copilot",
             "ai-gateway-anthropic", "ai-gateway-misc", "ai-gateway-openai"]

# run slug (dots for version numbers) -> grid2-scores.csv model name
SLUG_TO_CSV = {
    "claude-haiku-5.5": "haiku", "haiku": "haiku",
    "fw-glm-5.3-flash": "glm", "glm": "glm",
    "fw-deepseek-v4.1-flash": "dsflash",
    "deepseek-v4p1-flash-1017": "1017", "1017": "1017",
    "minimax-m3p1-flash": "minimax",
    "qwen3p8-2p4t-a95b": "qwen",
    "gemini-4-hydrogen": "hydrogen",
    "gemini-4-argon": "argon",
    "gemini-4-carbon": "carbon",
    "gemini-3.8-flash": "gem38",
    "gpt-6.1-terra": "terra",
    "gpt-6.1-sol": "sol",
    "muse-spark-open": "muse",
    "kimi-k3p1-pro": "kimi",
    "claude-sonnet-5.5": "sonnet",
    "claude-opus-5.5": "opus",
    "claude-fable-5": "fable",
    "gpt-6-astra": "astra",
}

# Owner-validated per-run scores for the glm O confirmation runs (2026-11-17):
# g31 = 5/8, g32 = 6/8; together with the 10-16 re-scored run (7) they give the
# frozen cell mean (7+5+6)/3 = 6 in grid2-scores.csv. The notes column carries
# the rubric breakdown / FLAG for each run.
OWNER_FREEZE_SCORES = {
    "O-glm-high-g31": ("5", "base=2 ground=1 agents=1 crit=1; FLAG: unexecuted "
                            'verification claim "grep shows no callers"'),
    "O-glm-high-g32": ("6", "base=1 ground=2 agents=2 crit=1"),
}

_cache = {}


def q(sql):
    r = subprocess.run(["sqlite3", "-readonly", OC_DB, sql],
                       capture_output=True, text=True)
    if r.returncode != 0:
        sys.exit("FATAL: sqlite query failed: %s\n%s" % (sql[:120], r.stderr))
    return r.stdout


def strip_ansi(t):
    return re.sub(r"\x1b\[[0-9;]*m", "", t)


def read_text(path):
    """Read a (possibly gzipped) text file."""
    if path.endswith(".gz"):
        with gzip.open(path, "rt", encoding="utf-8", errors="replace") as f:
            return f.read()
    return open(path, encoding="utf-8", errors="replace").read()


# ------------------------------------------------------------ identifiers --
def title_parts(title):
    """'eval-2026-11-16-IV2-RG3-<prov>-<model>-<effort?>-<tag>' -> parts or None."""
    m = re.match(r"eval-\d{4}-\d{2}-\d{2}-(.+)", title)
    if not m:
        return None
    rest = m.group(1)
    bench = None
    for code in ("IV2-RG4", "IV2-RG3", "IV2-RG2", "D-D1", "T1", "T2", "T3", "T4V2", "T4"):
        if rest.startswith(code + "-"):
            bench = code
            rest = rest[len(code) + 1:]
            break
    if bench is None:
        return None
    toks = rest.split("-")
    tag = ""
    if toks and toks[-1] not in EFFORTS:
        tag = toks[-1]
        toks = toks[:-1]
    effort = "default"
    if toks and toks[-1] in EFFORTS:
        effort = toks[-1]
        toks = toks[:-1]
    for p in PROVIDERS:
        pfx = p.split("-")
        if len(toks) > len(pfx) and toks[:len(pfx)] == pfx:
            toks = toks[len(pfx):]
            break
    slug = "-".join(toks) if toks else ""
    return {"bench": bench, "slug": slug, "effort": effort, "tag": tag}


def run_id_parts(run_id):
    """'<BENCH>-<slug>-<effort>[-<tag>]' -> (bench, csv_model, effort, tag)."""
    toks = run_id.split("-")
    bench = BENCH_CODE.get(toks[0], toks[0])
    tag = ""
    if toks and toks[-1] not in EFFORTS:
        tag = toks[-1]
        toks = toks[:-1]
    effort = "default"
    if toks and toks[-1] in EFFORTS:
        effort = toks[-1]
        toks = toks[:-1]
    raw_slug = "-".join(toks[1:])
    slug = re.sub(r"(\d)-(\d)", r"\1.\2", raw_slug).replace("_", ".")
    model = (SLUG_TO_CSV.get(raw_slug.replace("_", "."))
             or SLUG_TO_CSV.get(slug))
    return bench, model or _csv_model_of_slug(raw_slug), effort, tag


def stem_run_id(stem):
    """Canonical run id from a log stem (legacy runner prefixes converted)."""
    m = re.match(r"(IV2|D1|T1|T2|T3|T4V2|T4|O|IR|DR2|I2|D)-(.+)", stem)
    if not m:
        return stem
    code, rest = m.groups()
    bench = BENCH_CODE[code]
    toks = rest.split("-")
    tag = ""
    if toks and toks[-1] not in EFFORTS:
        tag = toks[-1]
        toks = toks[:-1]
    effort = "default"
    if toks and toks[-1] in EFFORTS:
        effort = toks[-1]
        toks = toks[:-1]
    for p in PROVIDERS:
        pfx = p.split("-")
        if len(toks) > len(pfx) and toks[:len(pfx)] == pfx:
            toks = toks[len(pfx):]
            break
    slug = "-".join(toks)
    rid = "%s-%s-%s" % (bench, slug, effort)
    if tag:
        rid += "-" + tag
    return rid


# ---------------------------------------------------------------- sessions --
def load_eval_sessions():
    """title -> row, for eval-2026-11-13..17 sessions."""
    sessions = {}
    cond = " OR ".join("title LIKE 'eval-2026-11-%s%%'" % d
                       for d in ("13", "14", "15", "16", "17"))
    rows = q("SELECT id, title, directory, model FROM session WHERE %s;" % cond)
    for line in rows.splitlines():
        id_, title, directory, model = line.split("|", 3)
        m = re.search(r'"providerID":"([^"]+)"', model)
        mm = re.search(r'"id":"([^"]+)"', model)
        mv = re.search(r'"variant":"([^"]+)"', model)
        sessions[title] = {
            "id": id_, "title": title, "directory": directory,
            "provider": m.group(1) if m else "",
            "model_id": (mm.group(1) if mm else "").split("/")[-1],
            "variant": mv.group(1) if mv else "",
        }
    return sessions


def final_assistant_text(session_id):
    key = "text:" + session_id
    if key in _cache:
        return _cache[key]
    out = []
    rows = q("SELECT id, data FROM message WHERE session_id='%s' "
             "ORDER BY time_created;" % session_id)
    final = None
    for line in rows.splitlines():
        mid, data = line.split("|", 1)
        if json.loads(data).get("role") == "assistant":
            final = mid
    if final:
        parts = q("SELECT data FROM part WHERE message_id='%s' "
                  "ORDER BY time_created;" % final)
        for line in parts.splitlines():
            d = json.loads(line)
            if d.get("type") == "text" and d.get("text"):
                out.append(d["text"])
    text = "\n".join(out).strip() + "\n" if out else ""
    _cache[key] = text
    return text


# ------------------------------------------------------------------- logs ---
CHROME = re.compile(r"^(?:→|✓|•|\$|!|\?|> build ·)")


def parse_log(path):
    """-> dict(stem, path, title, run_dir, arm_kill) or None for driver logs."""
    stem = re.sub(r"\.log(\.gz)?$", "", os.path.basename(path))
    t = strip_ansi(read_text(path))
    titles = [t.rstrip(")").replace(" above", "")
              for t in re.findall(r"session title (\S+)", t)]
    rdirs = re.findall(r"run dir: \S*?(bench-v3-[\w-]+)", t)
    arm_kill = None
    m = re.search(r"arm-killed-(timeout|costcap)", t)
    if m:
        arm_kill = m.group(1)
    prov_error = bool(re.search(r"The model does not exist|"
                                r"Failed to process successful response|"
                                r"ECONNRESET", t))
    if not titles and not rdirs:
        return None  # driver log (_campaign*.log)
    return {"stem": stem, "path": path, "title": titles[-1] if titles else "",
            "run_dir": rdirs[-1] if rdirs else "", "arm_kill": arm_kill,
            "prov_error": prov_error}


def build_log_text(log):
    """Fallback deliverable text from a legacy-bench log: after the last
    chrome (tool-call / prompt) line, trailing runner noise removed."""
    t = strip_ansi(read_text(log["path"]))
    lines = t.splitlines()
    cut = len(lines)
    for i in range(len(lines) - 1, -1, -1):
        if lines[i].startswith("run dir:"):
            cut = i
            break
    lines = lines[:cut]
    while lines and (not lines[-1].strip() or "Terminated" in lines[-1]):
        lines.pop()
    start = 0
    for i, l in enumerate(lines):
        if CHROME.match(l):
            start = i + 1
    body = "\n".join(lines[start:]).strip()
    return body + "\n" if body else ""


# ------------------------------------------------------------------ scorer --
SHORT_SLUGS = {"haiku", "glm", "terra", "argon", "carbon", "hydrogen",
               "minimax", "muse", "kimi", "opus", "sonnet", "fable", "astra",
               "sol", "qwen", "1017"}


def _csv_model_of_slug(slug):
    if not slug:
        return ""
    if slug in SLUG_TO_CSV:
        return SLUG_TO_CSV[slug]
    if slug in SHORT_SLUGS:
        return slug
    for tok in re.split(r"[-._]", slug):
        if tok in SHORT_SLUGS:
            return tok
    return ""


def load_scorer_scores():
    """Scorer evidence, indexed three ways for robust lookup.

    Returns (by_key, by_tuple):
      by_key:    literal run key (bench-v3 dir basename or log stem) ->
                 (score, dnf_reason)
      by_tuple:  (bench_code, csv_model_or_'', effort, tag) -> list of
                 (score, dnf_reason) — literal keys normalized.
    """
    entries = []  # (list of literal keys, bench, model, effort, tag, score, dnf)
    titles = q("SELECT title FROM session WHERE title LIKE '%scor%' "
               "COLLATE NOCASE;").splitlines()
    key_re = re.compile(r"(bench-v3-[\w-]+)")
    stem_re = re.compile(
        r"\b((?:O|IR|DR2|I2|D|T1|T2|T3|T4V2|IV2|D1)-[A-Za-z0-9_.\-]+?)"
        r"(?=\t|$)")
    score_re = re.compile(r"^-?\d+(?:\.\d+)?(?:/\d+)?$")
    header_re = re.compile(r"^\s*(?:Arm|ARM):\s*(\S+)|^#\s*SCORE SHEET —\s*(\S+)")
    inline_re = re.compile(
        r"^(?:#{0,6}\s*)?(?:-\s*)?\**(?:ARM\s*\d*\s*:?\s*)?"
        r"((?:O|IR|DR2|I2|D|T1|T2|T3|T4V2|IV2|D1)-[A-Za-z0-9_.\-]+?)"
        r"\s*(?:[—–-]+\s*)?:?\s*\**\s*TOTAL:?\s*\**\s*(-?\d+(?:\.\d+)?)", re.I)
    total_re = re.compile(r"^\s*(?:##\s*)?\**TOTAL:?\**\s+(-?\d+(?:\.\d+)?)(?:\s*/\s*\d+)?")
    score_line_re = re.compile(r"^\**SCORE:?\**:?\**\s*(-?\d+(?:\.\d+)?)(?:\s*/\s*\d+)?",
                               re.I)
    for line_title in titles:
        safe = line_title.replace("'", "''")
        sids = q("SELECT id FROM session WHERE title='%s' ORDER BY "
                 "time_created;" % safe).splitlines()
        title_model = ""
        for tok in re.split(r"[\s\-]+", line_title.lower()):
            if tok in SHORT_SLUGS:
                title_model = tok
                break
        for sid in sids:
            text = final_assistant_text(sid).replace("−", "-")
            block = None  # [keys, bench, model, effort, tag, score, dnf]

            def flush():
                if block and block[0] and (block[5] or block[6]):
                    entries.append(block)

            for line in text.splitlines():
                im = inline_re.match(line)
                if im:
                    key = re.sub(r"\.log$", "", im.group(1))
                    rid = stem_run_id(key)
                    b, m, e, t = run_id_parts(rid)
                    model = m or _csv_model_of_slug(key)
                    entries.append([[key], b, model, e, t, im.group(2), ""])
                    block = None
                    continue
                hm = header_re.match(line)
                if hm:
                    flush()
                    key = re.sub(r"\.log$", "", hm.group(1) or hm.group(2))
                    rid = stem_run_id(key)
                    b, m, e, t = run_id_parts(rid)
                    model = m or _csv_model_of_slug(key)
                    dnf0 = ""
                    if re.search(r"DNF", line, re.I):
                        low = line.lower()
                        if "timeout" in low:
                            dnf0 = "timeout"
                        elif "cost" in low:
                            dnf0 = "costcap"
                        else:
                            dnf0 = "provider-error"
                    block = [[key], b, model, e, t, "", dnf0]
                    continue
                mt = total_re.match(line)
                if mt and block:
                    if not re.search(r"DNF", line, re.I):
                        block[5] = block[5] or mt.group(1)
                    else:
                        block[6] = block[6] or "no-deliverable"
                    continue
                ms = score_line_re.match(line)
                if ms and block:
                    block[5] = block[5] or ms.group(1)
                    continue
                if block and re.search(r"DNF", line, re.I) and not block[5]:
                    low = line.lower()
                    if "timeout" in low:
                        block[6] = block[6] or "timeout"
                    elif "costcap" in low or "cost-cap" in low or \
                            "cost cap" in low:
                        block[6] = block[6] or "costcap"
                    elif "deliverable" in low or "no-change" in low or \
                            "no design" in low or "no edits" in low:
                        block[6] = block[6] or "no-deliverable"
                    elif "reset" in low or "error" in low or "dead" in low:
                        block[6] = block[6] or "provider-error"
                    else:
                        block[6] = block[6] or "no-deliverable"
                    continue
                if "\t" not in line:
                    continue
                mkey = key_re.search(line) or stem_re.search(line)
                if not mkey:
                    continue
                key = re.sub(r"\.log$", "", mkey.group(1))
                dnf = ""
                if re.search(r"DNF|arm-killed", line, re.I):
                    low = line.lower()
                    if "timeout" in low:
                        dnf = "timeout"
                    elif "costcap" in low or "cost-cap" in low:
                        dnf = "costcap"
                    elif "deliverable" in low or "no-change" in low:
                        dnf = "no-deliverable"
                    elif "reset" in low or "error" in low:
                        dnf = "provider-error"
                    else:
                        dnf = "no-deliverable"
                score = ""
                for field in line.split("\t"):
                    field = field.strip()
                    if score_re.match(field):
                        score = field.split("/")[0]
                        break
                rid = stem_run_id(key)
                b, m, e, t = run_id_parts(rid)
                wildcard = "..." in key
                model = "" if wildcard else (m or _csv_model_of_slug(key))
                if not model and title_model:
                    model = title_model
                elif wildcard and title_model:
                    model = title_model
                entries.append([[key], b, model, e, t, score, dnf])
            flush()

    by_key, by_tuple = {}, {}
    for keys, b, m, e, t, score, dnf in entries:
        for k in keys:
            by_key.setdefault(k, (score, dnf))
        if b:
            by_tuple.setdefault((b, m, e, t), []).append((score, dnf))
    return by_key, by_tuple


# -------------------------------------------------------------- artifacts ---
def pristine_for(rundir):
    """RG4 runs carry the policy-A GOAL.md; everything else diffs against RG3."""
    goal = os.path.join(rundir, "GOAL.md")
    try:
        with open(goal, encoding="utf-8") as fh:
            if "Failure policy (explicit" in fh.read():
                return PRISTINE_I4
    except OSError:
        pass
    return PRISTINE_I2


def diff_dir(rundir):
    r = subprocess.run(["diff", "-ru", "--exclude=__pycache__",
                        pristine_for(rundir), rundir], capture_output=True, text=True)
    return r.stdout


def write_artifacts(run, rundir):
    """Write runs/ artifacts for one run; returns list of artifact paths."""
    made = []
    bench, run_id = run["bench"], run["run_id"]
    if bench in LEGACY_BENCHES:
        ext = {"O": ".plan.md", "IR": ".review.md", "DR2": ".critique.md"}[bench]
        path = os.path.join(RUNS, run_id + ext)
        if run["text"]:
            with open(path, "w") as f:
                f.write(run["text"])
            made.append(path)
    elif bench == "I2":
        if rundir:
            # no rundir (retired raw tree): keep the committed artifact,
            # never overwrite with an empty diff
            path = os.path.join(RUNS, run_id + ".diff")
            with open(path, "w") as f:
                f.write(diff_dir(rundir))
            made.append(path)
        if run["text"]:
            path = os.path.join(RUNS, run_id + ".report.md")
            with open(path, "w") as f:
                f.write(run["text"])
            made.append(path)
    elif bench == "D":
        if rundir:
            design = os.path.join(rundir, "DESIGN-d1.md")
            if os.path.exists(design):
                path = os.path.join(RUNS, run_id + ".design.md")
                with open(design, encoding="utf-8", errors="replace") as f:
                    text = f.read()
                with open(path, "w") as f:
                    f.write(text)
                made.append(path)
        if run["text"]:
            path = os.path.join(RUNS, run_id + ".report.md")
            with open(path, "w") as f:
                f.write(run["text"])
            made.append(path)
    return made


# -------------------------------------------------------------- extraction --
# Round-2 (bench-v3 pilot, 2026-11-12/13) claude-family arm names carried a
# legacy IV2-<shortslug> prefix. The committed artifacts were normalized to
# I2-claude-<model>-<effort>-pN on 2026-11-18 (P1 naming fix); this mapping
# keeps a re-run reproducing exactly the normalized names.
ROUND2_RENAME = re.compile(r"^IV2-(sonnet|opus)-")

def norm_round2(name):
    """Legacy round-2 claude arm name -> normalized I2 run id (identity otherwise)."""
    return ROUND2_RENAME.sub("I2-claude-\\1-", name)


def collect_runs():
    """One record per run (log or run dir), with artifacts written."""
    os.makedirs(RUNS, exist_ok=True)
    sessions = load_eval_sessions()
    dir_of_session = {}
    for s in sessions.values():
        base = os.path.basename(s["directory"] or "")
        if base:
            dir_of_session.setdefault(base, []).append(s)

    logs = []
    for sub in ("", "grid/", "grid2/"):
        logs += sorted(glob.glob(os.path.join(BASE, "logs", sub, "*.log*")))
    parsed = [p for p in (parse_log(l) for l in logs) if p]
    log_by_stem = {p["stem"]: p for p in parsed}
    log_by_rundir = {}
    for p in parsed:
        if p["run_dir"]:
            log_by_rundir.setdefault(p["run_dir"], p)

    run_dirs = {}
    raw = os.path.join(BASE, "raw")
    if os.path.isdir(raw):
        for d in sorted(os.listdir(raw)):
            p = os.path.join(raw, d)
            if os.path.isdir(p) and d != "grid2":
                run_dirs[d] = p
        g2 = os.path.join(raw, "grid2")
        if os.path.isdir(g2):
            for d in sorted(os.listdir(g2)):
                p = os.path.join(g2, d)
                if os.path.isdir(p):
                    run_dirs.setdefault(d, p)
    scratch = os.path.join(BASE, "scratch")
    if os.path.isdir(scratch):
        for d in sorted(os.listdir(scratch)):
            p = os.path.join(scratch, d)
            if os.path.isdir(p):
                run_dirs.setdefault(d, p)

    scorer_by_key, scorer_by_tuple = load_scorer_scores()

    def resolve_score(run_dir, stem, bench, csv_model, effort, tag):
        """Scorer evidence for a run: exact key first, then normalized tuple
        (unique match only — ambiguity stays unresolved = fail-closed)."""
        for key in (run_dir, stem):
            if key and key in scorer_by_key:
                return scorer_by_key[key]
        for tup in ((bench, csv_model, effort, tag),
                    (bench, "", effort, tag)):
            hits = scorer_by_tuple.get(tup)
            if hits:
                distinct = sorted(set(hits))
                if len(distinct) == 1:
                    return distinct[0]
                scores_only = sorted({h for h in hits if h[0]})
                if len(scores_only) == 1:
                    return scores_only[0]
        return ("", "")

    runs = {}

    def add(run):
        prev = runs.get(run["run_id"])
        if not prev:
            runs[run["run_id"]] = run
            return
        # merge: keep the richer evidence
        for k in ("score", "text"):
            if not prev.get(k) and run.get(k):
                prev[k] = run[k]
        for k in ("session", "rundir", "log"):
            if not prev.get(k) and run.get(k):
                prev[k] = run[k]
        if prev["status"] == "orphan" and run["status"] != "orphan":
            prev["status"] = run["status"]
            prev["dnf_reason"] = run["dnf_reason"]

    # --- runs known from logs ---
    for log in parsed:
        stem = log["stem"]
        if stem.startswith("_campaign"):
            continue
        sess = sessions.get(log["title"])
        parts = title_parts(log["title"]) if log["title"] else None
        run_id = stem_run_id(stem)
        bench = BENCH_CODE.get(parts["bench"], parts["bench"]) if parts \
            else run_id_parts(run_id)[0]
        _, csv_model, effort0, tag0 = run_id_parts(run_id)
        score, dnf = resolve_score(log["run_dir"], stem, bench, csv_model,
                                   effort0, tag0)
        is_retry = bool(re.search(r"r2b?$", run_id.split("-")[-1]))
        if parts and parts["bench"] == "IV2-RG2":
            status = "superseded"
        elif dnf:
            # scorer-recorded DNF outranks everything (e.g. no final report)
            status = "DNF"
        elif score:
            # a scored deliverable counts even if the arm was killed afterwards
            status = "retry" if is_retry else "scored"
        elif run_id in OWNER_FREEZE_SCORES:
            status = "scored"
            score = OWNER_FREEZE_SCORES[run_id][0]
        elif log["arm_kill"]:
            status = "DNF"
        elif log.get("prov_error"):
            status = "DNF"
        else:
            status = "unscored"  # resolved after all runs are known
        dnf_reason = dnf or log["arm_kill"] or \
            ("provider-error" if status == "DNF" and log.get("prov_error")
             else "none")
        if status != "DNF":
            dnf_reason = "none"
        run = {"run_id": run_id, "bench": bench, "status": status,
               "score": score, "dnf_reason": dnf_reason,
               "log": log["path"], "rundir": log["run_dir"],
               "session": sess, "text": ""}
        add(run)

    # --- run dirs without a log (session via DB directory) ---
    for d, rundir in sorted(run_dirs.items()):
        if d in log_by_rundir or d in log_by_stem:
            continue  # covered by the log-based row
        sess_list = dir_of_session.get(d, [])
        sess = sess_list[-1] if sess_list else None
        parts = title_parts(sess["title"]) if sess else None
        if parts:
            bench = BENCH_CODE.get(parts["bench"], parts["bench"])
            run_id = "%s-%s-%s" % (bench, parts["slug"].replace(".", "_"),
                                   parts["effort"])
            if parts["tag"]:
                run_id += "-" + parts["tag"]
        else:
            bench, run_id = "", d
        score, dnf = resolve_score(d, d, bench, "", "", "")
        is_retry = bool(re.search(r"r2b?$", run_id.split("-")[-1]))
        if parts and parts["bench"] == "IV2-RG2":
            status = "superseded"
        elif dnf:
            status = "DNF"
        elif score:
            status = "retry" if is_retry else "scored"
        else:
            status = "unscored"  # resolved after all runs are known
        run = {"run_id": run_id, "bench": bench, "status": status,
               "score": score, "dnf_reason": dnf if status == "DNF" else "none",
               "log": "", "rundir": d, "session": sess, "text": ""}
        add(run)

    # --- round-2 pilot dirs (source c): raw-round2 *-p3/p4. Once raw-round2
    # is retired (deleted at cleanup), the run list falls back to the
    # committed runs/ artifacts for the same *-p3/p4 run ids.
    round2_names = set()
    if os.path.isdir(ROUND2):
        round2_names = {norm_round2(d) for d in os.listdir(ROUND2)
                        if os.path.isdir(os.path.join(ROUND2, d))
                        and re.search(r"-p[34]", d)}
    else:
        # retired raw tree: reconstruct the run list from the committed
        # runs/ artifacts plus the scorer-session arm keys (DNF arms have
        # no artifact of their own); legacy IV2-claude arm names are
        # normalized to their I2-claude-* run ids (2026-11-18 naming fix),
        # so a re-run reproduces the normalized runs/ artifact names.
        round2_names = {norm_round2(re.sub(r"\.(diff|design\.md|report\.md)$", "", f))
                        for f in os.listdir(RUNS)
                        if re.match(r"^(?:IV2|I2|D)-.*-p[34]", f)}
        round2_names |= {norm_round2(k) for k in scorer_by_key
                         if re.match(r"^(?:IV2|I2|D)-.*-p[34]", k)}
        # recorded DNF arms: dirs deleted at cleanup, never scored (their
        # DNF rows are in the committed TSV / RESULTS history)
        round2_names |= {"D-opus-default-p3-DNF", "D-opus-default-p3r2-DNF",
                         "D-sonnet-high-p4-DNF", "D-sonnet-high-p4r2-DNF"}
    for d in sorted(round2_names):
            rundir = os.path.join(ROUND2, d) if os.path.isdir(
                os.path.join(ROUND2, d)) else None
            sess_list = dir_of_session.get(d, [])
            sess = sess_list[-1] if sess_list else None
            if rundir:
                bench = "I2" if os.path.exists(
                    os.path.join(rundir, "reportgen.py")) else "D"
            else:
                # retired raw tree: bench from the committed artifact kind
                bench = "I2" if os.path.exists(
                    os.path.join(RUNS, d + ".diff")) else "D"
            run_id = d
            # model/effort/tag from the run id so a normalized name still
            # resolves its score via the (bench, model, effort, tag) tuple
            # when the legacy scorer key (pre-rename name) is not literal
            _, csv_model_r2, eff_r2, tag_r2 = run_id_parts(d)
            score, dnf = resolve_score(d, d, bench, csv_model_r2, eff_r2,
                                       tag_r2)
            if "-DNF" in d and not score:
                status, reason = "DNF", (dnf or "no-deliverable")
            elif sess and "IV2-RG2" in sess["title"]:
                status, reason = "superseded", "none"
            elif dnf:
                status, reason = "DNF", dnf
            elif score:
                status = "retry" if re.search(r"r2b?$", d.split("-")[-1]) \
                    else "scored"
                reason = "none"
            else:
                status, reason = "unscored", "none"
            run = {"run_id": run_id, "bench": bench, "status": status,
                   "score": score, "dnf_reason": reason, "log": "",
                   "rundir": rundir, "session": sess, "text": ""}
            add(run)

    # --- resolve retry status: an r2-tagged run is a retry only if the
    # earlier same-cell runs were all DNF/superseded; if the cell has another
    # scored run, it is simply the second valid run.
    cell_runs = {}
    for run in runs.values():
        _, csv_model, _, _ = run_id_parts(run["run_id"])
        if csv_model:
            cell_runs.setdefault((csv_model, run["bench"]), []).append(run)
    for cell, members in cell_runs.items():
        scored_peers = [m for m in members
                        if m["status"] == "scored" and m["score"]]
        for m in members:
            if m["status"] == "retry" and len(scored_peers) > 1:
                m["status"] = "scored"

    # --- resolve unscored runs: a run with no scorer evidence whose cell is
    # covered by scored runs (a later re-measure of the same cell) is
    # superseded; otherwise it is an orphan (fail-closed).
    covered_cells = set()
    for run in runs.values():
        if run["status"] in ("scored", "retry") and run["score"]:
            _, csv_model, _, _ = run_id_parts(run["run_id"])
            if csv_model:
                covered_cells.add((csv_model, run["bench"]))
    for run in runs.values():
        if run["status"] != "unscored":
            continue
        _, csv_model, _, _ = run_id_parts(run["run_id"])
        if csv_model and (csv_model, run["bench"]) in covered_cells:
            run["status"] = "superseded"
        else:
            run["status"] = "orphan"

    # --- artifacts + evidence ---
    rows = []
    for run in runs.values():
        sess = run["session"]
        text = ""
        if sess and run["bench"] in ("I2", "D"):
            text = final_assistant_text(sess["id"])
        elif run["bench"] in LEGACY_BENCHES and run["log"]:
            text = final_assistant_text(sess["id"]) if sess else ""
            if not text:
                text = build_log_text(log_by_stem[re.sub(r"\.log(\.gz)?$","",os.path.basename(run["log"]))])
        run["text"] = text
        rundir = None
        if run["rundir"]:
            rundir = run_dirs.get(run["rundir"])
            if rundir is None and run["log"]:
                # raw/ copies keep the log stem as directory name
                stem = re.sub(r"\.log(\.gz)?$","",os.path.basename(run["log"]))
                rundir = run_dirs.get(stem)
            if rundir is None:
                cand = os.path.join(ROUND2, run["rundir"])
                rundir = cand if os.path.isdir(cand) else None
        made = write_artifacts(run, rundir)
        if run["log"]:
            evidence = os.path.relpath(run["log"], ROOT)
        elif made:
            evidence = os.path.relpath(made[0], ROOT)
        else:
            # raw tree retired: fall back to any committed runs/ artifact
            existing = sorted(f for f in os.listdir(RUNS)
                              if f.startswith(run["run_id"] + "."))
            evidence = os.path.relpath(os.path.join(RUNS, existing[0]), ROOT) \
                if existing else ""
        _, csv_model, effort, tag = run_id_parts(run["run_id"])
        rows.append({"run_id": run["run_id"], "bench": run["bench"],
                     "model": csv_model, "effort": effort, "tag": tag,
                     "status": run["status"], "score": run["score"],
                     "dnf_reason": run["dnf_reason"],
                     "evidence_path": evidence,
                     "notes": OWNER_FREEZE_SCORES.get(
                         run["run_id"], ("", ""))[1]})
    return rows, sessions


# ------------------------------------------------------------------ costs ---
def write_costs():
    path = os.path.join(BASE, "grid2-costs.tsv")
    titles = q("SELECT DISTINCT title FROM session WHERE " +
               " OR ".join("title LIKE 'eval-2026-11-%s%%'" % d
                           for d in ("13", "14", "15", "16", "17")) +
               " ORDER BY title;").splitlines()
    out = []
    for t in titles:
        safe = t.replace("'", "''")
        cost = q("SELECT SUM(cost) FROM session WHERE title='%s' OR parent_id = "
                 "(SELECT id FROM session WHERE title='%s');" % (safe, safe))
        try:
            c = float(cost or 0)
        except ValueError:
            c = 0.0
        out.append("%s|%.4f" % (t, c))
    with open(path, "w") as f:
        f.write("\n".join(out) + "\n")
    return len(out)


# -------------------------------------------------------------- reconcile ---
def reconcile(rows):
    """CSV cells -> scored TSV rows; scored rows -> runs/ artifacts."""
    with open(os.path.join(BASE, "grid2-scores.csv")) as f:
        csv_rows = list(csv.DictReader(f))

    bench_cols = [("O8", "O"), ("IR", "IR"), ("DR2", "DR2"),
                  ("I2", "I2"), ("D", "D")]
    tsv_by_cell = {}
    for r in rows:
        if r["status"] in ("scored", "retry") and r["score"] and r["model"]:
            tsv_by_cell.setdefault((r["model"], r["bench"]), []).append(r)

    cells_total = cells_covered = cells_out = 0
    cells_uncovered = []
    for row in csv_rows:
        model, effort = row["model"], row["effort"]
        for col, bench in bench_cols:
            val = row[col].strip()
            if val in ("", "not measured", "DNF"):
                continue
            if not tsv_by_cell.get((model, bench)):
                cells_out += 1
                continue
            cells_total += 1
            if any(r["score"] for r in tsv_by_cell[(model, bench)]):
                cells_covered += 1
            else:
                cells_uncovered.append((model, effort, bench))

    missing_artifacts = []
    for r in rows:
        if r["status"] in ("scored", "retry") and r["score"]:
            ev = r["evidence_path"]
            if not ev or not os.path.exists(os.path.join(ROOT, ev)):
                missing_artifacts.append(r["run_id"])
    orphans = [r["run_id"] for r in rows if r["status"] == "orphan"]
    return {"cells_total": cells_total, "cells_covered": cells_covered,
            "cells_out_of_scope": cells_out, "cells_uncovered": cells_uncovered,
            "scored_rows": sum(1 for r in rows if r["score"] and
                               r["status"] in ("scored", "retry")),
            "missing_artifacts": missing_artifacts, "orphans": orphans,
            "rows": len(rows)}


def main():
    rows, _ = collect_runs()
    tsv_path = os.path.join(BASE, "grid2-run-scores.tsv")
    cols = ["run_id", "bench", "model", "effort", "tag", "status", "score",
            "dnf_reason", "evidence_path", "notes"]
    with open(tsv_path, "w") as f:
        f.write("\t".join(cols) + "\n")
        for r in sorted(rows, key=lambda x: x["run_id"]):
            f.write("\t".join(str(r[c]) for c in cols) + "\n")
    n_costs = write_costs()

    rec = reconcile(rows)
    print("TSV rows: %d" % len(rows))
    print("cost rows: %d" % n_costs)
    print("reconciliation:")
    print("  CSV cells in campaign scope: %d, covered by scored rows: %d,"
          " out-of-scope (no campaign run): %d"
          % (rec["cells_total"], rec["cells_covered"],
             rec["cells_out_of_scope"]))
    print("  scored TSV rows: %d, missing runs/ artifact: %d"
          % (rec["scored_rows"], len(rec["missing_artifacts"])))
    if rec["cells_uncovered"]:
        print("FAIL: campaign cells without a scored TSV row:")
        for c in rec["cells_uncovered"]:
            print("   ", c)
    if rec["missing_artifacts"]:
        print("FAIL: scored rows without runs/ artifact or missing evidence:")
        for c in rec["missing_artifacts"]:
            print("   ", c)
    if rec["orphans"]:
        print("FAIL: unreconcilable runs (status=orphan): %d" % len(rec["orphans"]))
        for c in rec["orphans"]:
            print("   ", c)
    if rec["cells_uncovered"] or rec["missing_artifacts"] or rec["orphans"]:
        sys.exit(1)
    print("OK: reconciliation clean")


if __name__ == "__main__":
    main()
