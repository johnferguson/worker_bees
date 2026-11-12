"""Check that this machine can work the queue.

Does to a harmless test file exactly what a worker does to a real job:
  1. checks the folders exist
  2. writes a test file in the queue folder and reads it back
  3. moves it the way a job moves: queue -> this worker's running folder
     -> failed -> complete
  4. tries to move it a second time, which must fail. That's what stops
     two workers taking the same job.
  5. deletes it

The test file's name doesn't look like a job, so a worker never takes it.
It is cleaned up even if a step fails.

Run it with:  uv run ZZZ_check_worker.py
"""

import sys
import time
from datetime import datetime

from worker_bees_settings import CONFIG_FILE, SettingsError, load_settings
from ZZZ_worker import JOB_FILE, WORKER_NAME

FOLDER_KEYS = ["queue_folder", "running_folder", "failed_folder", "complete_folder"]

failures = 0


def report(ok, step, detail=""):
    global failures
    if not ok:
        failures += 1
    print(f"  {'ok    ' if ok else 'FAILED'}  {step}" + (f": {detail}" if detail else ""))
    return ok


def check_folders(settings):
    """Return {key: Path} for the four folders, or None if any are missing."""
    top_dir = settings["top_dir"]
    print(f"Top level directory: {top_dir}")
    if not report(top_dir.is_dir(), "top level directory exists", "" if top_dir.is_dir() else "not found"):
        return None

    folders = {}
    for key in FOLDER_KEYS:
        if key not in settings:
            report(False, f"{key} is set", f"missing from {CONFIG_FILE.name}")
            continue
        path = top_dir / settings[key]
        if report(path.is_dir(), f"{settings[key]} exists", "" if path.is_dir() else "not found"):
            folders[key] = path
    return folders if len(folders) == len(FOLDER_KEYS) else None


def move(path, destination_folder, label):
    """Move the test file into a folder. Return its new path, or None if that failed."""
    target = destination_folder / path.name
    try:
        path.rename(target)
    except OSError as error:
        report(False, label, str(error))
        return None
    report(True, label)
    return target


def check_access(folders):
    """Write, read, move and delete a test file. Return when done or at the first failure."""
    name = f"zzz_check_{WORKER_NAME}_{datetime.now():%Y%m%d_%H%M%S}.txt"
    assert not JOB_FILE.fullmatch(name)  # a worker must never take the test file
    contents = f"worker_bees check from {WORKER_NAME} at {datetime.now():%Y-%m-%d %H:%M:%S}\n"

    my_running = folders["running_folder"] / WORKER_NAME
    path = folders["queue_folder"] / name
    print(f"\nTest file: {name}")

    try:
        try:
            my_running.mkdir(exist_ok=True)
        except OSError as error:
            report(False, f"create this worker's running folder ({WORKER_NAME})", str(error))
            return
        report(True, f"this worker's running folder ({WORKER_NAME}) is there")

        try:
            path.write_text(contents, encoding="utf-8")
        except OSError as error:
            report(False, "write a file in the queue", str(error))
            return
        report(True, "write a file in the queue")

        try:
            read_back = path.read_text(encoding="utf-8")
        except OSError as error:
            report(False, "read it back", str(error))
            return
        if not report(read_back == contents, "read it back", "" if read_back == contents else "contents changed"):
            return

        start = path
        path = move(path, my_running, "move it into the running folder (taking a job)")
        if path is None:
            path = start
            return

        # the file has gone from the queue, so a second move must fail
        try:
            start.rename(my_running / f"{name}.second")
            report(False, "a second move of the same job fails", "it worked, so two workers could take one job")
            (my_running / f"{name}.second").unlink(missing_ok=True)
        except OSError:
            report(True, "a second move of the same job fails")

        for key, label in [("failed_folder", "failed"), ("complete_folder", "complete")]:
            moved = move(path, folders[key], f"move it to the {label} folder")
            if moved is None:
                return
            path = moved

        try:
            path.unlink()
        except OSError as error:
            report(False, "delete it", str(error))
            return
        report(True, "delete it")
        path = None

    finally:
        if path is not None and path.exists():
            try:
                path.unlink()
                print("  (cleaned up the test file)")
            except OSError:
                print(f"  Could not delete the test file. Please delete it by hand: {path}")


def main():
    started = time.monotonic()
    print(f"Checking worker {WORKER_NAME}\n")
    try:
        settings = load_settings()
    except SettingsError as error:
        print(error)
        return 1

    folders = check_folders(settings)
    if folders is not None:
        check_access(folders)

    seconds = time.monotonic() - started
    if failures:
        print(f"\n{failures} check(s) FAILED. This worker isn't ready. ({seconds:.1f}s)")
        return 1
    print(f"\nAll checks passed. This worker is ready. ({seconds:.1f}s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
