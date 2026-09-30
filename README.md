# worker_bees

A simple job queue that doesn't depend on any one machine. Jobs wait as files
in a shared folder. Any number of workers (Windows PCs, or WSL) check the
folder every few minutes, take the oldest job that is due, run its Python
script and file the result.

## How it works

```
top_level_directory/
  001_queue/       jobs waiting to run: yyyymmdd_hhmmss_name.sched (or any other ending)
  002_running/     one folder per worker, holding the job it is running now
  003_failed/      finished jobs whose script failed
  004_complete/    finished jobs whose script worked
```

- A job file's first line is the script to run. Relative paths start from this
  folder; full paths work too.
- A worker claims a job by moving it into its own `002_running` folder. Only one
  worker can move a file, so a job never runs twice at once.
- When a job finishes, the worker adds its output to the end of the job file,
  then moves the file to `003_failed` or `004_complete`.
- `ZZZ_build_queue.py` turns the schedule into `.sched` files up to
  `forward_days` ahead. It runs every night as a job itself.
- To run something one-off, put a file in `001_queue` named
  `yyyymmdd_hhmmss_name.request` with the script on the first line.

## Files

| File | What it is |
|---|---|
| `000_worker_bees_queue.toml` | Settings: where the folders are, how far ahead to build, job timeout |
| `001_worker_bees_schedule.toml` | The scheduled jobs. The top of the file explains the options |
| `ZZZ_check_folders.py` | Checks the folders exist |
| `ZZZ_build_queue.py` | Writes the `.sched` files from the schedule. `--preview` shows what it would do |
| `ZZZ_worker.py` | The worker. Runs due jobs until none are left, then exits |
| `worker_bees_settings.py` | Reads the settings file for the other scripts |

## Setting up

1. Install [uv](https://docs.astral.sh/uv/). It installs Python and each
   script's packages, without admin rights.
2. Set `top_level_directory` in `000_worker_bees_queue.toml`, and create the
   four folders there. `uv run ZZZ_check_folders.py` checks them.
3. Put your jobs in `001_worker_bees_schedule.toml`, check them with
   `uv run ZZZ_build_queue.py --preview`, then run `uv run ZZZ_build_queue.py`.
4. Start a worker every few minutes on each machine (below).

### Windows: Task Scheduler

Create a task with:

- **Program:** the full path to `uv.exe` (`where uv` shows it, usually
  `C:\Users\<you>\.local\bin\uv.exe`)
- **Arguments:** `run ZZZ_worker.py`
- **Start in:** this folder
- **Trigger:** Daily, repeat every 5 minutes, for a duration of Indefinitely
- **Settings:** If the task is already running: Do not start a new instance

### WSL: cron

Set `top_level_directory_linux` in the settings file (`C:/` is `/mnt/c/` in
WSL), then add this with `crontab -e`, changing the folder:

```
*/5 * * * * cd /mnt/c/path/to/worker_bees && $HOME/.local/bin/uv run ZZZ_worker.py >> $HOME/worker_bees.log 2>&1
```

WSL only runs while it is open, and cron has to be started inside it
(`sudo service cron start`), so Task Scheduler is the more dependable choice.

## Good to know

- If a machine stops mid-job (a reboot, say), that job is put back in the queue
  the next time the worker starts there, so it runs again. Keep that in mind for
  jobs that shouldn't run twice.
- Only one worker runs at a time on each machine. Windows and WSL on the same PC
  count as two workers.
- Scripts run from their own folder, so they can open files next to them by name.
- A script tells the worker it failed by exiting with an error: an uncaught
  exception or `sys.exit(1)`.
