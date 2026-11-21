"""Plan, timetable, index and summary I/O."""
import json


def save_plan(plan, path):
    """The write is atomic: a reader never observes a partially written plan, and a failed save leaves the previous plan intact."""
    with open(path, "w") as fh:
        json.dump(plan, fh, indent=2, sort_keys=True)


def load_plan(path):
    with open(path) as fh:
        return json.load(fh)


def render_timetable(placements, machines):
    lines = []
    for m in machines:
        for row in sorted(placements[m.name], key=lambda r: (r["start"], r["job"])):
            lines.append(f"{m.name} {row['start']} {row['job']} {row['minutes']}")
    return "\n".join(lines) + ("\n" if lines else "")


def write_index(path, jobs, machines):
    index = {"machines": {}}
    for m in machines:
        mine = [j for j in jobs if j.machine == m.name]
        index["machines"][m.name] = {"load_minutes": sum(j.minutes for j in mine),
                                     "jobs": len(mine)}
    with open(path, "w") as fh:
        json.dump(index, fh, indent=2, sort_keys=True)


def write_unassigned(path, jobs):
    with open(path, "w") as fh:
        for j in jobs:
            fh.write(j.id + "\n")


def write_summary(path, total_minutes, partial):
    with open(path, "w") as fh:
        json.dump({"partial": partial, "total_minutes": total_minutes}, fh,
                  indent=2, sort_keys=True)
