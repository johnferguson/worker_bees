# worker_bees roadmap

Notes on where this project is going.

## The main idea: keep it simple

- One central shared folder holds the queue. Each job is a file.
- Any number of workers check the queue and take jobs that are due.
- A queue builder rebuilds the future jobs from a schedule file that works
  like crontab.

Everything below builds on that. None of it should make the core harder to
understand.

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
