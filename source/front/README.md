# PequeRoku Frontend

This directory contains the static frontend for the PequeRoku platform. It provides:
- A dashboard to log in, see and manage containers.
- An in-browser micro-IDE to edit files and run commands inside a container.
- A live metrics view with charts.

All assets here are served as static files by Nginx, and the UI communicates with the backend via REST and WebSocket endpoints.

Because this is a subfolder in a larger repository, you run the whole application from the repo root with Docker Compose. The frontend is mounted and served by the Nginx service defined at the root.

## Quick start

From the repository root (not inside this `front/` folder):

    docker compose up -d

Then open the HTTP endpoint exposed by the stack (check the root README or your Compose configuration for the host/port). The frontend is served by Nginx.

Notes:
- Opening these HTML files directly in your browser (file://) will not work due to same-origin, cookies, and WebSocket requirements.
- The frontend expects the backend to be reachable at the same origin for `/api/*` and `/ws/*`.

## Project layout

Files are plain ES modules with no build step. External libraries are loaded via CDN when needed (Monaco, xterm.js, Chart.js, Iconoir).

- `index.html`
  - The main app shell:
    - Login form (`/api/user/login/`)
    - Containers dashboard (`/api/containers/`)
    - Actions: create, start, stop, delete
    - Opens the IDE and Metrics in iframes or new tabs
  - Entry script: `/js/app/main.js`

- `ide.html`
  - In-browser micro-IDE for a container:
    - File tree (WebSocket-based FS operations)
    - Monaco editor for code editing
    - xterm.js-based terminal with multi-session tabs
    - “Run” action via a configurable `config.json`
    - GitHub clone helper
  - Entry script: `/js/ide/main.js`

- `metrics.html`
  - Live metrics dashboard (Chart.js) for a container:
    - CPU %
    - Memory RSS (MiB)
    - Threads
  - Entry script: `/js/metrics/main.js`

- `css/`
  - `base.css` – global base styles
  - `themes.css` – light/dark theme variables and toggling
  - `styles.css` – dashboard styles
  - `ideStyles.css` – IDE layout and components
  - `metrics.css` – metrics page layout
  - `ai.css` – AI chat UI in the IDE

- `js/`
  - `app/` – main app (dashboard)
    - `main.js` – bootstraps theme, login, containers
    - `login.js` – login flow, session check
    - `containers.js` – list and manage containers, open IDE/Metrics modals
  - `ide/` – IDE features
    - `main.js` – orchestrates editor, console, WS, templates, uploads
    - `editor.js` – Monaco integration and layout
    - `console.js` – xterm.js multi-session console
    - `files.js` – file-tree UI and actions
    - `fs-ws.js` – WS RPC for FS (read/write/move/delete/broadcast)
    - `websockets.js` – WS for container console sessions
    - `templates.js` – list/apply project templates
    - `uploads.js` – file upload modal
    - `runConfig.js` – reads `/app/config.json` and exposes run command
    - `hiddableDraggable.js` – responsive/resizable panels
  - `metrics/`
    - `main.js` – polling loop, charts, KPIs
  - `core/` – shared utilities
    - `api.js` – fetch wrapper, CSRF handling, error alerts
    - `csrf.js` – reads `csrftoken` cookie
    - `ws.js` – robust WebSocket client (reconnect, queue, ping)
    - `constants.js` – tunables (timeouts, sizes, paths)
    - `dom.js`, `modals.js`, `alerts.js`, `loader.js`, `themes.js`, `utils.js`, `store.js` – UI helpers, global state
  - `shared/`
    - `langMap.js` – shared lookups

- Tooling
  - `package.json` – dev scripts (lint/format with Biome)
  - `biome.json`, `.biomeignore`
  - No bundler is required; modules are loaded directly by the browser.

## How the frontend talks to the backend

All calls assume same-origin and use cookies for auth/CSRF. The fetch wrapper sets `credentials: "same-origin"` and a `X-CSRFToken` header from the `csrftoken` cookie.

- Auth and user data
  - `POST /api/user/login/` – login
  - `GET /api/user/me/` – user info, quota

- Containers (dashboard)
  - `GET /api/containers/` – list containers
  - `POST /api/containers/` – create new container
  - `POST /api/containers/{id}/power_on/` – start
  - `POST /api/containers/{id}/power_off/` – stop
  - `DELETE /api/containers/{id}/` – delete

- IDE (WebSockets)
  - `WS /ws/containers/{id}/` – terminal multiplexing (multi-session)
    - Text frames and binary frames are supported
  - `WS /ws/fs/{containerPk}/` – file system RPC and broadcasts
    - Actions like `read_file`, `write_file`, `path_moved`, `path_deleted`, etc.
    - Revision numbers are used for basic conflict detection

- Templates
  - `GET /api/templates/`
  - `POST /api/templates/{templateId}/apply/` with
    - `container_id`, `dest_path`, `clean`

- Metrics
  - `GET /api/containers/{id}/statistics/` – returns CPU %, RSS, threads, ts

- Downloads
  - `GET /api/containers/{id}/download_folder/` – zip export

If a request returns `401` or `403`, the frontend will notify and redirect to the login page.

## Routing and Nginx

This frontend is designed to be served at the site root by Nginx with friendly routes:

- `/` → `index.html` (dashboard)
- `/ide/` → `ide.html` (IDE)
- `/metrics/` → `metrics.html` (metrics)

Static assets are under `/css/*` and `/js/*`.

Example Nginx snippets (adjust to your setup):

    # Static files
    location /css/ { root /path/to/front; try_files $uri =404; }
    location /js/  { root /path/to/front; try_files $uri =404; }
    location = /index.html { root /path/to/front; }
    location = /ide.html    { root /path/to/front; }
    location = /metrics.html { root /path/to/front; }

    # Pretty routes for pages
    location = / { try_files /index.html =404; }
    location = /ide/ { try_files /ide.html =404; }
    location = /metrics/ { try_files /metrics.html =404; }

    # REST API (proxy to backend)
    location /api/ {
      proxy_pass http://backend;
      proxy_set_header Host $host;
      proxy_set_header X-Real-IP $remote_addr;
      proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
      proxy_set_header X-Forwarded-Proto $scheme;
    }

    # WebSockets (terminal and FS)
    map $http_upgrade $connection_upgrade {
      default upgrade;
      ''      close;
    }

    location /ws/ {
      proxy_pass http://backend;
      proxy_http_version 1.1;
      proxy_set_header Upgrade $http_upgrade;
      proxy_set_header Connection $connection_upgrade;
      proxy_set_header Host $host;
      proxy_read_timeout 3600s;
    }

In the Docker Compose setup at the repo root, Nginx already serves this directory and proxies `/api/` and `/ws/` to the backend. The above is for reference if you customize your deployment.

## Development

- No build step: edit files and refresh the browser.
- Lint/format with Biome:

      npm ci
      npm run lint
      npm run format
      npm run check
      npm run fix

- To run the full stack locally: use `docker compose up` from the repo root so Nginx and backend are available. Running a standalone static server for this folder will not be sufficient (auth cookies, CSRF, and WebSockets must be same-origin and proxied).

## Troubleshooting

- 401/403 or redirect to `/`: your session expired or CSRF cookie is missing. Log in again.
- Blank IDE or metrics via `/ide/` or `/metrics/`: ensure Nginx routes map those paths to `ide.html` and `metrics.html`.
- Terminal or file tree not working: check that WebSocket upgrade headers are configured and proxying to the backend works for `/ws/containers/*` and `/ws/fs/*`.
- Metrics not updating: the endpoint `/api/containers/{id}/statistics/` must be reachable and the user authorized.

## Adding a new static page

1. Add a new `*.html` file under this folder.
2. Include any scripts under `js/` and styles under `css/`.
3. Add an Nginx route (e.g., `location = /newpage/ { try_files /newpage.html =404; }`).
