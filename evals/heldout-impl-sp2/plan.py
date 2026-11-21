"""Job and machine model and the deterministic assignment logic.

Scheduling is deterministic: no randomness, no wall-clock, and a fixed
tie-break (earliest start, then machine file order).
"""
import csv

# Placement-attempt counter; conflicts() is the single conflict test.
STATS = {"attempts": 0}


class Job:
    def __init__(self, id, minutes, priority, machine):
        self.id = id
        self.minutes = minutes
        self.priority = priority
        self.machine = machine


class Machine:
    def __init__(self, name, shift_minutes):
        self.name = name
        self.shift_minutes = shift_minutes


def load_machines(path):
    with open(path, newline="") as fh:
        return [Machine(r["name"], int(r["shift_minutes"])) for r in csv.DictReader(fh)]


def load_jobs(path):
    with open(path, newline="") as fh:
        return [Job(r["id"], int(r["minutes"]), int(r["priority"]), r["machine"])
                for r in csv.DictReader(fh)]


def order_jobs(jobs):
    return sorted(jobs, key=lambda j: (-j.priority, j.id))


def conflicts(assigned, start, minutes):
    """True when [start, start + minutes) overlaps an assignment already on the machine."""
    STATS["attempts"] += 1
    end = start + minutes
    return any(a["start"] < end and start < a["start"] + a["minutes"] for a in assigned)


def best_start(job, machine, placements):
    """Earliest feasible start for job on machine, or None.

    Window scan: only two candidate starts per machine are tested, 0 and the
    end of the last job placed on it. Attempts per job are therefore bounded
    by 2 x machines (the shipped scan is linear in the machine count).
    """
    on = placements[machine.name]
    last_end = max((r["start"] + r["minutes"] for r in on), default=0)
    for start in (0, last_end):
        if start + job.minutes > machine.shift_minutes:
            continue
        if not conflicts(on, start, job.minutes):
            return start
    return None


def assign(jobs, machines):
    """Return (placements, unassigned): placements maps machine name to its rows."""
    placements = {m.name: [] for m in machines}
    unassigned = []
    for job in order_jobs(jobs):
        best = None
        for m in machines:
            s = best_start(job, m, placements)
            if s is None:
                continue
            if best is None or s < best[1]:
                best = (m, s)
        if best is None:
            unassigned.append(job)
            continue
        m, s = best
        placements[m.name].append({"job": job.id, "start": s, "minutes": job.minutes})
    return placements, unassigned
