# worker_bees roadmap

Notes on where this project is going.

## The main idea: keep it simple

- One central shared folder holds the queue. Each job is a file.
- Any number of workers check the queue and take jobs that are due.
- A queue builder rebuilds the future jobs from a schedule file that works
  like crontab.

Everything below builds on that. None of it should make the core harder to
understand.

## Decisions

- **One folder each, no folders per day.** This goes for the queue and for
  the failed and complete folders. Workers only look in one place, jobs that
  were missed (e.g. a PC was off overnight) are still the oldest files and
  get picked up next, and one-off jobs can be dropped in without picking a
  day folder. The date at the front of each file name already keeps them in
  time order.
- **The shared queue folder is not on SharePoint (or OneDrive).** Sync tools
  cause too many problems, and the queue depends on a job file only being
  movable by one worker at a time. A sync tool can't promise that: two PCs
  can both "move" the same file before they sync, and the job runs twice.
  The queue goes on our Unix server instead, shared over the network. Jobs
  can still use SharePoint for their own files.
- **A job's log lives in its own job file.** Whatever the script prints goes
  into the job file, so the file is the job's whole record: the script it
  ran, when, on which worker, and what happened. See plan 4.
- **Workers run under their own Windows account.** Each worker PC has a
  local `worker_bees` account, and the Task Scheduler task runs as it, not
  as whoever uses the PC. Its logins are kept in that account's own Windows
  Credential Manager, so people and programs (AI agents included) running
  under other accounts on the PC can't read them.
- **The server login can only reach the queue.** Workers log in to the
  Samba share with a `worker_bees` account on the server that can read and
  write the queue share and nothing else. If its password is ever found,
  the damage stays small.
- **Logins never go in worker_bees' own files.** Not in the settings file,
  the schedule, anything in git, a job file (whatever a script prints ends
  up there, on the share) or an environment variable (every job gets the
  worker's). They go in the places built for them: Windows Credential
  Manager, a root-only credentials file on Linux and WSL, keys in `~/.ssh`.

## Rule for everything else: optional add-ons

Each of the systems below is an add-on that you use only if you want it:

- The queue keeps working without any of them.
- Not using one is never extra work. Jobs and workers don't have to change.
- Where possible, an add-on reads what already exists (the queue folders, the
  job files, the logs) instead of keeping data of its own.

## Plans

### 1. Make it easy to set up a new worker

Setting up a new worker machine is tedious at the moment. The goal is a
quick, repeatable setup, probably built around uv, that covers everything a
worker needs:

- [ ] Python and every job's packages (uv can handle this)
- [ ] Access to the shared queue folder on the network
- [ ] Any SharePoint syncs that this machine's jobs need (see plan 2)
- [ ] The worker_bees folder itself, with the right settings for this machine
- [ ] The Task Scheduler task (or cron on WSL) that starts the worker every
      few minutes
- [ ] A final check that confirms the new worker is ready, e.g. it can see the
      folders and run a test job

Open questions:

- Samba is already set up on the Unix server, so Windows workers can reach
  the queue folder with a `//server/share` path. (Use that, not a mapped
  drive letter: Task Scheduler often runs with no one logged in, and
  drive letters don't exist then.) Linux and WSL workers still need it
  mounted, since WSL can't use a `\\server\share` path directly.
- Is the Unix server joined to the Windows domain? If it is, the worker
  account can be a domain account and the server takes its Windows login,
  so no password has to be stored on the PCs at all.
- The Unix server only holds the files. It has no Python, so it doesn't run
  a worker. The nightly queue build runs as an ordinary job on whichever
  PC worker picks it up, and `forward_days` (7) keeps the queue going if
  it's missed for a few nights.
- For jobs that need SharePoint files: can those syncs be scripted, or do
  they need a short manual checklist? They're set up through OneDrive,
  which is hard to automate.
- What differs from one machine to the next? That decides what the setup
  has to ask for, and what can be filled in automatically.

### 2. Requirements table

A table, kept outside the jobs themselves, that lists what each job needs to
run:

- [ ] Which syncs it needs (e.g. a SharePoint library)
- [ ] Which Python libraries it needs
- [ ] Anything else it relies on (network drives, programs, logins)
- [ ] SSH access to a server, for jobs that need it. Each worker gets its own
      key instead of a password, and the server limits what that key can do,
      so one PC's key can be removed without touching the others.

The job scripts don't change. If a job isn't in the table, it just runs as it
does now.

Open question:

- Should workers use the table to skip jobs they can't run, or should the
  table only be for people to read and for the worker check (plan 3)?

### 3. Worker check

A way to test a worker when it's turned on, to see what it can reach and
whether everything works as it should:

- [ ] Can it see the queue folders, and can it move files in them?
- [ ] Which syncs and drives can it reach?
- [ ] Are uv and Python working?
- [ ] If the requirements table (plan 2) is in use: which jobs can this
      worker run, and what's missing for the rest?

This fits with plan 1: the last step of setting up a new worker is to run
this check.

### 4. Logging

Each job's log goes into its own job file. Jobs don't need to do anything
special: whatever a script prints is logged.

Already working: the worker collects everything the script prints and adds
it to the end of the job file when the script finishes.

- [ ] Write the output into the job file line by line while the script runs,
      not all at once at the end. Then you can open a running job's file (or
      the monitor can) and see how far it has got, and if a PC stops
      mid-job, the output up to that point is kept.
- [ ] Put the time at the start of each line, so you can see how long each
      step took.
- [ ] Logs should be easy to read for people and for the monitor (plan 5).

### 5. Monitoring

A way to watch the jobs: what's waiting, what's running, what failed.

- [ ] The monitor needs no special data of its own. It only reads the queue
      folders and the logs (plan 4), a bit like `tail` on a log file.
- [ ] Turning the monitor off, or never using it, changes nothing else.
