# vm-service

A lightweight FastAPI microservice for managing ephemeral VMs with QEMU/KVM. It provisions VMs, exposes lifecycle APIs, provides a simple TTY WebSocket bridge, basic file operations via SSH/SFTP, VM search, and metrics. A Redis-backed catalog maintains VM state across the node.

Important: This service is part of a multi-service environment orchestrated with a docker-compose at the repository root. See “Docker & Compose” below for details.

Table of Contents
- Overview
- Architecture and Components
- Project Layout
- Runtime Requirements
- Configuration (Environment Variables)
- API Overview
  - Auth
  - Health
  - VM Lifecycle
  - File & FS Operations
  - TTY WebSocket
  - Search
  - Execute shell
  - Downloads
  - Metrics
- How it Works
- Docker & Compose
- Local Development
  - Run the service locally
  - Run tests & coverage
- Troubleshooting & Tips

Overview
- Orchestration: FastAPI app exposes REST and WebSocket endpoints
- VM backend: QEMU, with per-VM workdir and cloud-init seed ISO
- SSH: Paramiko for remote exec and SFTP
- Catalog: Redis to persist VM records and reconcile their health
- Metrics: psutil, via per-VM PID tracked by QEMU
- Security: Bearer token

Architecture and Components
- API (FastAPI)
  - vm_service/main.py: App factory, /health, WebSocket TTY route, router wiring
  - vm_service/vms.py: REST endpoints for VM lifecycle and operations
  - vm_service/metrics.py: Per-VM resource usage via psutil
- Domain models (Pydantic / dataclasses)
  - vm_service/models.py: VMRecord, VMOut, VMCreate, VMAction, etc.
- Implementations
  - vm_service/implementations/store.py: Redis-backed catalog (put/get/all/reconcile)
  - vm_service/implementations/runner.py: Starts/stops VMs (threads) using qemu_manager
  - vm_service/implementations/bridge.py: TTY WebSocket bridge using SSH channel
  - vm_service/implementations/ssh_cache.py: Connection/cache utilities for SSH/SFTP/Channels
  - vm_service/implementations/read_from_vm.py: List dirs, read file, download file/folder
  - vm_service/implementations/send_file.py: Upload files/templates to the VM
- QEMU manager (lower-level)
  - vm_service/qemu_manager/vm.py: Start VM (overlay, seed ISO, choose args)
  - vm_service/qemu_manager/qemu_args.py: Compose QEMU args for x86/arm64 (KVM/HVF/TCG)
  - vm_service/qemu_manager/seed.py: Create cloud-init seed ISO (user-data/meta-data)
  - vm_service/qemu_manager/ssh_ready.py: Wait for SSH to come up on the forwarded port
  - vm_service/qemu_manager/ports.py: Pick free localhost TCP ports
  - vm_service/qemu_manager/crypto.py: Helpers for key loading/spec hashing
- Security
  - vm_service/security.py: Bearer token validation (HTTPBearer)
- Settings
  - vm_service/settings.py: Configuration via env vars; sensible defaults for development

Project Layout
- vm_service/
  - main.py: FastAPI app + WebSocket
  - vms.py: Core REST endpoints
  - metrics.py: Metrics endpoint
  - models.py: Data models (Pydantic + dataclasses)
  - security.py: Bearer token dependency
  - settings.py: Environment-based config (paths, users, redis, QEMU)
  - implementations/
    - bridge.py, runner.py, store.py, ssh_cache.py, send_file.py, read_from_vm.py
  - qemu_manager/
    - vm.py, qemu_args.py, seed.py, ssh_ready.py, ports.py, crypto.py
  - tests/: Comprehensive pytest suite with SSH/QEMU mocked
  - Dockerfile, entrypoint.sh, pyproject.toml, poetry.lock

Runtime Requirements
- Python 3.11+
- Redis (reachable via REDIS_URL)
- QEMU (qemu-system-x86_64 or qemu-system-aarch64), plus UEFI firmware for arm64 if applicable
- An existing base qcow2 image (see VM_BASE_IMAGE)
- SSH private key (VM_SSH_PRIVKEY) whose public key will be injected into the VM via cloud-init
- On Linux with KVM: /dev/kvm (optional; TCG otherwise)
- On macOS with Apple Silicon: HVF acceleration supported; otherwise TCG fallback

Configuration (Environment Variables)
All configuration is read in vm_service/settings.py. Key variables:

