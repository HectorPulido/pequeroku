"""Shared fixtures for platform_api tests.

The fake VM client is patched at ``vm_manager.orchestration.VMServiceClient``,
which is the single construction site used by BOTH container creation
(``claim_or_create_container``) and node ops (``orchestration.get_service`` via
``platform_api.vmops``). Patching one spot covers the whole surface.
"""

from __future__ import annotations

import pytest
from django.core.cache import cache
from rest_framework.test import APIClient

from platform_api.models import APIKey
from vm_manager.models import Container
from vm_manager.test_utils import (
    create_container,
    create_container_type,
    create_node,
    create_quota,
    create_user,
)


class FakeVMServiceClient:
    created = 0

    def __init__(
        self, node, timeout=30.0, session=None, extra_headers=None, blocking=False
    ):
        self.node = node

    def create_vm(self, payload):
        FakeVMServiceClient.created += 1
        return {"id": f"vm-new-{FakeVMServiceClient.created}"}

    def ensure_vm(self, vm_id, payload):
        return {"id": vm_id, "state": "running"}

    def get_vm(self, vm_id):
        return {"id": vm_id, "state": "running"}

    def delete_vm(self, vm_id):
        return {"status": "deleted"}

    def action_vm(self, vm_id, action):
        return {"status": "ok", "action": action.action}

    def execute_sh(self, vm_id, command, timeout=None):
        if command == "__notrunning__":
            return {"ok": False, "reason": "VM is not running"}
        return {"ok": True, "stdout": "hi\n", "stderr": "", "exit_code": 0}

    def start_process(self, vm_id, command):
        return {"ok": True, "job_id": "job-123", "pid": 42, "log_path": "/x"}

    def process_status(self, vm_id, job_id, lines=80, since_bytes=None, wait=0):
        return {
            "ok": True,
            "job_id": job_id,
            "status": "running",
            "pid": 42,
            "log": "line1\n",
            "log_size": 6,
        }

    def stop_process(self, vm_id, job_id):
        return {"ok": True, "job_id": job_id, "status": "stopped"}

    def upload_files_blob(self, vm_id, payload):
        return {"ok": True}

    def read_file(self, vm_id, path):
        return {"name": "f.txt", "content": "data", "length": 4, "found": True}

    def list_dirs(self, vm_id, paths):
        return [{"path": "/app/f.txt", "name": "f.txt", "path_type": "file"}]

    def listening_ports(self, vm_id):
        return [{"port": 8000, "address": "0.0.0.0", "process": "python3", "pid": 7}]


@pytest.fixture(autouse=True)
def _clear_cache():
    cache.clear()
    yield
    cache.clear()


@pytest.fixture
def fake_vm(monkeypatch):
    FakeVMServiceClient.created = 0
    monkeypatch.setattr(
        "vm_manager.orchestration.VMServiceClient", FakeVMServiceClient, raising=False
    )
    return FakeVMServiceClient


@pytest.fixture
def node():
    return create_node(capacity_vcpus=8, capacity_mem_mb=8192)


def make_key(user, scopes=("read", "exec", "admin"), name="test"):
    _obj, token = APIKey.create_key(user=user, name=name, scopes=list(scopes))
    return token


@pytest.fixture
def api():
    """Factory: return an APIClient authenticated with a bearer token."""

    def _make(token):
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
        return client

    return _make


@pytest.fixture
def user_with_type(node):
    """A user + active quota + one allowed container type that fits the node."""
    user = create_user("apiuser")
    ct = create_container_type(
        container_type_name="small", memory_mb=512, vcpus=1, disk_gib=10, credits_cost=1
    )
    create_quota(user=user, credits=5, allowed_types=[ct])
    user.refresh_from_db()
    return user, ct


@pytest.fixture
def owned_container(user_with_type, node):
    user, ct = user_with_type
    c = create_container(
        user=user, node=node, container_type=ct, status=Container.Status.RUNNING
    )
    return user, ct, c
