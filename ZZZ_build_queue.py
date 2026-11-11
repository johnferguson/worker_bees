"""Build the job queue from the schedule.

Reads 000_worker_bees_queue.toml (settings) and 001_worker_bees_crontab.txt
(the jobs, one per line like a crontab), then makes sure the queue folder
holds one .sched file for every scheduled run from now until forward_days
ahead.

It is safe to run at any time, as often as you like:
  1. The whole schedule is checked first. If anything is wrong it stops
     before touching a single file.
  2. New and changed files are written.
  3. Only then are old files deleted: future .sched files that are no
     longer in the schedule.
Files due in the next few minutes are never touched. Neither is anything
that doesn't end in .sched, so jobs added by hand (e.g. .request files)
are always left alone.

Run it with:                                uv run ZZZ_build_queue.py
See what it would do without changing anything:
                                            uv run ZZZ_build_queue.py --preview
"""

import re
import sys
from datetime import datetime, timedelta
from pathlib import Path

from worker_bees_settings import CONFIG_FILE, SCHEDULE_FILE, SettingsError, folder, load_settings

SAFETY_MINUTES = 10  # never touch files due sooner than this
SCHED_SUFFIX = ".sched"  # files this script makes; it ignores everything else

MONTH_NAMES = ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"]
DAY_NAMES = ["sun", "mon", "tue", "wed", "thu", "fri", "sat"]

# the five time fields of a crontab line: name, lowest, highest, names allowed
FIELDS = [
    ("minute", 0, 59, None),
    ("hour", 0, 23, None),
    ("day of month", 1, 31, None),
    ("month", 1, 12, MONTH_NAMES),  # jan = 1
    ("day of week", 0, 7, DAY_NAMES),  # sun = 0, and 7 is Sunday too
]


class ScheduleError(SettingsError):
    """A problem in the schedule that someone needs to fix."""


# ------------------------------------------------------- reading a crontab line


def to_number(text, field):
    """'5' -> 5, and for month and day of week a name too: 'mar' -> 3, 'tue' -> 2."""
    name, low, high, names = field
    if text.isdigit():
        return int(text)
    if names and text in names:
        return names.index(text) + low
    raise ScheduleError(f"{name}: '{text}' is not a number from {low} to {high}")


def parse_field(text, field):
    """Return the set of numbers a field allows, e.g. '*/15' as a minute -> {0, 15, 30, 45}.

    A field is a comma separated list of parts. Each part is * (every value),
    a number, or a range like 1-5, and can end in /step: */15, 8-18/2.
    """
    name, low, high, _ = field
    values = set()
    for part in text.lower().split(","):
        base, has_step, step_text = part.partition("/")
        step = 1
        if has_step:
            if not step_text.isdigit() or int(step_text) == 0:
                raise ScheduleError(f"{name}: '{part}' needs a whole number after the /, like */15")
            step = int(step_text)
        if base == "*":
            first, last = low, high
        elif "-" in base:
            first_text, last_text = base.split("-", 1)
            first, last = to_number(first_text, field), to_number(last_text, field)
        else:
            first = to_number(base, field)
            last = high if has_step else first  # 5/10 means 5, 15, 25 ...
        if not low <= first <= last <= high:
            raise ScheduleError(f"{name}: '{part}' should be within {low}-{high}, low to high")
        values.update(range(first, last + 1, step))
    return values


def job_name(script):
    """The name a job gets in the queue: the script's file name, e.g. jobs/ftp_upload.py -> ftp_upload."""
    return re.sub(r"[^A-Za-z0-9_-]", "_", Path(script).stem) or "job"


def parse_line(line, label):
    """Turn one crontab line into a job, a dict of the allowed values for each field."""
    parts = line.split(None, 5)
    if len(parts) < 6:
        raise ScheduleError(f"{label}: should be five time fields and then the script, "
                            f"like  0 8 * * 1-5  jobs/report.py")
    day_of_month, day_of_week, script = parts[2], parts[4], parts[5]
    sets = []
    for text, field in zip(parts[:5], FIELDS):
        try:
            sets.append(parse_field(text, field))
        except ScheduleError as error:
            raise ScheduleError(f"{label}: {error}")
    days_of_week = {7 if d == 0 else d for d in sets[4]}  # one number for Sunday
    return {
        "script": script.strip(),
        "name": job_name(script.strip()),
        "minutes": sorted(sets[0]),
        "hours": sorted(sets[1]),
        "days_of_month": sets[2],
        "months": sets[3],
        "days_of_week": days_of_week,
        # a day field starting with * (even */2) switches off the either-one rule in day_matches
        "any_day_of_month": day_of_month.startswith("*"),
        "any_day_of_week": day_of_week.startswith("*"),
    }


