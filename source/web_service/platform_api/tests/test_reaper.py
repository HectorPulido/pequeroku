import pytest
from django.utils import timezone

from platform_api.management.commands.reap_expired import Command
from vm_manager.models import Container
from vm_manager.test_utils import create_container, create_node, create_user

pytestmark = pytest.mark.django_db


class FakeClient:
    deleted = []

    def __init__(self, node, **kwargs):
        self.node = node

    def delete_vm(self, vm_id):
        FakeClient.deleted.append(vm_id)
        return {"status": "deleted"}


@pytest.fixture
def fake_reaper_client(monkeypatch):
    FakeClient.deleted = []
    monkeypatch.setattr(
        "platform_api.management.commands.reap_expired.VMServiceClient",
        FakeClient,
        raising=False,
    )
    return FakeClient


def test_reaps_expired_only(fake_reaper_client):
    user = create_user("reapu")
    node = create_node()
    past = timezone.now() - timezone.timedelta(seconds=10)
    future = timezone.now() + timezone.timedelta(hours=1)

    expired = create_container(
        user=user, node=node, container_id="exp-1", expires_at=past
    )
    persistent = create_container(
        user=user, node=node, container_id="keep-1", expires_at=None
    )
    not_yet = create_container(
        user=user, node=node, container_id="future-1", expires_at=future
    )

    reaped = Command().run_once()
    assert reaped == 1
    assert FakeClient.deleted == ["exp-1"]
    assert not Container.objects.filter(pk=expired.pk).exists()
    assert Container.objects.filter(pk=persistent.pk).exists()
    assert Container.objects.filter(pk=not_yet.pk).exists()


def test_reaper_drops_row_even_if_node_delete_fails(monkeypatch):
    class Boom:
        def __init__(self, node, **kwargs):
            pass

        def delete_vm(self, vm_id):
            raise RuntimeError("node down")

    monkeypatch.setattr(
        "platform_api.management.commands.reap_expired.VMServiceClient",
        Boom,
        raising=False,
    )
    user = create_user("reapu2")
    node = create_node()
    past = timezone.now() - timezone.timedelta(seconds=10)
    c = create_container(user=user, node=node, container_id="exp-2", expires_at=past)

    reaped = Command().run_once()
    assert reaped == 1
    assert not Container.objects.filter(pk=c.pk).exists()
