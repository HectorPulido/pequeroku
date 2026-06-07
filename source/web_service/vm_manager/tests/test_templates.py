"""Tests for vm_manager.templates (apply_template / first_start_of_container).

The VM upload goes through ``VMServiceClient``; we patch it with a fake so no
network is touched. DB-backed paths use the shared factories in test_utils.
"""

from __future__ import annotations

import pytest

from vm_manager import templates as templates_mod
from vm_manager.models import Container, FileTemplate, FileTemplateItem
from vm_manager.test_utils import create_container


class FakeVMClient:
    """Captures the upload payload so we can assert what would be sent to the VM."""

    last_node = None
    last_call = None

    def __init__(self, node):
        FakeVMClient.last_node = node

    def upload_files(self, container_id, payload):
        FakeVMClient.last_call = (container_id, payload)
        return {"ok": True}


@pytest.fixture(autouse=True)
def _patch_client(monkeypatch):
    FakeVMClient.last_node = None
    FakeVMClient.last_call = None
    monkeypatch.setattr(templates_mod, "VMServiceClient", FakeVMClient)


def _make_template(slug="default"):
    # A base "default" template is created by a data migration; drop it so each
    # test controls the template (and its items) deterministically.
    FileTemplate.objects.filter(slug=slug).delete()
    tpl = FileTemplate.objects.create(name=f"tpl-{slug}", slug=slug)
    FileTemplateItem.objects.create(template=tpl, path="/app/a.py", content="print(1)", order=1)
    FileTemplateItem.objects.create(template=tpl, path="/app/b.py", content="print(2)", order=0)
    return tpl


@pytest.mark.django_db
def test_apply_template_uploads_items_ordered():
    container = create_container()
    tpl = _make_template(slug="custom-tpl")
    resp = templates_mod.apply_template(container, tpl, dest_path="/app", clean=True)
    assert resp == {"ok": True}

    cid, payload = FakeVMClient.last_call
    assert cid == str(container.container_id)
    assert payload.dest_path == "/app" and payload.clean is True
    # items are ordered by (order, path): b.py (order=0) before a.py (order=1)
    assert [f.path for f in payload.files] == ["/app/b.py", "/app/a.py"]
    assert [f.text for f in payload.files] == ["print(2)", "print(1)"]


@pytest.mark.django_db
def test_first_start_applies_default_template_and_flips_flag():
    container = create_container(first_start=True, status=Container.Status.RUNNING)
    _make_template(slug="default")

    templates_mod.first_start_of_container(container)

    container.refresh_from_db()
    assert container.first_start is False
    assert FakeVMClient.last_call is not None  # template was applied


@pytest.mark.django_db
def test_first_start_skips_when_flag_false():
    container = create_container(first_start=False, status=Container.Status.RUNNING)
    _make_template(slug="default")
    templates_mod.first_start_of_container(container)
    assert FakeVMClient.last_call is None  # nothing applied


@pytest.mark.django_db
def test_first_start_skips_when_not_running():
    container = create_container(first_start=True, status=Container.Status.STOPPED)
    _make_template(slug="default")
    templates_mod.first_start_of_container(container)
    assert FakeVMClient.last_call is None


@pytest.mark.django_db
def test_first_start_noop_when_no_default_template():
    container = create_container(first_start=True, status=Container.Status.RUNNING)
    # Drop the migration-seeded default so the lookup returns nothing.
    FileTemplate.objects.filter(slug="default").delete()
    templates_mod.first_start_of_container(container)
    assert FakeVMClient.last_call is None
    # The in-memory flag flip is NOT persisted: save() only runs after a template
    # is applied, so without a default template the DB row stays first_start=True.
    container.refresh_from_db()
    assert container.first_start is True
