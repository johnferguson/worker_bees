"""A web page that shows what the workers are doing: the banh mi stand.

The stand is the queue. Each bee on a moped is a worker, and each house is
a job's script. A bee out at a house is running that job right now; bees
parked at the stand are waiting for work. The counter shows the orders
waiting to go out, and the houses show what's coming up next.

It only reads. It lists the queue folders and never opens, moves or
changes a file, so turning it off (or never using it) changes nothing.
It doesn't even open the job files: on Windows a worker can't move a file
another program has open, and the monitor must never get in a worker's way.

Run it with:  uv run ZZZ_monitor.py
and open the address it prints.
"""

import os
import re
from datetime import datetime

from worker_bees_settings import SettingsError, folder, load_settings
from worker_bees_web import Handler, serve

JOB_FILE = re.compile(r"(\d{8}_\d{6})_(.+)")  # yyyymmdd_hhmmss_name.anything
UPCOMING_SHOWN = 30
FINISHED_SHOWN = 15


def entries(path):
    """List a folder without opening anything in it."""
    with os.scandir(path) as found:
        return list(found)


def job_from_name(name):
    """'20261111_080000_ftp_upload.sched' -> when it's due, its name and its kind."""
    match = JOB_FILE.fullmatch(name)
    if not match:
        return None
    try:
        due = datetime.strptime(match.group(1), "%Y%m%d_%H%M%S")
    except ValueError:
        return None
    stem, dot, ending = match.group(2).rpartition(".")
    if not dot:
        stem, ending = match.group(2), ""
    return {"file": name, "name": stem, "kind": ending, "due": due.isoformat(timespec="minutes")}


def when_changed(entry):
    # for a folder this is when a file last went in or out of it
    return datetime.fromtimestamp(entry.stat().st_mtime).isoformat(timespec="seconds")


def monitor_state():
    try:
        settings = load_settings()
        queue = folder(settings, "queue_folder")
        running = folder(settings, "running_folder")
        failed = folder(settings, "failed_folder")
        complete = folder(settings, "complete_folder")
    except SettingsError as error:
        return {"error": str(error)}

    now = datetime.now()
    timeout_minutes = settings.get("job_timeout_minutes", 240)

    workers = []
    for entry in sorted(entries(running), key=lambda e: e.name.lower()):
        if not entry.is_dir():
            continue
        jobs = [job for e in entries(entry.path) if e.is_file() and (job := job_from_name(e.name))]
        workers.append({"name": entry.name, "jobs": jobs, "changed": when_changed(entry)})

    due, upcoming, queued = [], [], 0
    now_text = now.isoformat(timespec="minutes")
    for entry in entries(queue):
        job = job_from_name(entry.name) if entry.is_file() else None
        if job is None:
            continue
        queued += 1
        (due if job["due"] <= now_text else upcoming).append(job)
    due.sort(key=lambda j: j["due"])
    upcoming.sort(key=lambda j: j["due"])

    finished = []
    for result, path in (("complete", complete), ("failed", failed)):
        for entry in entries(path):
            job = job_from_name(entry.name) if entry.is_file() else None
            if job:
                job["result"] = result
                job["finished"] = when_changed(entry)  # the worker writes to it last, as it finishes
                finished.append(job)
    finished.sort(key=lambda j: j["finished"], reverse=True)

    return {
        "now": now.isoformat(timespec="seconds"),
        "timeout_minutes": timeout_minutes,
        "workers": workers,
        "due": due,
        "upcoming": upcoming[:UPCOMING_SHOWN],
        "queued": queued,
        "finished": finished[:FINISHED_SHOWN],
        "failed_total": sum(1 for j in finished if j["result"] == "failed"),
    }


class MonitorPage(Handler):
    page = "monitor.html"
    get_api = {"/api/state": monitor_state}


if __name__ == "__main__":
    serve(MonitorPage, 8766, "worker_bees monitor")
