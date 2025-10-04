import pytest
from django.urls import reverse
from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework.test import APIClient

from vm_manager.models import Container, ResourceQuota

from vm_manager.test_utils import (
    create_quota,
    create_user,
    create_container,
    create_node,
    create_container_type,
)

pytestmark = pytest.mark.django_db


class DummyHTTPResponse:
    def __init__(
        self,
        content=b"DATA",
        status=200,
        headers=None,
        json_data=None,
        content_type="application/octet-stream",
        content_disposition=None,
    ):
        self.content = content
        self.status_code = status
        self.headers = headers or {}
        if content_type is not None:
            self.headers.setdefault("Content-Type", content_type)
        if content_disposition is not None:
            self.headers.setdefault("Content-Disposition", content_disposition)
        self._json_data = json_data

    def json(self):
        if self._json_data is not None:
            return self._json_data
        raise ValueError("No JSON available")


class FakeVMServiceClient:
    created_counter = 0

    def __init__(
        self, node, timeout=30.0, session=None, extra_headers=None, blocking=False
    ):
        self.node = node
        self.blocking = blocking
        self._last_action = None

    def list_vms(self):
        return []

    def create_vm(self, payload):
        FakeVMServiceClient.created_counter += 1
        return {"id": f"vm-new-{FakeVMServiceClient.created_counter}"}

    def get_vms(self, vm_ids):
        # Return a dict keyed by id as expected by _index_vms_by_id
        return {str(i): {"id": str(i), "state": "running"} for i in vm_ids}

    def get_vm(self, vm_id):
        return {"id": vm_id, "state": "running"}

    def delete_vm(self, vm_id):
        return {"status": "deleted"}

    def action_vm(self, vm_id, action):
        self._last_action = action.action
        return {"status": "ok", "action": action.action}

    def upload_files(self, vm_id, payload):
        return {"ok": True}

    def upload_files_blob(self, vm_id, payload):
        files = payload.get("files") or []
        # For text uploads, count files
        return {"length": len(files)}

    def statistics(self, vm_id):
        return {"cpu": 0.12, "mem": 123}

    def download_file(self, vm_id, path):
        return DummyHTTPResponse(
            content=b"hello world",
            status=200,
            content_type="text/plain",
            content_disposition='attachment; filename="hello.txt"',
        )

    def download_folder(self, vm_id, root="/app", prefer_fmt="zip"):
        # Let the view compute default filename if header missing
        return DummyHTTPResponse(
            content=b"ZIPDATA",
            status=200,
            content_type=(
                "application/zip" if prefer_fmt == "zip" else "application/gzip"
            ),
            content_disposition=None,
        )


def patch_services(monkeypatch):
    # Patch VM client in all modules that may import it directly
    targets = [
        "vm_manager.vm_client.VMServiceClient",
        "vm_manager.views.VMServiceClient",
        "vm_manager.mixin.VMServiceClient",
        "vm_manager.templates.VMServiceClient",
        "vm_manager.editor_consumers.VMServiceClient",
        "vm_manager.management.commands.reconcile_containers.VMServiceClient",
    ]
    for t in targets:
        monkeypatch.setattr(t, FakeVMServiceClient, raising=False)
    # Patch audit to no-op
    monkeypatch.setattr("vm_manager.views.audit_log_http", lambda *a, **k: None)
    # Ensure fresh quota is fetched from DB (avoid stale OneToOne cache on request.user)
    monkeypatch.setattr(
        "vm_manager.views.ContainersViewSet._check_quota",
        lambda self, request: ResourceQuota.objects.filter(
            user=request.user, active=True
        ).first(),
        raising=False,
    )
    # Ensure fresh quota is fetched from DB (avoid stale OneToOne cache on request.user)
    monkeypatch.setattr(
        "vm_manager.views.ContainersViewSet._check_quota",
        lambda self, request: ResourceQuota.objects.filter(
            user=request.user, active=True
        ).first(),
        raising=False,
    )


