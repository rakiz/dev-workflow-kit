"""Job and machine model and the deterministic assignment logic.

Scheduling is deterministic: no randomness, no wall-clock, and a fixed
tie-break (earliest start, then machine file order).
"""
import csv


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
    end = start + minutes
    return any(a["start"] < end and start < a["start"] + a["minutes"] for a in assigned)


def best_start(job, machine, placements):
    """Earliest feasible start for job on machine, or None.

    Candidate starts are 0 and the end time of every job placed so far.
    """
    ends = {0}
    for rows in placements.values():
        for row in rows:
            ends.add(row["start"] + row["minutes"])
    on = placements[machine.name]
    for start in sorted(ends):
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
