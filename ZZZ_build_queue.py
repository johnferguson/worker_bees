"""Build the job queue from the schedule.

Reads 000_worker_bees_queue.toml (settings) and 001_worker_bees_schedule.toml
(the jobs), then makes sure the queue folder holds one .sched file for
every scheduled run from now until forward_days ahead.

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
import tomllib
from datetime import date, datetime, timedelta
from pathlib import Path

HERE = Path(__file__).parent
CONFIG_FILE = HERE / "000_worker_bees_queue.toml"
SCHEDULE_FILE = HERE / "001_worker_bees_schedule.toml"

SAFETY_MINUTES = 10  # never touch files due sooner than this
SCHED_SUFFIX = ".sched"  # files this script makes; it ignores everything else

DAY_NAMES = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
ORDINALS = {"1st": 1, "2nd": 2, "3rd": 3, "4th": 4, "5th": 5}
JOB_SETTINGS = {"name", "script", "days", "times", "every_minutes", "between", "enabled"}


class ScheduleError(Exception):
    """A problem in the settings or schedule that someone needs to fix."""


def load_toml(path):
    if not path.exists():
        raise ScheduleError(f"File not found: {path}")
    try:
        # utf-8-sig copes with the invisible marker Notepad sometimes adds
        return tomllib.loads(path.read_text(encoding="utf-8-sig"))
    except tomllib.TOMLDecodeError as error:
        raise ScheduleError(f"Could not read {path.name}: {error}")


# ---------------------------------------------------------------- day rules


def expand_days(rule):
    """'mon-fri' -> ['mon', 'tue', 'wed', 'thu', 'fri'],  'mon,wed' -> ['mon', 'wed']"""
    names = []
    for part in rule.split(","):
        if "-" in part:
            first, last = part.split("-", 1)
        else:
            first = last = part
        if first not in DAY_NAMES or last not in DAY_NAMES:
            raise ScheduleError(f"days = '{rule}' has a day name that isn't one of {', '.join(DAY_NAMES)}")
        if DAY_NAMES.index(first) > DAY_NAMES.index(last):
            raise ScheduleError(f"days = '{rule}' should go forwards, e.g. mon-fri not fri-mon")
        names += DAY_NAMES[DAY_NAMES.index(first) : DAY_NAMES.index(last) + 1]
    return names


def day_matches(day, rule):
    """Return True if the date `day` fits the days rule, e.g. 'mon-fri' or '2nd tue'.

    Raises ScheduleError if the rule isn't understood.
    """
    rule = " ".join(rule.lower().split())  # tidy case and spacing
    rule = re.sub(r" ?([,-]) ?", r"\1", rule)  # 'mon, wed' -> 'mon,wed'
    weekday = DAY_NAMES[day.weekday()]

    if rule == "daily":
        return True

    if rule == "last day":
        # tomorrow is in a different month
        return (day + timedelta(days=1)).month != day.month

    if rule.startswith("day "):
        try:
            numbers = [int(n) for n in rule[4:].split(",")]
        except ValueError:
            numbers = []
        if not numbers or not all(1 <= n <= 31 for n in numbers):
            raise ScheduleError(f"days = '{rule}' should look like 'day 1' or 'day 1,15'")
        return day.day in numbers

    words = rule.split(" ")
    if len(words) == 2:  # '2nd tue', 'last fri'
        which, name = words
        if name not in DAY_NAMES or (which != "last" and which not in ORDINALS):
            raise ScheduleError(f"days = '{rule}' should look like '2nd tue' or 'last fri'")
        if weekday != name:
            return False
        if which == "last":
            # a week from now is in a different month
            return (day + timedelta(days=7)).month != day.month
        # days 1-7 hold the 1st of each weekday, days 8-14 the 2nd, and so on
        return (day.day - 1) // 7 + 1 == ORDINALS[which]

    return weekday in expand_days(rule)


# ------------------------------------------------------------------- times


def parse_time(text, label):
    try:
        return datetime.strptime(text, "%H:%M").time()
    except (TypeError, ValueError):
        raise ScheduleError(f"{label}: '{text}' is not a time like '08:00'")


def run_times(job, label):
    """Return every time of day the job runs, from 'times' or 'every_minutes' + 'between'."""
    if "times" in job:
        if not isinstance(job["times"], list) or not job["times"]:
            raise ScheduleError(f'{label}: times should be a list like ["08:00", "13:00"]')
        return [parse_time(text, label) for text in job["times"]]

    step = job["every_minutes"]
    between = job.get("between")
    if not isinstance(step, int) or step < 1:
        raise ScheduleError(f"{label}: every_minutes should be a whole number like 30")
    if not isinstance(between, list) or len(between) != 2:
        raise ScheduleError(f'{label}: between should look like ["07:00", "18:00"]')

    start = datetime.combine(date.today(), parse_time(between[0], label))
    end = datetime.combine(date.today(), parse_time(between[1], label))
    if start > end:
        raise ScheduleError(f"{label}: between should go from earlier to later")
    times = []
    while start <= end:
        times.append(start.time())
        start += timedelta(minutes=step)
    return times


# ------------------------------------------------------ checking the files


def read_settings(settings):
    """Return (queue folder, forward_days) from the settings file."""
    for key in ["top_level_directory", "queue_folder", "forward_days"]:
        if key not in settings:
            raise ScheduleError(f"{key} is not set in {CONFIG_FILE.name}")

    forward_days = settings["forward_days"]
    if not isinstance(forward_days, int) or forward_days < 0:
        raise ScheduleError(f"forward_days in {CONFIG_FILE.name} should be a whole number like 7")

    queue = Path(settings["top_level_directory"]) / settings["queue_folder"]
    if not queue.is_dir():
        raise ScheduleError(f"Queue folder not found: {queue}  (ZZZ_check_folders.py can help)")
    return queue, forward_days


def check_job(job, label, names_seen):
    """Raise ScheduleError if anything about this job is wrong."""
    unknown = set(job) - JOB_SETTINGS
    if unknown:
        raise ScheduleError(f"{label}: unknown setting(s): {', '.join(sorted(unknown))}")
    for key in ["name", "script", "days"]:
        if not isinstance(job.get(key), str) or not job[key].strip():
            raise ScheduleError(f"{label}: {key} is missing (it should be text in quotes)")

    if not re.fullmatch(r"[A-Za-z0-9_-]+", job["name"]):
        raise ScheduleError(f"{label}: name can only use letters, numbers, _ and -")
    if job["name"] in names_seen:
        raise ScheduleError(f"{label}: there is already a job called {job['name']}")
    names_seen.add(job["name"])

    if ("times" in job) == ("every_minutes" in job):
        raise ScheduleError(f"{label}: needs either times or every_minutes (not both)")
    if not isinstance(job.get("enabled", True), bool):
        raise ScheduleError(f"{label}: enabled should be true or false")

    try:
        day_matches(date.today(), job["days"])  # raises if the rule isn't understood
    except ScheduleError as error:
        raise ScheduleError(f"{label}: {error}")
    run_times(job, label)  # raises if the times are wrong


def check_schedule(schedule):
    """Check every job and return the list of jobs. Reports all problems at once."""
    jobs = schedule.get("job", [])
    if not isinstance(jobs, list) or not jobs:
        # an empty schedule would delete every future job, so treat it as a mistake
        raise ScheduleError(f"No [[job]] sections found in {SCHEDULE_FILE.name}")

    problems = []
    names_seen = set()
    for number, job in enumerate(jobs, start=1):
        label = f"job {number} ({job.get('name', 'no name')})"
        try:
            check_job(job, label, names_seen)
        except ScheduleError as error:
            problems.append(str(error))

    if problems:
        raise ScheduleError(f"Problems in {SCHEDULE_FILE.name}:\n" + "\n".join(f"  - {p}" for p in problems))
    return jobs


# -------------------------------------------------------- building the queue


def wanted_files(jobs, today, forward_days, cutoff):
    """Return {filename: file contents} for every run after cutoff, up to forward_days ahead."""
    wanted = {}
    for offset in range(forward_days + 1):
        day = today + timedelta(days=offset)
        for job in jobs:
            if not job.get("enabled", True) or not day_matches(day, job["days"]):
                continue
            for run_time in run_times(job, job["name"]):
                start = datetime.combine(day, run_time)
                if start > cutoff:
                    name = f"{start:%Y%m%d_%H%M%S}_{job['name']}{SCHED_SUFFIX}"
                    wanted[name] = f"{job['script']}\n"
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
    try:
        queue, forward_days = read_settings(load_toml(CONFIG_FILE))
        jobs = check_schedule(load_toml(SCHEDULE_FILE))
    except ScheduleError as error:
        print(f"STOPPED - nothing was changed.\n{error}")
        return 1

    now = datetime.now()
    cutoff = now + timedelta(minutes=SAFETY_MINUTES)
    wanted = wanted_files(jobs, now.date(), forward_days, cutoff)
    existing = future_sched_files(queue, cutoff)

    # new files, and files whose contents changed (e.g. a new script path)
    to_write = [name for name in sorted(wanted) if existing.get(name) != wanted[name]]
    # files for runs that are no longer in the schedule
    to_delete = sorted(set(existing) - set(wanted))

    paused = sum(1 for job in jobs if not job.get("enabled", True))
    last_day = now.date() + timedelta(days=forward_days)
    print(f"Queue folder: {queue}")
    print(f"Schedule: {len(jobs)} job(s), {paused} paused. Building up to {last_day:%a %d %b %Y}.")
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