def test_list_containers_syncs_statuses(monkeypatch):
    patch_services(monkeypatch)

    user = create_user("u1")
    node = create_node()
    c = create_container(user=user, node=node, status=Container.Status.STOPPED)
    client = APIClient()
    client.force_authenticate(user=user)

    url = reverse("container-list")
    res = client.get(url)
    assert res.status_code == 200

    # Should include our container and have synchronized status to 'running'
    assert len(res.json()) == 1
    assert res.json()[0]["id"] == c.id
    assert res.json()[0]["status"] == "running"


def test_retrieve_updates_status(monkeypatch):
    patch_services(monkeypatch)

    user = create_user("u2")
    node = create_node()
    c = create_container(user=user, node=node, status=Container.Status.ERROR)

    client = APIClient()
    client.force_authenticate(user=user)

    url = reverse("container-detail", kwargs={"pk": c.pk})
    res = client.get(url)
    assert res.status_code == 200
    assert res.json()["status"] == "running"


def test_create_container_uses_quota_and_node_and_vmclient(monkeypatch):
    patch_services(monkeypatch)

    user = create_user("u3")
    # Node with enough resources
    node = create_node(capacity_vcpus=2, capacity_mem_mb=2048)
    # Create a container type within node capacity
    t = create_container_type(
        container_type_name="S", memory_mb=256, vcpus=1, disk_gib=10, credits_cost=1
    )
    # Create quota and allow this type
    create_quota(user=user, credits=5, ai_use_per_day=5)
    user.refresh_from_db()
    user.quota.allowed_types.set([t.id])

    client = APIClient()
    client.force_authenticate(user=user)

    url = reverse("container-list")
    res = client.post(url, data={"container_type": t.id}, format="json")
    assert res.status_code == 201, res.content

    data = res.json()
    assert data["container_id"].startswith("vm-new-")
    # Check DB object created with the ID from create_vm
    obj = Container.objects.get(pk=data["id"])
    assert obj.node == node
    assert obj.memory_mb == 256
    assert obj.vcpus == 1
    assert obj.disk_gib == 10


def test_destroy_container_calls_vm_delete(monkeypatch):
    patch_services(monkeypatch)

    user = create_user("u4")
    create_quota(user=user)
    node = create_node()
    c = create_container(user=user, node=node)

    client = APIClient()
    client.force_authenticate(user=user)

    url = reverse("container-detail", kwargs={"pk": c.pk})
    res = client.delete(url)
    assert res.status_code == 200
    assert res.json()["status"] == "stopped"
    assert not Container.objects.filter(pk=c.pk).exists()


def test_upload_file_succeeds(monkeypatch):
    patch_services(monkeypatch)

    user = create_user("u5")
    create_quota(user=user)
    node = create_node()
    c = create_container(user=user, node=node)

    client = APIClient()
    client.force_authenticate(user=user)

    url = reverse("container-upload-file", kwargs={"pk": c.pk})
    file_obj = SimpleUploadedFile(
        "hello.txt", b"hello world", content_type="text/plain"
    )
    res = client.post(
        url, data={"file": file_obj, "dest_path": "/app"}, format="multipart"
    )

    assert res.status_code == 200, res.content
    assert "length" in res.json()
    assert res.json()["length"] == 1


def test_statistics_requires_running(monkeypatch):
    patch_services(monkeypatch)

    user = create_user("u6")
    create_quota(user=user)
    node = create_node()
    c = create_container(user=user, node=node, status=Container.Status.STOPPED)

    client = APIClient()
    client.force_authenticate(user=user)

    url = reverse("container-statistics", kwargs={"pk": c.pk})
    res = client.get(url)
    assert res.status_code == 400
    assert "error" in res.json()


