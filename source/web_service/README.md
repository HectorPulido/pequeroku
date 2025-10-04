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


## VM Manager (containers, types, quotas, nodes, templates, teams)

This section documents key models and behaviors in `vm_manager.models` that govern container resources, scheduling, quotas, and team-based sharing.

### ContainerType
- Fields:
  - container_type_name: display name.
  - memory_mb: memory in MB.
  - vcpus: number of virtual CPUs.
  - disk_gib: disk size in GiB.
  - credits_cost: how many user credits are required to create/run a container of this type.
  - private: if true, the type will not be auto-assigned to new user quotas.
- Usage:
  - Drives default resource sizing for containers (see “Container” below).
  - Controls credit consumption via `credits_cost`.
- Defaults seeding:
  - On first migration of `vm_manager`, if no types exist, defaults are seeded:
    - small: 1 vCPU, 1024 MB, 5 GiB, credits_cost=1
    - medium: 2 vCPU, 2048 MB, 10 GiB, credits_cost=2
    - large: 4 vCPU, 4096 MB, 25 GiB, credits_cost=4
- Admin management:
  - Manage types at /admin/vm_manager/containertype/
  - Use the “private” flag for internal/limited types that should not be auto-granted to new users.
- Creating/updating via shell (examples):
  ```/dev/null/README.md#L1-20
  # Django shell
  from vm_manager.models import ContainerType

  # Create or update a GPU type (kept private)
  ct, _ = ContainerType.objects.update_or_create(
      container_type_name="gpu-small",
      defaults={
          "memory_mb": 8192,
          "vcpus": 4,
          "disk_gib": 40,
          "credits_cost": 6,
          "private": True,
      },
  )

  # Adjust pricing of an existing type
  ContainerType.objects.filter(container_type_name="medium").update(credits_cost=3)
  ```
- Notes & best practices:
  - When a `Container` has a `container_type` selected, its `memory_mb`, `vcpus`, and `disk_gib` are copied from the type on save, keeping instances aligned with catalog settings.
  - Keep the catalog small and opinionated (e.g., small/medium/large) to simplify credit policy and scheduling.
  - Use `private` types for experimental or premium tiers, granting them per-user or per-team via `allowed_types`.
  - Keep `credits_cost` roughly proportional to resource demand across types to preserve fairness.
  - Changing a type updates the resources on the next container save; to freeze resources on a specific container, avoid saving after manual edits or temporarily disassociate its `container_type`.
  - If you need per-container overrides, consider modeling explicit override fields/flags and documenting how they interact with `container_type`.

### ResourceQuota
- One-to-one with User; fields include:
  - ai_use_per_day: daily AI requests allowed.
  - credits: total credits available to allocate to containers.
  - allowed_types: ManyToMany to ContainerType, restricting which types the user can create.
  - active: if set to false, all user containers are stopped.
- Defaults and creation:
  - A quota is auto-created for each new user using `default_ai_use_per_day` and `default_credits` from `internal_config.Config`.
  - On first creation, all non-private `ContainerType`s are auto-added to `allowed_types`.
- Behavior:
  - If `active` is set to false, all containers under the quota are updated to `desired_state="stopped"` and a reconcile command is triggered to enforce the state.
  - `calculate_used_credits(user)` sums `credits_cost` for running containers; legacy containers with no type count as 1 credit.
- Credit policy guidelines:
  - Think of credits as a cap on concurrent capacity. Running containers consume credits; stopped containers do not.
  - Recommended baseline:
    - default_credits: 3
    - small=1, medium=2–3, large=4+ credits depending on resource pressure
  - Use `private` types for premium tiers and grant them selectively via `allowed_types`.
  - To upsell, increase `credits` on the user’s quota; to limit, remove types from `allowed_types` or lower `credits`.
  - Changing a `ContainerType.credits_cost` affects future credit checks and current running containers’ accounting via `calculate_used_credits`.
  - Example plans:
    - Basic: credits=3; allowed types: small, medium
    - Pro: credits=6; allowed types: small, medium, large
    - Team: credits=10+; allowed types: include private types as needed
  - Retro-assign public types to existing quotas (bulk fix):
    ```/dev/null/README.md#L1-50
    # Django shell
    from vm_manager.models import ResourceQuota, ContainerType
    public_types = list(ContainerType.objects.filter(private=False).values_list("pk", flat=True))
    for q in ResourceQuota.objects.all():
        missing = set(public_types) - set(q.allowed_types.values_list("pk", flat=True))
        if missing:
            q.allowed_types.add(*missing)
    ```
  - Enforcement notes:
    - Credits are evaluated at creation via `can_create_container`; running containers continue to count against credits until stopped.
    - Stopping containers frees credits; deactivating a quota sets `desired_state="stopped"` for all containers and triggers reconciliation.
- Admin examples:
  - Adjust a user’s credits/AI uses and allowed types at /admin/vm_manager/resourcequota/<id>/.
  - Grant or revoke access to specific `ContainerType`s via the ManyToMany widget.
