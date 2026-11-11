"""A web page for editing the schedule, 001_worker_bees_crontab.txt.

The jobs are listed on the left. Click one to change it, add new ones, drag
them into a different order, pause them. Every change is written straight
into the crontab file, which stays an ordinary text file: you can still
edit it in Notepad. Each job shows how often it runs and when it runs next.

The previous version of the file is kept as 001_worker_bees_crontab.txt.bak.
If someone else changes the file while the page is open, the page refuses
to save over it and reloads instead.

Changes reach the queue at the next queue build (the nightly job), or
straight away with:  uv run ZZZ_build_queue.py

Run it with:  uv run ZZZ_schedule_editor.py
and open the address it prints.
"""

import hashlib
import os
import re
from datetime import datetime, timedelta

import ZZZ_build_queue as builder
from worker_bees_settings import HERE, SCHEDULE_FILE, SettingsError, load_settings
from worker_bees_web import Handler, serve
from ZZZ_worker import find_script

NEXT_RUNS = 5
MAX_SCRIPTS_LISTED = 500
SKIP_FOLDERS = {".git", ".venv", "venv", "__pycache__", "node_modules", "web"}


# ------------------------------------------------- the crontab file as parts


def paused_job_line(text):
    """'#0 8 * * * a.py' is a paused job: a # with a valid crontab line right after it.

    '# 0 8 ...' (with a space) and every other comment are just comments.
    """
    if len(text) < 2 or not text.startswith("#") or text[1].isspace():
        return False
    try:
        builder.parse_line(text[1:], "")
        return True
    except builder.ScheduleError:
        return False


def is_job_line(line):
    text = line.strip()
    return bool(text) and (not text.startswith("#") or paused_job_line(text))


def split_crontab(text):
    """Split the file into a header, the jobs in order, and a footer.

    Each job keeps the comment lines right above it (with no blank line in
    between) as its description, so they move with it. Other comments
    between jobs (a section heading, say) stay with the job below them.
    """
    lines = text.splitlines()
    header, jobs, footer = lines, [], []
    end_of_last = 0
    for row, line in enumerate(lines):
        if not is_job_line(line):
            continue
        start = row
        while start > end_of_last and lines[start - 1].strip().startswith("#") and not is_job_line(lines[start - 1]):
            start -= 1
        between = lines[end_of_last:start]
        if not jobs:
            header = between
        text = line.strip()
        jobs.append({
            "lead": [] if len(jobs) == 0 else [l for l in between if l.strip()],
            "description": [re.sub(r"^#\s?", "", l.strip()) for l in lines[start:row]],
            "line": text[1:] if text.startswith("#") else text,
            "paused": text.startswith("#"),
        })
        end_of_last = row + 1
    if jobs:
        footer = [l for l in lines[end_of_last:] if l.strip()]
    return {"header": header, "jobs": jobs, "footer": footer}


def join_crontab(parts):
    """The opposite of split_crontab: one blank line between jobs."""
    out = list(parts["header"])
    while out and not out[-1].strip():
        out.pop()
    for job in parts["jobs"]:
        if out:
            out.append("")
        if job["lead"]:  # a section heading: keep it apart from the job's own description
            out += job["lead"] + [""]
        out += [f"# {d}".rstrip() for d in job["description"]]
        out.append(("#" if job["paused"] else "") + job["line"])
    if parts["footer"]:
        out += [""] + parts["footer"]
    return "\n".join(out) + "\n"


def read_file():
    """Return (text, version). The version changes whenever the file does."""
    text = SCHEDULE_FILE.read_text(encoding="utf-8-sig") if SCHEDULE_FILE.exists() else ""
    return text, hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def write_file(old_text, new_text):
    """Keep the old version as a .bak, then swap the new file in all at once."""
    backup = SCHEDULE_FILE.with_name(SCHEDULE_FILE.name + ".bak")
    backup.write_text(old_text, encoding="utf-8")
    temporary = SCHEDULE_FILE.with_name(SCHEDULE_FILE.name + ".saving")
    temporary.write_text(new_text, encoding="utf-8")
    os.replace(temporary, SCHEDULE_FILE)


# ------------------------------------------------------- how often a job runs


def scripts_folder():
    try:
        return load_settings()["scripts_dir"]
    except SettingsError:
        return HERE


def next_runs(job, now, count=NEXT_RUNS):
    """The next few times the job runs, looking up to four years ahead (for 29 Feb)."""
    found = []
    for offset in range(4 * 366 + 1):
        day = now.date() + timedelta(days=offset)
        if not builder.day_matches(day, job):
            continue
        for hour in job["hours"]:
            for minute in job["minutes"]:
                start = datetime(day.year, day.month, day.day, hour, minute)
                if start > now:
                    found.append(start.isoformat(timespec="minutes"))
                    if len(found) == count:
                        return found
    return found


def how_often(job, today):
    """Runs on a day it runs, and on average per week and per month over the next year."""
    runs_per_day = len(job["hours"]) * len(job["minutes"])
    days = [builder.day_matches(today + timedelta(days=n), job) for n in range(365)]
    return {
        "per_day": runs_per_day if any(days) else 0,
        "per_week": sum(days[:364]) * runs_per_day / 52,
        "per_month": sum(days) * runs_per_day / 12,
        "per_year": sum(days) * runs_per_day,
    }