def test_statistics_success(monkeypatch):
    patch_services(monkeypatch)

    user = create_user("u7")
    create_quota(user=user)
    node = create_node()
    c = create_container(user=user, node=node, status=Container.Status.RUNNING)

    client = APIClient()
    client.force_authenticate(user=user)

    url = reverse("container-statistics", kwargs={"pk": c.pk})
    res = client.get(url)
    assert res.status_code == 200
    assert "cpu" in res.json()


@pytest.mark.parametrize(
    "action_name, expected_status_key",
    [
        ("container-power-on", "starting..."),
        ("container-power-off", "stopping..."),
        ("container-restart-container", "restarted"),
    ],
)
def test_power_actions(monkeypatch, action_name, expected_status_key):
    patch_services(monkeypatch)

    user = create_user("u8")
    create_quota(user=user)
    node = create_node()
    c = create_container(user=user, node=node, status=Container.Status.RUNNING)

    client = APIClient()
    client.force_authenticate(user=user)

    url = reverse(action_name, kwargs={"pk": c.pk})
    res = client.post(url)
    assert res.status_code == 200
    assert res.json()["status"] == expected_status_key


def test_download_file_requires_path(monkeypatch):
    patch_services(monkeypatch)

    user = create_user("u9")
    create_quota(user=user)
    node = create_node()
    c = create_container(user=user, node=node)

    client = APIClient()
    client.force_authenticate(user=user)

    url = reverse("container-download-file", kwargs={"pk": c.pk})
    res = client.get(url)
    assert res.status_code == 400
    assert "error" in res.json()


def test_download_file_success(monkeypatch):
    patch_services(monkeypatch)

    user = create_user("u10")
    create_quota(user=user)
    node = create_node()
    c = create_container(user=user, node=node)

    client = APIClient()
    client.force_authenticate(user=user)

    url = reverse("container-download-file", kwargs={"pk": c.pk})
    res = client.get(url, {"path": "/app/hello.txt"})
    assert res.status_code == 200
    assert res["Content-Type"] == "text/plain"
    assert "attachment; filename=" in res["Content-Disposition"]
    assert res.content == b"hello world"


def test_download_folder_success(monkeypatch):
    patch_services(monkeypatch)

    user = create_user("u11")
    create_quota(user=user)
    node = create_node()
    c = create_container(user=user, node=node)

    client = APIClient()
    client.force_authenticate(user=user)

    url = reverse("container-download-folder", kwargs={"pk": c.pk})
    res = client.get(url, {"root": "/app/src", "prefer_fmt": "zip"})
    assert res.status_code == 200
    # Since our fake response doesn't set Content-Disposition,
    # the view should set a default one based on root and fmt
    assert "attachment; filename=" in res["Content-Disposition"]
    assert res.content == b"ZIPDATA"


def test_create_container_fallback_when_insufficient_capacity(monkeypatch):
    patch_services(monkeypatch)

    user = create_user("u12")
    # Candidate node exists but with insufficient capacity
    node = create_node(capacity_vcpus=2, capacity_mem_mb=2048)
    # Type larger than node capacity to force scheduler to return None
    t = create_container_type(
        container_type_name="XL", memory_mb=16384, vcpus=8, disk_gib=20, credits_cost=1
    )
    # Quota allows this type
    create_quota(user=user, credits=5)
    user.refresh_from_db()
    user.quota.allowed_types.set([t.id])

    client = APIClient()
    client.force_authenticate(user=user)

    url = reverse("container-list")
    res = client.post(url, data={"container_type": t.id}, format="json")
    assert res.status_code == 201

    data = res.json()
    assert "warning" in data
    assert "No available nodes with enough capacity" in data["warning"]
    assert "X-Warning" in res
    assert "No available nodes with enough capacity" in res["X-Warning"]

    obj = Container.objects.get(pk=data["id"])
    assert obj.node is not None


