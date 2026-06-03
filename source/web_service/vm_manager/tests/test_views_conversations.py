"""REST endpoints for AI conversations stored in the VM.

GET    /api/containers/{pk}/conversations/            -> {conversations, current}
GET    /api/containers/{pk}/conversations/{id}/       -> {conversation_id, messages}
DELETE /api/containers/{pk}/conversations/{id}/       -> {conversations, current}
"""

import json

import pytest
from django.urls import reverse
from rest_framework.test import APIClient

import ai_services.conversations as convo
from vm_manager.test_utils import create_user, create_node, create_container

pytestmark = pytest.mark.django_db


class FakeService:
    def __init__(self, files=None, dirs=None):
        self.files = dict(files or {})
        self.dir_entries = list(dirs or [])
        self.execced = []

    def read_file(self, vm_id, path):
        if path in self.files:
            return {"found": True, "content": self.files[path]}
        return {"found": False, "content": ""}

    def upload_files(self, vm_id, payload):
        for f in payload.files:
            self.files[f.path] = f.text
        return {"ok": True}

    def list_dirs(self, vm_id, paths):
        return [
            {"path": f"{convo.MEMORY_DIR}/{n}", "name": n, "path_type": "file"}
            for n in self.dir_entries
        ]

    def execute_sh(self, vm_id, command):
        self.execced.append(command)
        return {"ok": True}


def _setup(monkeypatch, files=None, dirs=None):
    user = create_user("convo-user")
    container = create_container(
        user=user, node=create_node(), container_id="vm-convo-1"
    )
    svc = FakeService(files=files, dirs=dirs)
    monkeypatch.setattr(convo, "VMServiceClient", lambda node: svc)
    # bypass quota plumbing for the endpoint check
    monkeypatch.setattr(
        "vm_manager.views.ContainersViewSet._check_quota",
        lambda self, request: True,
    )
    client = APIClient()
    client.force_authenticate(user=user)
    return client, user, container, svc


def test_list_conversations_endpoint(monkeypatch):
    client, user, container, _svc = _setup(
        monkeypatch, dirs=["ai_memory_1.json", "ai_memory_2.json"]
    )
    # active pointer lives in the DB
    convo.set_current_id(user, container, 2)
    url = reverse("container-conversations", kwargs={"pk": container.pk})
    res = client.get(url)
    assert res.status_code == 200
    assert res.json() == {"conversations": [1, 2], "current": 2}


def test_get_conversation_messages_endpoint(monkeypatch):
    msgs = [{"role": "user", "content": "hi"}, {"role": "assistant", "content": "yo"}]
    client, _user, container, _svc = _setup(
        monkeypatch,
        files={convo.memory_path(3): json.dumps({"messages": msgs})},
        dirs=["ai_memory_3.json"],
    )
    url = reverse(
        "container-conversation", kwargs={"pk": container.pk, "conversation_id": "3"}
    )
    res = client.get(url)
    assert res.status_code == 200
    assert res.json() == {"conversation_id": 3, "messages": msgs}


def test_delete_conversation_endpoint(monkeypatch):
    client, _user, container, svc = _setup(
        monkeypatch, dirs=["ai_memory_1.json", "ai_memory_2.json"]
    )
    url = reverse(
        "container-conversation", kwargs={"pk": container.pk, "conversation_id": "2"}
    )
    res = client.delete(url)
    assert res.status_code == 200
    assert any("rm -f" in c and "ai_memory_2.json" in c for c in svc.execced)


def test_conversations_requires_auth(monkeypatch):
    _client, _user, container, _svc = _setup(monkeypatch)
    anon = APIClient()
    url = reverse("container-conversations", kwargs={"pk": container.pk})
    res = anon.get(url)
    assert res.status_code in (401, 403)
