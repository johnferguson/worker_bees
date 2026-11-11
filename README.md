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

- A job file's first line is the script to run. Relative paths are looked up in
  `scripts_directory` first, then in this folder; full paths work too.
- `000_worker_bees_queue.toml` stays on each worker computer. It tells that
  worker where the shared folders are: `top_level_directory` for the queue and
  `scripts_directory` for the job scripts. Put both on the shared folder so
  every worker sees the same jobs and runs the same scripts.
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
| `000_worker_bees_queue.toml` | This machine's settings: where the queue folders and job scripts are, how far ahead to build, job timeout |
| `001_worker_bees_crontab.txt` | The scheduled jobs, one per line like a crontab. The top of the file explains the format |
| `ZZZ_check_folders.py` | Checks the folders exist |
| `ZZZ_build_queue.py` | Writes the `.sched` files from the schedule. `--preview` shows what it would do |
| `ZZZ_worker.py` | The worker. Runs due jobs until none are left, then exits |
| `worker_bees_settings.py` | Reads the settings file for the other scripts |

## Setting up

1. Set up the accounts (below). Then, logged in as the worker account,
   install [uv](https://docs.astral.sh/uv/). It installs Python and each
   script's packages, without admin rights.
2. Set `top_level_directory` in `000_worker_bees_queue.toml`, and create the
   four folders there. Set `scripts_directory` to the folder holding your job
   scripts. `uv run ZZZ_check_folders.py` checks them.
3. Put your jobs in `001_worker_bees_crontab.txt`, one per line like a
   crontab, check them with `uv run ZZZ_build_queue.py --preview`, then run
   `uv run ZZZ_build_queue.py`:

   ```
   # minute hour day-of-month month day-of-week  script
   0 8,13 * * 1-5   jobs/ftp_upload.py
   ```
4. Start a worker every few minutes on each machine (below).

### Accounts and logins

Workers use two accounts, both called `worker_bees`. Neither one's password
goes in any worker_bees file.

**On the Unix server**, an account that can only reach the queue share.
As root, make a user that can't log in to the server itself, give it the
queue folder, and set its Samba password:

```
useradd -s /usr/bin/false worker_bees
chown -R worker_bees /path/to/queue/folder
smbpasswd -a worker_bees
```

Then limit the share to it in `smb.conf`:

```
[worker_bees]
   path = /path/to/queue/folder
   valid users = worker_bees
   read only = no
```

**On each Windows worker PC**, a standard (not administrator) local account
for the worker to run as. In a Command Prompt run as administrator:

```
net user worker_bees * /add
```

Then store the server login in that account's Credential Manager. Windows
keeps it encrypted, readable only by that account, and uses it whenever
`//server/worker_bees` is opened:

```
runas /profile /user:worker_bees cmd
```

and in the window that opens:

```
cmdkey /add:server /user:worker_bees /pass
```

(`/pass` with nothing after it asks for the password, so it isn't saved in
the command history.) The `worker_bees` folder must be readable by this
account.

If the Unix server is joined to the Windows domain, use a domain account
for the worker instead and skip `cmdkey`: the server takes its Windows login.

**Jobs that need a password of their own** should read it with the
[`keyring`](https://pypi.org/project/keyring/) package, which uses Credential
Manager on Windows. Don't print it: the job's output is written into the job
file on the share.

### Windows: Task Scheduler

Create a task with:

- **Run as:** the `worker_bees` account, with "Run whether user is logged on
  or not". Leave "Do not store password" unticked, or the task can't use the
  login saved with `cmdkey`.
- **Program:** the full path to `uv.exe` (`where uv`, as the worker account,
  shows it, usually `C:\Users\worker_bees\.local\bin\uv.exe`)
- **Arguments:** `run ZZZ_worker.py`
- **Start in:** this folder
- **Trigger:** Daily, repeat every 5 minutes, for a duration of Indefinitely
- **Settings:** If the task is already running: Do not start a new instance

### WSL: cron

WSL can't open `//server/...` paths, so mount the share. Put the login in a
file only root can read, `/etc/worker_bees.cred`:

```
username=worker_bees
password=...
```

```
sudo chmod 600 /etc/worker_bees.cred
```

and add this line to `/etc/fstab` (needs `sudo apt install cifs-utils`):

```
//server/worker_bees /mnt/worker_bees cifs credentials=/etc/worker_bees.cred,uid=YOUR_WSL_USER,iocharset=utf8 0 0
```

Set `top_level_directory_linux` (and `scripts_directory_linux`) in the
settings file to paths under `/mnt/worker_bees`, then add this with
`crontab -e`, changing the folder:

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