- Shell examples:
  ```/dev/null/README.md#L1-200
  # Django shell
  from django.contrib.auth.models import User
  from vm_manager.models import ResourceQuota, ContainerType

  user = User.objects.get(username="alice")
  quota = user.quota  # ResourceQuota

  # Grant a private type to a user
  gpu_small = ContainerType.objects.get(container_type_name="gpu-small")
  quota.allowed_types.add(gpu_small)

  # Check credits availability and eligibility
  print("Credits left:", quota.credits_left())
  print("Can create gpu-small?", quota.can_create_container(gpu_small))

  # Review used credits by running containers
  print("Used credits:", quota.calculate_used_credits(user))
  ```

### Container
- Links to:
  - User, Node, optional ContainerType, and ResourceQuota (auto-set from `user.quota` on save).
- Behavior:
  - Name defaults to a human-friendly random value if not provided.
  - Resource sync: when `container_type` is set, `memory_mb`, `vcpus`, and `disk_gib` are derived from the type on save. Manual edits to these fields while a type is linked are likely to be overwritten on subsequent saves.
  - desired_state vs status:
    - `desired_state` expresses intent (running/stopped).
    - `status` reflects the observed runtime state (created, provisioning, running, stopped, error).
    - A reconciler/management command brings actual state in line with `desired_state`; disabling a quota triggers a targeted reconcile for affected containers.
    - Manual changes outside the reconciler can drift; prefer updating `desired_state` or using admin/actions that trigger reconciliation.
  - Quota enforcement: creation checks `ResourceQuota.can_create_container`; running containers consume credits and stopping them frees credits.
- Visibility and sharing:
  - `visible_containers_for(user)` and `can_view_container(user, ...)` implement team-based visibility using `TeamMembership` relationships.

### Node
- Fields:
  - arch: host architecture (e.g., x86_64, aarch64).
  - kvm_available: whether /dev/kvm is available.
  - capacity_vcpus, capacity_mem_mb: total host capacity.
  - healthy, heartbeat_at: health probe status and last heartbeat time.
- Scheduling helpers:
  - `get_used_resources()` and `get_free_resources()` compute host resource usage and availability based on running containers.
  - `get_node_score()` = 2.0 × free_mem_mb + 1.0 × free_vcpus − 0.5 × running_containers (higher is better).

### File templates
- FileTemplate:
  - Named, sluggable templates for bootstrapping files into containers/projects.
  - `items_count` returns the number of items in the template.
- FileTemplateItem:
  - Defines file `path`, `content`, `mode`, and `order`; unique per `(template, path)` and ordered by `(order, path)`.

### Teams and sharing
- Team:
  - Has an owner; on save, ensures the owner has an ADMIN `TeamMembership`.
  - If a team is deactivated, all memberships are set inactive.
- TeamMembership:
  - Associates users with teams and roles (member/admin), with an `active` flag and helpful indexes.
  - Used by container visibility queries to allow team-based access.

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

AI usage pricing and admin display:
- Request cost is calculated in `internal_config.AIUsageLog.get_request_price()` using:
  - `token_input_price` x `prompt_tokens`
  - `token_output_price` x `completion_tokens`
- The admin list for AI usage logs shows only the total cost per request.
- In the admin change view, the cost breakdown is read-only: `cost_input`, `cost_output`, and `total_cost`.

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
  - `token_input_price` (per-token price for prompt/input)
  - `token_output_price` (per-token price for completion/output)
  - `default_ai_use_per_day` (e.g. `"5"`)
  - `default_credits` (initial user credits; e.g. `"3"`)
  - `openai_model` (provider-specific default, e.g. `"openai/gpt-oss-120b"`)
  - `openai_api_url` (provider-specific default, e.g. `"https://api.groq.com/openai/v1"`)
  - `openai_api_key` (placeholder; you must override it)

Where it’s used:
- User default quotas are created from Config values in `vm_manager.signals.create_user_quota`.
- AI service reads `openai_api_key`, `openai_api_url`, and `openai_model` to initialize the client.
- AI usage pricing reads `token_input_price` and `token_output_price` to compute per-request cost in `internal_config.AIUsageLog.get_request_price`.
- You can introduce new flags throughout the codebase and read them centrally.

Updating values (Admin):
- Go to `/admin/internal_config/config/` and edit the entries. For production, set your real AI provider values:
  - `openai_api_key`: your key
  - `openai_api_url`: e.g. `https://api.openai.com/v1` or your provider’s base URL
  - `openai_model`: desired model id
  - `token_input_price`: per-token input price (float string; e.g. "1.5e-7")
  - `token_output_price`: per-token output price (float string; e.g. "7.5e-7")

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
    Config.objects.update_or_create(
        name="token_input_price",
        defaults={"value": "1.5e-7", "description": "Per-token input price"},
    )
    Config.objects.update_or_create(
        name="token_output_price",
        defaults={"value": "7.5e-7", "description": "Per-token output price"},
    )

    # Read one or multiple:
    print(Config.get_config_value("openai_model", default="gpt-4o"))
    print(Config.get_config_values(["openai_api_key", "openai_api_url", "openai_model", "token_input_price", "token_output_price"]))


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