def day_matches(day, job):
    """Return True if the job runs on the date `day`.

    The cron rule: if both day of month and day of week are set (neither
    starts with *), a day matching EITHER one is enough. Otherwise it has to
    match both (a plain * matches every day anyway).
    """
    if day.month not in job["months"]:
        return False
    by_month_day = day.day in job["days_of_month"]
    by_week_day = day.isoweekday() in job["days_of_week"]  # Monday 1 ... Sunday 7
    if job["any_day_of_month"] or job["any_day_of_week"]:
        return by_month_day and by_week_day
    return by_month_day or by_week_day


# ------------------------------------------------------ checking the files


def read_settings(settings):
    """Return (queue folder, forward_days) from the settings file."""
    forward_days = settings.get("forward_days")
    if not isinstance(forward_days, int) or forward_days < 0:
        raise SettingsError(f"forward_days in {CONFIG_FILE.name} should be a whole number like 7")
    return folder(settings, "queue_folder"), forward_days


def read_schedule(path):
    """Check every line of the schedule and return the jobs. Reports all problems at once."""
    if not path.exists():
        raise ScheduleError(f"File not found: {path}")
    # utf-8-sig copes with the invisible marker Notepad sometimes adds
    lines = path.read_text(encoding="utf-8-sig").splitlines()

    jobs, problems = [], []
    for number, line in enumerate(lines, start=1):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        try:
            jobs.append(parse_line(line, f"line {number}"))
        except ScheduleError as error:
            problems.append(str(error))

    if problems:
        raise ScheduleError(f"Problems in {path.name}:\n" + "\n".join(f"  - {p}" for p in problems))
    if not jobs:
        # an empty schedule would delete every future job, so treat it as a mistake
        raise ScheduleError(f"No jobs found in {path.name}")
    return jobs


# -------------------------------------------------------- building the queue


def wanted_files(jobs, today, forward_days, cutoff):
    """Return {filename: file contents} for every run after cutoff, up to forward_days ahead."""
    wanted = {}
    for offset in range(forward_days + 1):
        day = today + timedelta(days=offset)
        for job in jobs:
            if not day_matches(day, job):
                continue
            for hour in job["hours"]:
                for minute in job["minutes"]:
                    start = datetime(day.year, day.month, day.day, hour, minute)
                    if start <= cutoff:
                        continue
                    name = f"{start:%Y%m%d_%H%M%S}_{job['name']}{SCHED_SUFFIX}"
                    contents = f"{job['script']}\n"
                    if wanted.get(name, contents) != contents:
                        raise ScheduleError(
                            f"Two different scripts called {job['name']} both run at {start:%Y-%m-%d %H:%M}. "
                            f"Rename one of them: the queue tells jobs apart by script name and time.")
                    wanted[name] = contents
    return wanted


def future_sched_files(queue, cutoff):
    """Return {filename: contents} for the .sched files in the queue due after cutoff."""
    cutoff_text = f"{cutoff:%Y%m%d_%H%M%S}"
    found = {}
    for path in queue.glob(f"*{SCHED_SUFFIX}"):
        if path.name[:15] <= cutoff_text:
            continue  # due now or soon: a worker may be about to take it
        found[path.name] = path.read_text(encoding="utf-8", errors="replace")
    return found


def main():
    preview = "--preview" in sys.argv[1:]

    # 1. check everything before touching any files
    now = datetime.now()
    cutoff = now + timedelta(minutes=SAFETY_MINUTES)
    try:
        queue, forward_days = read_settings(load_settings())
        jobs = read_schedule(SCHEDULE_FILE)
        wanted = wanted_files(jobs, now.date(), forward_days, cutoff)
    except SettingsError as error:
        print(f"STOPPED - nothing was changed.\n{error}")
        return 1

    existing = future_sched_files(queue, cutoff)

    # new files, and files whose contents changed (e.g. a new script path)
    to_write = [name for name in sorted(wanted) if existing.get(name) != wanted[name]]
    # files for runs that are no longer in the schedule
    to_delete = sorted(set(existing) - set(wanted))

    last_day = now.date() + timedelta(days=forward_days)
    print(f"Queue folder: {queue}")
    print(f"Schedule: {len(jobs)} job(s). Building up to {last_day:%a %d %b %Y}.")
    print(f"{len(wanted)} run(s) wanted: {len(to_write)} to write, {len(to_delete)} to delete, "
          f"{len(wanted) - len(to_write)} already in place.")

    if preview:
        for name in to_write:
            print(f"  would write   {name}")
        for name in to_delete:
            print(f"  would delete  {name}")
        print("Preview only - nothing was changed.")
        return 0

    # 2. write new and changed files
    for name in to_write:
        (queue / name).write_text(wanted[name], encoding="utf-8")
        print(f"  wrote    {name}")

    # 3. only now delete files that are no longer in the schedule
    for name in to_delete:
        (queue / name).unlink(missing_ok=True)
        print(f"  deleted  {name}")

    print("Done.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
