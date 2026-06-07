---
name: configure-and-run-repo
description: Clone an external Git repository into the VM and get it actually running — install dependencies, run framework setup (migrations/build), write /app/config.json with a non-blocking run command and the right port, and verify the server answers. Use whenever the user says things like "download this repo and set it up / configure it / run it", "clone X and make it work", or "get this project running" with a Git URL.
---

# Configure and run a cloned repository

Goal end state, all of it: the repo cloned, its dependencies installed, framework
setup done, `/app/config.json` holding a **non-blocking** `run` command and the
**correct** `port`, and the server **verified up** (a real `curl` got a response).
Do not stop at "dependencies installing" — drive it to a working server.

Work autonomously and KEEP GOING across the whole runbook; only stop to ask if a
required secret (API key, DB password) is truly unavailable.

## 0. Inventory first (cheap; saves a failed-command round trip)

The VM baseline normally has `git`, `python3`/`pip3`, `python3-venv`, `curl` and a
build toolchain. Confirm what THIS task needs in one shot instead of discovering a
gap by letting a command fail:

    command -v git python3 pip3 node npm docker; python3 --version

apt-install only what is missing (see step 2 for how to install correctly).

## 1. Clone

Clone into `/app` (your persistent workspace). If `/app` already has the seed
files only (`readme.txt`, `config.json`), clone into a subfolder:

    git clone <url> /app/repo        # project root is then /app/repo (maybe /app/repo/<subdir>)

Note the **real project root** — many repos keep the app in a subdir (`src/`,
`backend/`, `app/`). Everything below (`pip install`, `manage.py`, the `run`
command) runs from that root, but **`config.json` and `readme.txt` must stay at
`/app`** (a workspace reset wipes everything under `/app` except those two).

## 2. Detect the project type — and prefer docker-compose

**If the repo ships a `docker-compose.yml`/`docker-compose.yaml` (and `docker` is
present), that IS its intended way to run — use it.** `docker compose up -d` builds
the image, starts the DB and the app with the env the author already wired, and
skips the entire venv/pip/PEP668/dependency-resolution minefield. This is almost
always the fastest, most reliable path; reach for the manual venv route only when
there is no compose file. Map the published host port into `config.json.port`
(read the compose `ports:`), then verify with `curl` (step 6).

Otherwise, read the manifests at the project root to decide the toolchain — never assume:

- Python: `requirements.txt`, `pyproject.toml`, `Pipfile`, `manage.py` (Django),
  `app.py`/`wsgi.py`/`asgi.py` (Flask/FastAPI), `Dockerfile`, `docker-compose.yml`.
- Node: `package.json` (look at `scripts.start`/`dev`/`build`), lockfile picks the
  manager (`package-lock.json`→npm, `pnpm-lock.yaml`→pnpm, `yarn.lock`→yarn).
- Read the repo's `README*` for the intended run command — copy it, don't invent.

## 3. Install dependencies (this is where runs usually go wrong)

**Installs are long: start them, then WAIT — do not babysit them.** `bash`
auto-promotes `apt-get install` / `pip install` / `npm install` to a BACKGROUND
job and gives you a `job_id`. Call `process(job_id, action="wait")` ONCE — it
blocks until the install finishes and returns the result. Do NOT poll
`action="status"` in a tight loop (it wastes tokens and time); `wait` is the tool
for "let it finish". When it returns, read the log to confirm success.

Things that look like failures but are NOT — keep waiting, do not intervene:
- **pip backtracking**: lines like `Using cached X-0.6.2 → 0.6.1 → 0.5.1 …` mean pip
  is resolving a version conflict by trying older releases. This is normal; it
  finishes on its own. It is NOT a reason to kill the install.
- **`python3 -m venv` taking a few seconds**: pip appears in `.venv/bin` only after
  it finishes bootstrapping. Don't `ls` for it mid-creation and panic.

Hard rules learned the hard way:
- NEVER `rm -rf` a venv (or any dir) while an install is running into it — you will
  corrupt your own work. If you must recreate it, `process(..., action="stop")`
  first.
