"""Run the jobs that are due in the queue.

Start it every few minutes from Windows Task Scheduler or cron. Each time it:
  1. makes sure it is the only worker running on this machine. If an earlier
     one is still busy with a long job, this one quietly exits.
  2. puts back any job this machine was running when it last stopped
     unexpectedly (a reboot, for example), so it runs again.
  3. takes the oldest due job, runs its script, writes the output into the
     job file and moves the file to the complete or failed folder.
  4. repeats step 3 until nothing is due, then exits.

A worker claims a job by moving it into its own folder inside the running
folder (e.g. 002_running/PC07). Only one worker can move a file, so a job
is never run by two workers at once.

Run it with:  uv run ZZZ_worker.py
"""

import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path

from worker_bees_settings import CONFIG_FILE, HERE, SettingsError, folder, load_settings

# Windows and WSL on the same PC count as two different workers
WORKER_NAME = socket.gethostname() + ("" if os.name == "nt" else "-linux")

JOB_FILE = re.compile(r"\d{8}_\d{6}_.+")  # yyyymmdd_hhmmss_name.anything


def take_machine_lock():
    """Return an open lock file, or None if another worker on this machine has it.

    The operating system lets go of the lock when a worker exits for any
    reason, even a crash or a reboot, so it can never get stuck.
    """
    handle = open(Path(tempfile.gettempdir()) / f"worker_bees_{WORKER_NAME}.lock", "a")
    try:
        if os.name == "nt":
            import msvcrt

            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl

            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        handle.close()
        return None
    return handle


def move_into(path, destination_folder):
    """Move a file into a folder, adding the time to its name if that name is taken."""
    destination = destination_folder / path.name
    if destination.exists():
        destination = destination_folder / f"{path.stem}_{datetime.now():%H%M%S}{path.suffix}"
    path.rename(destination)
    return destination


def put_back_interrupted_jobs(my_running, queue):
    """Jobs left in this worker's running folder were cut off, so queue them again.

    Only called once the machine lock is held, so nothing here is still running.
    """
    for path in sorted(my_running.iterdir()):
        with open(path, "a", encoding="utf-8") as f:
            f.write(f"\n--- {datetime.now():%Y-%m-%d %H:%M:%S} interrupted on {WORKER_NAME}, put back in the queue\n")
        move_into(path, queue)
        print(f"put back  {path.name}")


def claim_next_job(queue, my_running):
    """Move the oldest due job into this worker's running folder and return its new path.

    Returns None when nothing is due.
    """
    now = f"{datetime.now():%Y%m%d_%H%M%S}"
    for name in sorted(os.listdir(queue)):  # the date at the front makes this oldest first
        if not JOB_FILE.fullmatch(name) or name[:15] > now:
            continue
        try:
            (queue / name).rename(my_running / name)
        except OSError:
            continue  # another worker got there first
        return my_running / name
    return None


def run_job(path, timeout_minutes):
    """Run the script named on the first line of the job file and add the output to the file.

    Returns True if the script finished with exit code 0.
    """
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    script_text = lines[0].strip() if lines else ""
    script = Path(script_text)
    if not script.is_absolute():
        script = HERE / script  # relative paths start from the worker_bees folder

    started = datetime.now()
    if not script_text:
        code, output = None, "The first line of the job file should be the script to run.\n"
    elif not script.is_file():
        code, output = None, f"Script not found: {script}\n"
    else:
        # uv sets UV to its own location when it starts this worker
        uv = os.environ.get("UV") or shutil.which("uv")
        command = [uv, "run", str(script)] if uv else [sys.executable, str(script)]
        try:
            result = subprocess.run(
                command,
                cwd=script.parent,  # run it from its own folder, like double-clicking it
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,  # errors go in the same log, in the right order
                env={**os.environ, "PYTHONUTF8": "1"},
                timeout=timeout_minutes * 60,
            )
            code, output = result.returncode, result.stdout
        except subprocess.TimeoutExpired as error:
            code = None
            output = (error.stdout or b"") + f"\nSTOPPED: still running after {timeout_minutes} minutes\n".encode()
        output = output.decode("utf-8", errors="replace").replace("\r\n", "\n")

    with open(path, "a", encoding="utf-8") as f:
        f.write(f"\n--- worker: {WORKER_NAME}\n")
        f.write(f"--- script: {script}\n")
        f.write(f"--- started: {started:%Y-%m-%d %H:%M:%S}  finished: {datetime.now():%Y-%m-%d %H:%M:%S}\n")
        f.write(f"--- exit code: {code}\n")
        f.write(output if output.endswith("\n") else output + "\n")
    return code == 0


def main():
    try:
        settings = load_settings()
        queue = folder(settings, "queue_folder")
        running = folder(settings, "running_folder")
        failed = folder(settings, "failed_folder")
        complete = folder(settings, "complete_folder")
        timeout_minutes = settings.get("job_timeout_minutes", 240)
        if not isinstance(timeout_minutes, (int, float)) or timeout_minutes <= 0:
            raise SettingsError(f"job_timeout_minutes in {CONFIG_FILE.name} should be a number like 240")
    except SettingsError as error:
        print(error)
        return 1

    lock = take_machine_lock()
    if lock is None:
        print(f"Another worker is already running on {WORKER_NAME}, leaving it to carry on.")
        return 0

    my_running = running / WORKER_NAME
    my_running.mkdir(exist_ok=True)
    put_back_interrupted_jobs(my_running, queue)

    while True:
        job = claim_next_job(queue, my_running)
        if job is None:
            break
        print(f"running   {job.name}")
        worked = run_job(job, timeout_minutes)
        finished = move_into(job, complete if worked else failed)
        print(f"{'complete' if worked else 'FAILED  '}  {finished.name}")

    print("Nothing more is due.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
