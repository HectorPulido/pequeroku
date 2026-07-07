"""The ephemeral-run lifecycle, shared by the sync path and the async worker.

``execute_run`` is the single code path: claim/boot a VM (with a TTL so it can
never orphan), wait until it's ready, push files, run the command, capture the
result, and destroy the VM. Sync runs call it inline; the worker calls it for
each pending row.
"""

from __future__ import annotations

import time
from datetime import timedelta

from django.utils import timezone

from vm_manager import orchestration

from . import vmops
from .errors import APIError
from .models import Run

# Extra time-to-live granted to a run's VM beyond its command timeout, so the
# reaper kills it even if the worker dies mid-run. The run can never orphan a VM.
_TTL_MARGIN_SECONDS = 60

# How long to wait for an on-demand VM to reach 'running' before giving up.
_READY_POLL_SECONDS = 2


def _wait_running(container, deadline: float) -> bool:
    """Poll the node until the VM is 'running' (SSH-ready) or the deadline passes."""
    svc = orchestration.get_service(container)
    while True:
        try:
            state = svc.get_vm(str(container.container_id)).get("state")
            if state == "running":
                return True
            if state == "error":
                return False
        except Exception:
            pass
        if time.monotonic() >= deadline:
            return False
        time.sleep(_READY_POLL_SECONDS)


def execute_run(run: Run) -> Run:
    """Run the full lifecycle and persist the outcome onto ``run``."""
    start = time.monotonic()
    if run.started_at is None:
        run.started_at = timezone.now()
    run.status = Run.Status.RUNNING
    run.save(update_fields=["status", "started_at"])

    container = None
    try:
        ct = run.container_type
        if ct is None:
            raise APIError("invalid_request", "Run has no container type")

        expires_at = timezone.now() + timedelta(
            seconds=int(run.timeout_seconds) + _TTL_MARGIN_SECONDS
        )
        container, _warning, _from_pool = orchestration.claim_or_create_container(
            user=run.user,
            ct=ct,
            name=f"run-{run.pk}",
            expires_at=expires_at,
            first_start=False,
        )
        run.container = container
        run.save(update_fields=["container"])

        deadline = start + float(run.timeout_seconds)
        if not _wait_running(container, deadline):
            run.status = Run.Status.TIMEOUT
            run.error_code = "timeout"
            run.stderr = "VM did not become ready before the timeout"
            return run

        if run.files:
            vmops.upload_files(container, run.files, dest_path="/app")

        result = vmops.exec_sh(container, run.command, timeout=int(run.timeout_seconds))
        run.stdout = result["stdout"]
        run.stderr = result["stderr"]
        run.exit_code = result["exit_code"]
        run.truncated = result["truncated"]
        run.status = Run.Status.SUCCEEDED
    except APIError as e:
        run.status = Run.Status.FAILED
        run.error_code = e.code
        if not run.stderr:
            run.stderr = e.message
    except Exception as e:  # pragma: no cover - defensive
        run.status = Run.Status.FAILED
        run.error_code = "internal_error"
        if not run.stderr:
            run.stderr = str(e)
    finally:
        if container is not None:
            # Always tear down the ephemeral VM; never leave it for the user.
            vmops.destroy(container)
            run.container = None
        run.duration_ms = int((time.monotonic() - start) * 1000)
        run.finished_at = timezone.now()
        run.files = []  # don't keep uploaded payloads around after the run
        run.save()

    return run
