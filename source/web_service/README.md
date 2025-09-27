# Pequeroku Web Service (Backend)

Django-based backend for Pequeroku with Django REST Framework, Channels (WebSockets), and OpenAPI docs via drf-spectacular. It uses PostgreSQL for persistence and Redis for Channels message brokering. It also includes an AI assistant service exposed over WebSockets and a flexible `Config` model to manage runtime flags and AI provider settings.

- ASGI stack: Django 5.x + Channels
- REST: Django REST Framework
- Realtime: channels-redis (Redis)
- OpenAPI: drf-spectacular (schema + Swagger/Redoc UI)
- App server (container): Gunicorn + Uvicorn workers
- Dependencies: Poetry
- Tests: pytest + pytest-django + coverage

Project path: `source/web_service`


## Requirements

- Python 3.11+ (local). The Dockerfile uses Python 3.13-slim.
- Poetry (https://python-poetry.org/)
- PostgreSQL 13+ (app runtime)
- Redis 6+ (Channels)
- For tests only: SQLite is used automatically; Redis is not required.


## Project layout (apps)

- `pequeroku`: project (settings, urls, asgi, wsgi)
- `vm_manager`: containers, quotas, templates, user endpoints
- `internal_config`: configuration flags, audit and AI usage logs
- `ai_services`: AI WebSocket consumer, agents, tools


## Quick Start (local, Poetry)

1) Install dependencies

    $ poetry install

2) Create `.env` at `web_service/` (see “Environment variables” below)

3) Run migrations

    $ poetry run python manage.py migrate

4) Create a superuser (optional but recommended)

    $ poetry run python manage.py createsuperuser

5) Start dev server

    $ poetry run python manage.py runserver

If you test WebSockets intensively, you can also run the ASGI server explicitly:

    $ poetry run daphne -b 0.0.0.0 -p 8000 pequeroku.asgi:application


## Environment variables

From `pequeroku/settings.py` and scripts:

- `SECRET_KEY` (default: "thisisnotasecretkey")
- `DEBUG` (default: true. Set to "false" in production)
- `ALLOWED_HOSTS`: comma-separated (e.g. `localhost,127.0.0.1,api.example.com`)
- `DB_NAME`, `DB_USER`, `DB_PASSWORD`, `DB_HOST`, `DB_PORT`: PostgreSQL connection
- `REDIS_URL` (default: `redis://redis:6379/1`)
- `REDIS_PREFIX` (default: `web_service:`)
- `WORKERS`: optional Gunicorn workers (default: 8, used in container)
- `DJANGO_MODULE`: optional ASGI module (default: `pequeroku`)
- `DJANGO_SUPERUSER_USERNAME`, `DJANGO_SUPERUSER_PASSWORD`, `DJANGO_SUPERUSER_EMAIL`: optional auto-creation in container

Example `.env` (development):

    SECRET_KEY=change-me
    DEBUG=true
    ALLOWED_HOSTS=localhost,127.0.0.1
    DB_NAME=pequeroku
    DB_USER=pequeroku
    DB_PASSWORD=pequeroku
    DB_HOST=127.0.0.1
    DB_PORT=5432
    REDIS_URL=redis://127.0.0.1:6379/1
    REDIS_PREFIX=web_service:


## API endpoints

- Admin: `/admin/`
- API base: `/api/`
- OpenAPI schema: `/api/schema/`
- Swagger UI: `/api/schema/swagger-ui/`
- Redoc: `/api/schema/redoc/`

With `DEBUG=true`, static and media are served by Django. In production, serve them via a proper web server/object storage.


## Running tests

Pytest is configured via `pyproject.toml` and uses `pequeroku/settings_test.py` (SQLite + in-memory channel layer). Run the full suite with coverage:

    $ poetry run pytest .

Examples:
- Run subset: `poetry run pytest -k "expr"`
- Stop on first fail: `poetry run pytest -x`
- More verbosity: `poetry run pytest -vv`


## AI Server (WebSocket)

The AI assistant is implemented in `ai_services.ai_consumers.AIConsumer` and exposed via Channels routing at:

- WebSocket route: `/ws/ai/<container_pk>/` (see `pequeroku/routing.py`)

High-level flow:

