# PequeRoku Python SDK

A thin, hand-polished client over the public PequeRoku API (`/api/v1`). Give your
scripts and agents a real sandbox: create VMs, run code, move files, inspect
ports — all behind an API key.

## Install

```bash
cd sdk
poetry install   # or: pip install httpx && pip install -e .
```

## Quickstart

```python
from pequeroku import PequeRoku

pq = PequeRoku(api_key="pk_xxx", base_url="https://your-host")

# One-shot: run code in a throwaway VM (created + destroyed for you).
result = pq.run("python main.py", files=[{"path": "main.py", "content": "print('hi')"}])
print(result.stdout, result.exit_code)

# Persistent container you can come back to.
c = pq.create_container(type="small", name="blog")
pq.write_files(c["id"], [{"path": "app.py", "content": "..."}])
pq.exec(c["id"], "pip install flask")
pq.exec(c["id"], "python app.py", background=True)   # returns {process_id, pid}
print(pq.ports(c["id"]))                              # listening ports + preview path
pq.destroy_container(c["id"])
```

## Async runs

```python
r = pq.run("long_job.sh", wait=False)   # returns immediately, status="pending"
final = pq.wait_run(r.id)               # polls /runs/{id} until done
print(final.stdout)
```

## Getting a key

Ask an operator to mint one (the token is shown once):

```bash
python manage.py create_api_key <username> --scopes read,exec,admin
```

Scopes are hierarchical: `read` < `exec` < `admin`. A `read` key can't run code;
an `exec` key can't create/destroy. Errors come back as `PequeRokuError` with a
stable `.code` (e.g. `quota_exceeded`, `machine_not_running`, `forbidden_scope`).

## API reference

The contract is self-describing: the OpenAPI spec lives at
`/api/v1/schema/` with Swagger UI at `/api/v1/schema/swagger-ui/`.