- AUTH_TOKEN: Bearer token required for all protected endpoints (everything except /health).
- REDIS_URL: e.g. redis://redis:6379/1
- REDIS_PREFIX: Namespace/prefix for Redis keys (default: vmservice:)
- NODE_NAME: Logical name of the node running the VMs (displayed in responses)
- VM_BASE_DIR: Base dir to store per-VM workdirs (console log, pidfile, qcow2 overlay, seed.iso)
- VM_SSH_USER: VM user to set in cloud-init & SSH (default: root)
- VM_SSH_PRIVKEY: Private key used to connect (public key injected in seed ISO) (default ~/.ssh/id_vm_pequeroku)
- VM_QEMU_BIN: Path to qemu-system-x86_64 (x86) or used by arm64 helper
- VM_BASE_IMAGE: Path to the base qcow2 image used as backing
- VM_TIMEOUT_BOOT_S: SSH readiness timeout in seconds
- VM_RUN_AS_UID / VM_RUN_AS_GID: Optional run-as user/group for the QEMU process and files
- Optional for ARM64 firmware resolution (qemu_args): VM_UEFI_ARM64 (if the heuristic fails)

API Overview
Auth
- All /vms/* and /metrics/* routes require Authorization: Bearer <AUTH_TOKEN>.
- /health is public.

Health
- GET /health
  - Returns: {"ok": "True"}

VM Lifecycle
- POST /vms/
  - Body (JSON): { "vcpus": int, "mem_mib": int, "disk_gib": int, "base_image": str|null, "timeout_boot_s": int|null }
  - Creates a VM record, starts provisioning asynchronously; returns VMOut.
- GET /vms/
  - List all VMs known in Redis.
- GET /vms/{vm_id}
  - Fetch a specific VM.
- GET /vms/list/{vm_ids}
  - Comma-separated list of IDs.
- POST /vms/{vm_id}/actions
  - Body: {"action": "start" | "stop" | "reboot", "cleanup_disks": bool}
  - Start: If already running, returns VMOut; otherwise triggers start and moves to provisioning.
  - Stop: Sends shutdown/kill signals; optional disk cleanup (overlay/seed/logs/pid).
  - Reboot: Stop then start (with a short delay).
- DELETE /vms/{vm_id}
  - Stops VM and cleans up disks; returns VMOut.

File & FS Operations
- POST /vms/{vm_id}/upload-files
  - Body: { "dest_path": "/app", "clean": false, "files": [{ "path": "rel/file.txt", "text": "...", "content_b64": "...", "mode": 420 }] }
  - Writes files under dest_path (POSIX join with safety); can clean the dest dir before writing.
- POST /vms/{vm_id}/list-dirs
  - Body: { "paths": ["/app"], "depth": 1 }
  - Returns (path, name, path_type) for files/dirs using remote find.
- POST /vms/{vm_id}/read-file
  - Body: { "path": "/abs/path" }
  - Returns file content via SFTP (UTF-8, ignore errors).
- POST /vms/{vm_id}/create-dir
  - Body: { "path": "/abs/path" }
  - mkdir -p remotely.
- GET /vms/{vm_id}/console/tail?lines=120
  - Returns the last N lines of the VM’s console.log (if present).

TTY WebSocket
- GET /vms/{vm_id}/tty (WebSocket)
  - Accepts a text WS; bridges to SSH invoke_shell; backend echoes output.
  - Special inputs: "ctrlc" and "ctrld" send respective control chars.

Search
- POST /vms/{vm_id}/search
  - Body: {
      "pattern": "text",
      "root": "/app",
      "case_insensitive": false,
      "include_globs": ["*.py"],
      "exclude_dirs": [".git"],
      "max_results_total": 500,
      "timeout_seconds": 10
    }
  - Runs grep -RInI remotely with filters; aggregates matches by file.

Execute shell
- POST /vms/{vm_id}/execute-sh
  - Body: { "command": "ls -la /" }
  - Runs a command via SSH; returns combined "Result:" and "Error:" outputs.

Downloads
- GET /vms/{vm_id}/download-file?path=/abs/path
  - Returns file bytes with proper content-disposition and media-type guess.
- GET /vms/{vm_id}/download-folder?root=/app&prefer_fmt=zip|tar.gz
  - Quickly packs a directory with zip (if available) or tar.gz and streams it back.

Metrics
- GET /metrics/{vm_id}
  - Uses the VM’s pidfile and psutil to return:
    {
      "ts": float,
      "cpu_percent": float|null,
      "rss_bytes": int|null,
      "rss_human": "10.0 MB"|"-",
      "rss_mib": float|null,
      "num_threads": int|null,
      "io": { ... } | {}
    }

Example requests
- Create VM:
  curl -X POST http://127.0.0.1:8080/vms/ \
    -H "Authorization: Bearer $AUTH_TOKEN" \
    -H "Content-Type: application/json" \
    -d '{"vcpus":2,"mem_mib":1024,"disk_gib":10}'
- Stop VM:
  curl -X POST http://127.0.0.1:8080/vms/$ID/actions \
    -H "Authorization: Bearer $AUTH_TOKEN" \
    -H "Content-Type: application/json" \
    -d '{"action":"stop","cleanup_disks":true}'
- WebSocket TTY (using websocat):
  websocat -H="Authorization: Bearer $AUTH_TOKEN" ws://127.0.0.1:8080/vms/$ID/tty

How it Works
- VM provisioning
  - vm_service/implementations/runner.py creates a per-VM workdir under VM_BASE_DIR/vms/<id>, sets initial state → provisioning, and spawns a thread that:
    1) Creates qcow2 overlay referencing VM_BASE_IMAGE (seed.py/make_overlay)
    2) Creates cloud-init seed ISO with user-data/meta-data (seed.py/make_seed_iso)
    3) Picks a high TCP port, builds QEMU args (qemu_args.py), runs QEMU (qemu_manager/vm.py)
    4) Waits for SSH ready (qemu_manager/ssh_ready.py) with timeout
    5) Sets running state (or error on failure); updates Redis store
- SSH & caching
  - implementations/ssh_cache.py maintains a per-VM cache for SSHClient, SFTPClient, and interactive Channel. Helpers open_ssh/open_sftp transparently generate or reuse connections.
- Redis store & reconciliation
  - implementations/store.py serializes VMRecord to JSON and persists it under a namespaced key. “all()” reads all VMs and reconciles “running” VMs that have a dead SSH port → stopped (with error_reason). This makes the catalog self-healing after node restarts.
- TTY bridge
  - implementations/bridge.py spawns a small thread that pumps SSH channel data into the WebSocket and forwards user keystrokes back to the channel.

Docker & Compose
- This service is designed to be run alongside other components via a docker-compose file at the repository root.
- Typical characteristics:
  - A Redis service is defined there and networked to this service
  - Volume(s) for VM_BASE_DIR
  - Environment variables for credentials and paths
  - QEMU and KVM support depend on the host and container runtime (KVM passthrough is host/OS specific)
- To run the full stack:
  - From the repository root (where docker-compose.yml lives): docker compose up -d
  - Identify the vm-service container name in the compose file (often vm_service or similar) and check logs: docker compose logs -f vm_service
- To build only this image:
  - From vm_service/: docker build -t vm-service:local .

Local Development
Prerequisites
- Python 3.11
- Poetry (recommended)
- Redis accessible (e.g., docker run -p 6379:6379 redis:7 or a local service)
- QEMU installed if you plan to actually run VMs (not needed to run tests)

Install dependencies
- From vm_service/ (the directory containing pyproject.toml):
  poetry install
  poetry shell   # optional

Run the service locally (dev)
- Ensure Redis is reachable via REDIS_URL and AUTH_TOKEN is set.
- Start the API:
  poetry run python vm_service/main.py
  # or
  poetry run uvicorn vm_service.main:app --host 0.0.0.0 --port 8080 --reload
- Create the base image and firmware prerequisites on your host if you want real VMs to boot.
  - Set VM_BASE_IMAGE to a valid qcow2 (e.g., Ubuntu cloud image)
  - On macOS/arm64, ensure UEFI firmware is installed (see qemu_args for VM_UEFI_ARM64)

Run tests & coverage
- All tests are designed to run without Redis, SSH, or QEMU by mocking those layers.
- Commands:
  poetry run pytest .
  # Coverage is enabled by default (term-missing)
- The test suite includes:
  - tests/test_api.py: end-to-end API (FastAPI TestClient) with mocks
  - tests/test_runner.py, tests/test_qemu_vm.py, tests/test_qemu_args.py: VM lifecycle and QEMU arg composition
  - tests/test_read_from_vm.py, tests/test_send_file.py: FS ops via SSH/SFTP
  - tests/test_ssh_cache.py: caching logic
  - tests/test_store.py: Redis catalog serialization and reconciliation logic

Troubleshooting & Tips
- Redis connectivity: Verify REDIS_URL and that the service can resolve the hostname. Use docker compose networking if running via Docker.
- Base image not found: Ensure VM_BASE_IMAGE points to a filesystem path readable by the service container/host.
- UEFI on arm64: qemu_args.py tries common locations and QEMU’s datadir; set VM_UEFI_ARM64 explicitly if needed.
- KVM passthrough in containers: Requires host support and appropriate privileges/capabilities. Otherwise the service falls back to TCG (slow, but OK for basic testing).
- SSH key: VM_SSH_PRIVKEY must exist and its .pub will be injected in the seed ISO; ensure file permissions are sane.