def describe(line, now, scripts_dir):
    """Everything the page shows about one crontab line."""
    parts = line.split(None, 5)
    info = {
        "fields": (parts[:5] + [""] * 5)[:5],
        "script": parts[5].strip() if len(parts) == 6 else "",
    }
    try:
        job = builder.parse_line(line, "This line")
    except builder.ScheduleError as error:
        info["error"] = str(error)
        return info
    info["often"] = how_often(job, now.date())
    info["next_runs"] = next_runs(job, now)
    info["name"] = job["name"]
    info["script_found"] = find_script(job["script"], scripts_dir).is_file()
    return info


def list_scripts(scripts_dir):
    """Python files in the scripts folder and the worker_bees folder, for the script box."""
    found = set()
    for base in dict.fromkeys([scripts_dir, HERE]):
        for folder, subfolders, files in os.walk(base):
            subfolders[:] = [s for s in subfolders if s not in SKIP_FOLDERS and not s.startswith(".")]
            if len(os.path.relpath(folder, base).split(os.sep)) > 3:
                subfolders[:] = []
            for name in files:
                # leave out worker_bees' own files, apart from the queue build job
                own_file = name.startswith(("worker_bees_", "ZZZ_")) and name != "ZZZ_build_queue.py"
                if name.endswith(".py") and not own_file:
                    found.add(os.path.relpath(os.path.join(folder, name), base).replace(os.sep, "/"))
            if len(found) >= MAX_SCRIPTS_LISTED:
                return sorted(found)
    return sorted(found)


def schedule_state():
    text, version = read_file()
    parts = split_crontab(text)
    now = datetime.now()
    scripts_dir = scripts_folder()
    jobs, totals = [], {"per_week": 0, "per_month": 0, "per_year": 0}
    for job in parts["jobs"]:
        info = describe(job["line"], now, scripts_dir)
        info["paused"] = job["paused"]
        info["description"] = "\n".join(job["description"])
        jobs.append(info)
        if not job["paused"] and "often" in info:
            for key in totals:
                totals[key] += info["often"][key]
    totals["per_day"] = totals["per_year"] / 365
    return {
        "version": version,
        "file": str(SCHEDULE_FILE),
        "scripts_dir": str(scripts_dir),
        "jobs": jobs,
        "totals": totals,
        "scripts": list_scripts(scripts_dir),
    }


# ----------------------------------------------------------------- changes


def line_from(job):
    """Build a crontab line from the page's fields, or raise ScheduleError."""
    fields = [str(f).strip() for f in job.get("fields", [])]
    script = str(job.get("script", "")).strip()
    if len(fields) != 5 or not all(fields):
        raise builder.ScheduleError("Fill in all five time fields (use * for 'every').")
    if any(" " in f for f in fields):
        raise builder.ScheduleError("Time fields can't have spaces: use commas, like 8,13")
    if not script:
        raise builder.ScheduleError("Which script should run?")
    if "\n" in script:
        raise builder.ScheduleError("The script should be on one line.")
    line = f"{' '.join(fields):<17} {script}"
    builder.parse_line(line, "This job")  # raises if anything is wrong
    return line


def check(request):
    """Describe a line that hasn't been saved yet, so the page can show it as you type."""
    try:
        line = line_from(request)
    except builder.ScheduleError as error:
        return 200, {"error": str(error)}
    return 200, describe(line, datetime.now(), scripts_folder())


def save(request):
    """Apply one change (update, add, delete or move) and write the file."""
    text, version = read_file()
    if request.get("version") != version:
        return 409, {"error": "The schedule file was changed somewhere else, so nothing was saved. "
                              "The page now shows the file as it is.", "state": schedule_state()}
    parts = split_crontab(text)
    jobs = parts["jobs"]
    action = request.get("action")
    index = request.get("index")
    if action in ("update", "delete", "move") and not (isinstance(index, int) and 0 <= index < len(jobs)):
        return 400, {"error": "That job isn't in the file any more."}

    try:
        if action in ("update", "add"):
            new = request.get("job", {})
            description = [d.rstrip() for d in str(new.get("description", "")).splitlines()]
            while description and not description[-1]:
                description.pop()
            fields = {"line": line_from(new), "paused": bool(new.get("paused")), "description": description}
            if action == "update":
                jobs[index].update(fields)
            else:
                jobs.append({"lead": [], **fields})
                index = len(jobs) - 1
        elif action == "delete":
            jobs.pop(index)
            index = None
        elif action == "move":
            to = request.get("to")
            if not (isinstance(to, int) and 0 <= to < len(jobs)):
                return 400, {"error": "Can't move a job there."}
            jobs.insert(to, jobs.pop(index))
            index = to
        else:
            return 400, {"error": f"Unknown action: {action}"}
    except builder.ScheduleError as error:
        return 400, {"error": str(error)}

    write_file(text, join_crontab(parts))
    return 200, {"state": schedule_state(), "index": index}


class EditorPage(Handler):
    page = "schedule_editor.html"
    get_api = {"/api/schedule": schedule_state}
    post_api = {"/api/check": check, "/api/save": save}


if __name__ == "__main__":
    serve(EditorPage, 8765, "worker_bees schedule editor")
