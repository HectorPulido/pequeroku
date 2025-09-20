import pytest
from django.urls import reverse
from rest_framework.test import APIClient

from vm_manager.models import FileTemplate, FileTemplateItem

from vm_manager.test_utils import create_user, create_node, create_container

pytestmark = pytest.mark.django_db


def create_template(name="My Tpl", items=2):
    tpl = FileTemplate.objects.create(name=name, description="desc")
    for i in range(items):
        FileTemplateItem.objects.create(
            template=tpl,
            path=f"f{i}.txt",
            content=f"content-{i}",
            mode=0o644,
            order=i,
        )
    return tpl


def _patch_apply_and_audit(monkeypatch, capture):
    # Capture calls to apply_template without touching network/services
    def fake_apply(container_obj, tpl_obj, dest_path="/app", clean=True):
        capture["called"] = True
        capture["container_pk"] = container_obj.pk
        capture["template_pk"] = tpl_obj.pk
        capture["dest_path"] = dest_path
        capture["clean"] = clean
        return {"ok": True}

    # Patch the symbol used by the view
    monkeypatch.setattr("vm_manager.views.apply_template", fake_apply)
    # No-op audit
    monkeypatch.setattr("vm_manager.views.audit_log_http", lambda *a, **k: None)


def test_apply_template_success_owner_calls_apply_and_returns_payload(monkeypatch):
    capture = {
        "called": False,
    }
    _patch_apply_and_audit(monkeypatch, capture)

    user = create_user("u1")
    node = create_node()
    container = create_container(user=user, node=node)
    tpl = create_template(items=3)

    client = APIClient()
    client.force_authenticate(user=user)

    url = reverse("filetemplate-apply", kwargs={"pk": tpl.pk})
    payload = {
        "container_id": container.pk,
        "dest_path": "sub/dir",  # should normalize to "/sub/dir"
        "clean": False,
    }
    res = client.post(url, data=payload, format="json")
    assert res.status_code == 200, res.content

    data = res.json()
    assert data["status"] == "applied"
    assert data["template_id"] == tpl.pk
    assert data["container"] == container.pk
    assert data["dest_path"] == "/sub/dir"
    assert data["files_count"] == 3

    # Ensure our mocked apply_template was invoked with normalized values
    assert capture["called"] is True
    assert capture["container_pk"] == container.pk
    assert capture["template_pk"] == tpl.pk
    assert capture["dest_path"] == "/sub/dir"
    assert capture["clean"] is False


def test_apply_template_404_when_not_owner_and_not_superuser(monkeypatch):
    capture = {"called": False}
    _patch_apply_and_audit(monkeypatch, capture)

    owner = create_user("owner")
    other = create_user("other")
    node = create_node()
    foreign_container = create_container(user=owner, node=node)
    tpl = create_template(items=1)

    client = APIClient()
    client.force_authenticate(user=other)

    url = reverse("filetemplate-apply", kwargs={"pk": tpl.pk})
    payload = {
        "container_id": foreign_container.pk,
        "dest_path": "/app",
        "clean": True,
    }
    res = client.post(url, data=payload, format="json")
    assert res.status_code == 404

    # ensure apply_template didn't run
    assert capture["called"] is False


def test_apply_template_success_superuser_can_apply_to_any_container(monkeypatch):
    capture = {"called": False}
    _patch_apply_and_audit(monkeypatch, capture)

    owner = create_user("owner")
    superuser = create_user("root", is_superuser=True)
    node = create_node()
    foreign_container = create_container(user=owner, node=node)
    tpl = create_template(items=2)

    client = APIClient()
    client.force_authenticate(user=superuser)

    url = reverse("filetemplate-apply", kwargs={"pk": tpl.pk})
    payload = {
        "container_id": foreign_container.pk,
        # Omit dest_path/clean to use defaults: "/app", True
    }
    res = client.post(url, data=payload, format="json")
    assert res.status_code == 200, res.content

    data = res.json()
    assert data["status"] == "applied"
    assert data["template_id"] == tpl.pk
    assert data["container"] == foreign_container.pk
    assert data["dest_path"] == "/app"
    assert data["files_count"] == 2

    assert capture["called"] is True
    assert capture["container_pk"] == foreign_container.pk
    assert capture["template_pk"] == tpl.pk
    assert capture["dest_path"] == "/app"
    assert capture["clean"] is True