1) Client connects as an authenticated user to `/ws/ai/<pk>/`, where `<pk>` is the integer primary key of a `vm_manager.Container` the user can access.
2) The server verifies ownership/visibility and checks the daily AI quota from `vm_manager.ResourceQuota.ai_use_per_day`.
3) The assistant is initialized from persisted memory (`internal_config.AIMemory`), or bootstrapped by the agent (`ai_services.agents`).
4) Messages are streamed back using small JSON events.

Server-to-client events (examples):
- `{"event": "connected", "ai_uses_left_today": <int>}`
- `{"event": "start_text"}`
- `{"event": "text", "content": "<chunk>"}` (multiple chunks)
- `{"event": "finish_text"}`
- `{"event": "memory_data", "memory": [...]}`

Client sends:
- `{"text": "your prompt here"}` (max ~3000 chars per message)
- Special command: `{"text": "/clear"}` to reset conversation memory for this user+container.

Quotas and usage:
- Daily limits come from `ResourceQuota.ai_use_per_day`. The consumer logs each interaction to `internal_config.AIUsageLog`. Remaining quota is announced via the `connected` event.

Memory:
- Conversation memory is stored per `user` + `container` in `internal_config.AIMemory`. Sending `/clear` resets and reboots the agent’s system context.

Provider configuration (OpenAI-compatible):
- The AI client is created in `ai_services.utils.get_openai_client` using the `Config` model values:
  - `openai_api_key`
  - `openai_api_url` (e.g. `https://api.openai.com/v1` or a compatible provider like Groq)
  - `openai_model` (e.g. `gpt-4o`, or a provider-specific name)

Agents:
- Agent logic/tools live under `ai_services/agents/*` (e.g., `DevAgent`). You can customize prompts, tools, or the model at that layer.


## Config model (feature flags and AI settings)

`internal_config.models.Config` stores runtime-configurable flags and values. This enables changing behavior without redeploying.

Defaults and seeding:
- On `post_migrate` of the `internal_config` app, a set of defaults is inserted if missing (see `internal_config.signals.create_default_configs`):
  - `default_ai_use_per_day` (e.g. `"5"`)
  - `max_containers` (e.g. `"2"`)
  - `default_disk_gib` (e.g. `"10"`)
  - `default_mem_mib` (e.g. `"2048"`)
  - `default_vcpus` (e.g. `"2"`)
  - `openai_model` (provider-specific default)
  - `openai_api_url` (provider-specific default)
  - `openai_api_key` (placeholder; you must override it)

Where it’s used:
- User default quotas are created from Config values in `vm_manager.signals.create_user_quota`.
- AI service reads `openai_api_key`, `openai_api_url`, and `openai_model` to initialize the client.
- You can introduce new flags throughout the codebase and read them centrally.

Updating values (Admin):
- Go to `/admin/internal_config/config/` and edit the entries. For production, set your real AI provider values:
  - `openai_api_key`: your key
  - `openai_api_url`: e.g. `https://api.openai.com/v1` or your provider’s base URL
  - `openai_model`: desired model id

Updating values (Django shell):

    $ poetry run python manage.py shell

    from internal_config.models import Config

    # Upsert:
    Config.objects.update_or_create(
        name="openai_api_key",
        defaults={"value": "sk-your-key", "description": "OpenAI API key"},
    )
    Config.objects.update_or_create(
        name="openai_api_url",
        defaults={"value": "https://api.openai.com/v1", "description": "OpenAI API URL"},
    )
    Config.objects.update_or_create(
        name="openai_model",
        defaults={"value": "gpt-4o", "description": "Default LLM model"},
    )

    # Read one or multiple:
    print(Config.get_config_value("openai_model", default="gpt-4o"))
    print(Config.get_config_values(["openai_api_key", "openai_api_url", "openai_model"]))


## Audit logging and AI usage logs

Models:
- `internal_config.AuditLog`: general-purpose audit trail for user and system actions.
- `internal_config.AIUsageLog`: per-interaction AI usage (query/response, user, container).
- `internal_config.AIMemory`: conversation memory (JSON) per user+container.

What is captured:
- `AuditLog` tracks actions such as user login/logout and container lifecycle/operations:
  - Examples include `container.create`, `container.power_on`, `container.send_command`, `template.apply`, and WebSocket events like `ws.connect`, `ws.cmd`, etc.