def test_create_container_fallback_when_no_candidates(monkeypatch):
    patch_services(monkeypatch)

    user = create_user("u13")
    # No candidates due to unhealthy node (still present for random fallback)
    node = create_node(healthy=False)
    # Type that would fit on a normal node
    t = create_container_type(
        container_type_name="S", memory_mb=256, vcpus=1, disk_gib=10, credits_cost=1
    )
    create_quota(user=user, credits=3)
    user.refresh_from_db()
    user.quota.allowed_types.set([t.id])

    client = APIClient()
    client.force_authenticate(user=user)

    url = reverse("container-list")
    res = client.post(url, data={"container_type": t.id}, format="json")
    assert res.status_code == 201

    data = res.json()
    assert "warning" in data
    assert "No available nodes with enough capacity" in data["warning"]
    assert "X-Warning" in res

    obj = Container.objects.get(pk=data["id"])
    # Should still assign the only node via random fallback
    assert obj.node is not None


def test_power_off_sets_desired_state_stopped(monkeypatch):
    patch_services(monkeypatch)

    user = create_user("u14")
    create_quota(user=user)
    node = create_node()
    c = create_container(
        user=user,
        node=node,
        status=Container.Status.RUNNING,
        desired_state=Container.DesirableStatus.RUNNING,
    )

    client = APIClient()
    client.force_authenticate(user=user)

    url = reverse("container-power-off", kwargs={"pk": c.pk})
    res = client.post(url)
    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "stopping..."
    assert body["desired_state"] == Container.DesirableStatus.STOPPED

    c.refresh_from_db()
    assert c.desired_state == Container.DesirableStatus.STOPPED


def test_power_on_sets_desired_state_running(monkeypatch):
    patch_services(monkeypatch)

    user = create_user("u15")
    create_quota(user=user)
    node = create_node()
    c = create_container(
        user=user,
        node=node,
        status=Container.Status.STOPPED,
        desired_state=Container.DesirableStatus.STOPPED,
    )

    client = APIClient()
    client.force_authenticate(user=user)

    url = reverse("container-power-on", kwargs={"pk": c.pk})
    res = client.post(url)
    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "starting..."
    assert body["desired_state"] == Container.DesirableStatus.RUNNING

    c.refresh_from_db()
    assert c.desired_state == Container.DesirableStatus.RUNNING


def test_create_container_requires_container_type(monkeypatch):
    patch_services(monkeypatch)

    user = create_user("req_type")
    create_quota(user=user, credits=3)
    node = create_node()

    client = APIClient()
    client.force_authenticate(user=user)

    url = reverse("container-list")
    res = client.post(url, data={}, format="json")
    assert res.status_code == 400
    assert "Invalid container type" in res.content.decode()


def test_create_container_type_not_allowed(monkeypatch):
    patch_services(monkeypatch)

    user = create_user("not_allowed")
    # Create a type but do not add to allowed_types
    t = create_container_type(
        container_type_name="M", memory_mb=512, vcpus=2, disk_gib=10, credits_cost=1
    )
    create_quota(user=user, credits=5)
    node = create_node()

    client = APIClient()
    client.force_authenticate(user=user)

    url = reverse("container-list")
    res = client.post(url, data={"container_type": t.id}, format="json")
    assert res.status_code == 403
    assert "not allowed" in res.content.decode().lower()


def test_create_container_insufficient_credits(monkeypatch):
    patch_services(monkeypatch)

    user = create_user("no_credits")
    # Type costs 2 credits; give user only 1
    t = create_container_type(
        container_type_name="H", memory_mb=256, vcpus=1, disk_gib=10, credits_cost=2
    )
    create_quota(user=user, credits=1)
    user.refresh_from_db()
    user.quota.allowed_types.set([t.id])
    node = create_node()

    client = APIClient()
    client.force_authenticate(user=user)

    url = reverse("container-list")
    res = client.post(url, data={"container_type": t.id}, format="json")
    assert res.status_code == 403
    assert "not enough credits" in res.content.decode().lower()


# Removed duplicate tests for container creation validations
