"""Command-line entry point: schedule jobs onto machines and write the artefacts."""
import argparse
import os
import sys

import plan
import planio


def runstate_path(out_dir):
    """The run-state cache lives beside the output directory."""
    return os.path.join(os.path.dirname(os.path.abspath(out_dir)), "runstate")


def run(jobs_path, machines_path, out_dir):
    jobs = plan.load_jobs(jobs_path)
    machines = plan.load_machines(machines_path)
    placements, unassigned = plan.assign(jobs, machines)
    os.makedirs(out_dir, exist_ok=True)
    plan_doc = {"machines": {}}
    for m in machines:
        rows = sorted(placements[m.name], key=lambda r: (r["start"], r["job"]))
        plan_doc["machines"][m.name] = {"shift_minutes": m.shift_minutes, "assignments": rows}
    planio.save_plan(plan_doc, os.path.join(out_dir, "plan.json"))
    with open(os.path.join(out_dir, "timetable.txt"), "w") as fh:
        fh.write(planio.render_timetable(placements, machines))
    index = planio.index_from_plan(plan_doc)
    cached = planio.load_runstate(runstate_path(out_dir), jobs, machines)
    if cached is not None:
        loads, counts = cached
        index = {"machines": {name: {"load_minutes": loads.get(name, 0),
                                    "jobs": counts.get(name, 0)}
                             for name in plan_doc["machines"]}}
    planio.save_index(index, os.path.join(out_dir, "index.json"))
    planio.save_runstate(runstate_path(out_dir), jobs, machines)
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description="Schedule jobs onto machines.")
    ap.add_argument("--jobs", required=True)
    ap.add_argument("--machines", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args(argv)
    return run(args.jobs, args.machines, args.out)


if __name__ == "__main__":
    sys.exit(main())