- Each `AuditLog` entry includes: `user` (nullable), `action`, `target_type`, `target_id`, `message`, `metadata` (JSON), `ip`, `user_agent`, `success`, `created_at`.
- AI interactions are logged in `AIUsageLog` including `query`, `response`, `user`, `container`, and `created_at`.

Helpers to register logs:
- HTTP/DRF requests: use `internal_config.audit.audit_log_http(request, action=..., target_type=..., target_id=..., message=..., metadata=..., success=True|False)`
- WebSockets: use `internal_config.audit.audit_log_ws(action=..., user=..., ip=..., user_agent=..., target_type=..., target_id=..., message=..., metadata=..., success=True|False)`

Accessing logs (programmatically):
- Per-user audit and AI logs from a `ResourceQuota`:
  - `vm_manager.ResourceQuota.get_user_logs()`
  - `vm_manager.ResourceQuota.get_user_ai_logs()`
- Per-container logs:
  - `vm_manager.Container.get_machine_logs()`
  - `vm_manager.Container.get_user_ai_logs()`

Admin views:
- Go to `/admin/internal_config/auditlog/` and `/admin/internal_config/aiusagelog/` to inspect entries.

Retention and indexing:
- `AuditLog` and `AIUsageLog` have useful indexes for common queries (by user, date, action). You can add a periodic job to prune old data depending on your compliance and retention policies.


## Static and media files

- `STATIC_URL`: `/static/`, `STATIC_ROOT`: `staticfiles/`
- `MEDIA_URL`: `/media/`, `MEDIA_ROOT`: `media/`
- In development with `DEBUG=true`, Django serves both. In production, use a reverse proxy or storage bucket.


## Docker

The Dockerfile installs Poetry and dependencies and runs Gunicorn with Uvicorn workers through `entrypoint.sh`:

- Loads `.env` if present
- Runs `migrate` and `collectstatic`
- Optionally creates a superuser if env vars are set
- Starts Gunicorn ASGI server

Build:

    $ docker build -t pequeroku-web-service .

Run (example):

    $ docker run --rm -p 8000:8000 \
      -e SECRET_KEY=change-me \
      -e DEBUG=false \
      -e ALLOWED_HOSTS=localhost \
      -e DB_NAME=pequeroku \
      -e DB_USER=pequeroku \
      -e DB_PASSWORD=pequeroku \
      -e DB_HOST=db \
      -e DB_PORT=5432 \
      -e REDIS_URL=redis://redis:6379/1 \
      -e DJANGO_SUPERUSER_USERNAME=admin \
      -e DJANGO_SUPERUSER_PASSWORD=adminpass \
      -e DJANGO_SUPERUSER_EMAIL=admin@example.com \
      --name pequeroku-web \
      pequeroku-web-service

Notes:
- Exposes port 8000 by default.
- Requires reachable PostgreSQL and Redis; in a Compose setup, set `DB_HOST` and `REDIS_URL` to the service names.

Example docker-compose snippet:

    services:
      web:
        image: pequeroku-web-service
        build: .
        ports:
          - "8000:8000"
        env_file:
          - .env
        depends_on:
          - db
          - redis

      db:
        image: postgres:16
        environment:
          POSTGRES_DB: pequeroku
          POSTGRES_USER: pequeroku
          POSTGRES_PASSWORD: pequeroku
        volumes:
          - pgdata:/var/lib/postgresql/data

      redis:
        image: redis:7

    volumes:
      pgdata:


## Common management commands

- Migrations: `poetry run python manage.py migrate`
- Superuser: `poetry run python manage.py createsuperuser`
- Collect static: `poetry run python manage.py collectstatic --no-input`
- Dev server: `poetry run python manage.py runserver`


## Notes

- Production: Set `DEBUG=false`, configure `ALLOWED_HOSTS`, and secure `SECRET_KEY`. Put your reverse proxy/TLS in front and serve static assets properly.
- Channels/Redis: Ensure `REDIS_URL` is reachable where WebSockets or background messaging is required.
- AI provider: Override `openai_api_key`, `openai_api_url`, and `openai_model` in the `Config` table (Admin or shell) before using the AI features.
- Tests: Do not require Postgres/Redis thanks to `settings_test.py`; run with `poetry run pytest .`.
