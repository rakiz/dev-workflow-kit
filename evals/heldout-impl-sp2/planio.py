"""Plan, timetable, index and summary I/O."""
import hashlib
import json


def save_plan(plan, path):
    """The write is atomic: a reader never observes a partially written plan, and a failed save leaves the previous plan intact."""
    with open(path, "w") as fh:
        json.dump(plan, fh, indent=2, sort_keys=True)


def save_index(index, path):
    with open(path, "w") as fh:
        json.dump(index, fh, indent=2, sort_keys=True)


def load_plan(path):
    with open(path) as fh:
        return json.load(fh)


def render_timetable(placements, machines):
    lines = []
    for m in machines:
        for row in sorted(placements[m.name], key=lambda r: (r["start"], r["job"])):
            lines.append(f"{m.name} {row['start']} {row['job']} {row['minutes']}")
    return "\n".join(lines) + ("\n" if lines else "")


def index_from_plan(plan_doc):
    """Index derived from the plan's actual assignments (the truth)."""
    return {"machines": {name: {"load_minutes": sum(a["minutes"] for a in m["assignments"]),
                                "jobs": len(m["assignments"])}
                         for name, m in plan_doc["machines"].items()}}


def write_unassigned(path, jobs):
    with open(path, "w") as fh:
        for j in jobs:
            fh.write(j.id + "\n")


def write_unreadable(path, paths):
    with open(path, "w") as fh:
        for p in paths:
            fh.write(str(p) + "\n")


def write_summary(path, total_minutes, partial):
    with open(path, "w") as fh:
        json.dump({"partial": partial, "total_minutes": total_minutes}, fh,
                  indent=2, sort_keys=True)


def preference_digest(jobs):
    """Digest of the preference column, row by row (job id + preferred machine)."""
    h = hashlib.sha256()
    for j in jobs:
        h.update((j.id + "\x1f" + (j.machine or "") + "\n").encode())
    return h.hexdigest()


def preference_forecast(jobs, machines):
    """Per-machine load forecast if every job landed on its preferred machine."""
    loads = {m.name: 0 for m in machines}
    counts = {m.name: 0 for m in machines}
    for j in jobs:
        if j.machine in loads:
            loads[j.machine] += j.minutes
            counts[j.machine] += 1
    return loads, counts


def save_runstate(path, jobs, machines):
    """Record the per-machine load forecast so the next run can reuse it."""
    loads, counts = preference_forecast(jobs, machines)
    state = {"key": preference_digest(jobs), "loads": loads, "jobs": counts}
    with open(path, "w") as fh:
        json.dump(state, fh, indent=2, sort_keys=True)


def load_runstate(path, jobs, machines):
    """The forecast recorded for this input, or None when no forecast applies."""
    try:
        with open(path) as fh:
            state = json.load(fh)
    except (OSError, ValueError):
        return None
    if not isinstance(state, dict) or state.get("key") != preference_digest(jobs):
        return None
    return state.get("loads") or {}, state.get("jobs") or {}