- NEVER "fix" a missing Python dependency with `apt-get install python3-<lib>` when
  you have a venv — packages like `python3-matplotlib`/`python3-wordcloud` drag in
  ~1GB of TeX/Java/GUI deps. Install Python libs with pip into the venv.
- One `apt-get` at a time: a second fails on the dpkg lock. If the lock is "held by
  process … (apt-get)", that is your own earlier install — wait for it.

Pick ONE Python strategy and install + run with the SAME interpreter (Debian 12 is
PEP 668 / externally-managed, so a bare `pip install` errors):

- **venv** (default for `requirements.txt`): `python3 -m venv /app/.venv` then
  `/app/.venv/bin/pip install -r requirements.txt`. Afterwards ALWAYS run via
  `/app/.venv/bin/python` (never bare `python3`), and `config.json.run` must use it.
- **apt** (system Python): `DEBIAN_FRONTEND=noninteractive apt-get install -y python3-<name> …`,
  then run with the system `python3`.

Node: `npm install` (or the lockfile's manager). Verify the import/binary with the
exact interpreter before declaring success: `/app/.venv/bin/python -c "import django"`.

## 4. Framework bring-up

**Django** (`manage.py` present):
- Make it bootable without external services: if it requires Postgres but no
  `POSTGRES_*`/`DATABASE_URL` env is set, fall back to SQLite, and add the VM's
  host to `ALLOWED_HOSTS` (`localhost`, `127.0.0.1`, `0.0.0.0`) and a matching
  `CSRF_TRUSTED_ORIGINS`. Prefer env-driven settings over hardcoding; keep changes
  minimal and reversible.
- `python manage.py migrate` then `python manage.py collectstatic --no-input`
  (both via your chosen interpreter).
- Run: dev → `python manage.py runserver 0.0.0.0:8000`; or
  `gunicorn <project>.wsgi:application --bind 0.0.0.0:8000`.

**Flask/FastAPI**: `flask run --host 0.0.0.0 --port 8000` /
`uvicorn app:app --host 0.0.0.0 --port 8000`.

**Node**: run `scripts.start`/`dev`; for Vite/CRA bind host `0.0.0.0` and use the
dev port (5173/3000). For a build step run `npm run build` first.

**docker-compose**: `docker compose up -d` (after `command -v docker`).

Always bind to `0.0.0.0` (not `127.0.0.1`) on a high, unprivileged port so the
preview proxy can reach it.

## 5. Write /app/config.json

    {"run": "<non-blocking start command>", "port": <the port the app listens on>}

CRITICAL: `run` is pasted into the user's interactive terminal — it must be
**non-blocking** or it freezes that terminal. Background the server inside the
command: `setsid -f`, `nohup … &`, `… &`, or `docker compose up -d`. cd into the
project root and use the right interpreter. Examples:

    {"run": "cd repo/src && nohup /app/.venv/bin/gunicorn expenses_tracker.wsgi:application --bind 0.0.0.0:8000 >/app/run.log 2>&1 &", "port": 8000}
    {"run": "cd repo && nohup npm run dev -- --host 0.0.0.0 >/app/run.log 2>&1 &", "port": 5173}

`port` must equal the port the app actually listens on. No `port` → no preview.

## 6. Verify it is actually up (do not skip)

Your `bash`/`process` tools are SEPARATE from the IDE Run button — start and check
the server yourself:

1. Start it: `bash(command="<the run command>", background=true)` (or it
   auto-backgrounds), get the `job_id`.
2. `process(job_id, action="status")` — confirm it didn't crash; read the log.
3. Confirm the port: `ss -ltn | grep :<port>` then
   `curl -sS -m 5 http://localhost:<port>/` — you want a real HTTP response.
4. If it failed, read the log/error, fix, and retry until `curl` succeeds.

Only then summarize: what you cloned, how it installs, how it runs, the port, and
that `curl` confirmed it. Update `/app/readme.txt` with the run command if helpful.
