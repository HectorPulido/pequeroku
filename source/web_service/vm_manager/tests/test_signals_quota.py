import pytest
from django.contrib.auth import get_user_model

from vm_manager.models import Node
from vm_manager.signals import SUPERUSER_QUOTA, create_default_node
from types import SimpleNamespace

pytestmark = pytest.mark.django_db

User = get_user_model()


def test_superuser_quota_is_unlimited():
    user = User.objects.create_superuser(username="root", password="pass1234", email="")
    assert user.quota.credits == SUPERUSER_QUOTA
    assert user.quota.ai_use_per_day == SUPERUSER_QUOTA


def test_regular_user_quota_uses_config_defaults():
    user = User.objects.create_user(username="bob", password="pass1234")
    assert user.quota.credits == 3
    assert user.quota.ai_use_per_day == 5


def test_default_node_syncs_runtime_token_only_for_local_node(monkeypatch):
    monkeypatch.setenv("BASE_NODE_AUTH_TOKEN", "test-generated-token")
    Node.objects.filter(name="base").delete()
    sender = SimpleNamespace(name="vm_manager")
    create_default_node(sender)
    node = Node.objects.get(name="base")
    assert node.active and node.auth_token == "test-generated-token"

    node.auth_token = "N/A"
    node.save(update_fields=["auth_token"])
    create_default_node(sender)
    node.refresh_from_db()
    assert node.auth_token == "test-generated-token"

    node.node_host = "https://remote.invalid/"
    node.auth_token = "remote-token"
    node.save(update_fields=["node_host", "auth_token"])
    create_default_node(sender)
    node.refresh_from_db()
    assert node.auth_token == "remote-token"
