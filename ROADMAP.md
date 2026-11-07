# worker_bees roadmap

Notes on where this project is going.

## The main idea: keep it simple

- One central shared folder holds the queue. Each job is a file.
- Any number of workers check the queue and take jobs that are due.
- A queue builder rebuilds the future jobs from a schedule file that works
  like crontab.

Everything below builds on that. None of it should make the core harder to
understand.

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
- [ ] The SharePoint sync, so the machine can see the shared queue folder
- [ ] The worker_bees folder itself, with the right settings for this machine
- [ ] The Task Scheduler task (or cron on WSL) that starts the worker every
      few minutes
- [ ] A final check that confirms the new worker is ready, e.g. it can see the
      folders and run a test job

Open questions:

- Can the SharePoint sync be scripted, or does it need a short manual
  checklist? It's set up through OneDrive, which is hard to automate.
- What differs from one machine to the next? That decides what the setup
  has to ask for, and what can be filled in automatically.

### 2. Requirements table

A table, kept outside the jobs themselves, that lists what each job needs to
run:

- [ ] Which syncs it needs (e.g. a SharePoint library)
- [ ] Which Python libraries it needs
- [ ] Anything else it relies on (network drives, programs, logins)

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

A standard way to keep the output of jobs.

- [ ] Decide what gets logged and where. At the moment each job's output is
      added to the end of its own job file, which then goes into the failed
      or complete folder.
- [ ] Logs should be easy to read for people and for the monitor (plan 5).

### 5. Monitoring

A way to watch the jobs: what's waiting, what's running, what failed.

- [ ] The monitor needs no special data of its own. It only reads the queue
      folders and the logs (plan 4), a bit like `tail` on a log file.
- [ ] Turning the monitor off, or never using it, changes nothing else.
