import pytest
from rest_framework.test import APIClient

from vm_manager.models import Container

from .conftest import make_key

pytestmark = pytest.mark.django_db


def test_idempotency_key_returns_same_resource(api, fake_vm, user_with_type):
    user, ct = user_with_type
    token = make_key(user)
    client = api(token)
    headers = {"HTTP_IDEMPOTENCY_KEY": "abc-123"}
    r1 = client.post("/api/v1/containers/", {"type": ct.pk}, format="json", **headers)
    r2 = client.post("/api/v1/containers/", {"type": ct.pk}, format="json", **headers)
    assert r1.status_code == 201 and r2.status_code == 201
    assert r1.json()["id"] == r2.json()["id"]
    # Only one container actually created despite two POSTs.
    assert Container.objects.filter(user=user).count() == 1


def test_without_idempotency_key_creates_two(api, fake_vm, user_with_type):
    user, ct = user_with_type
    token = make_key(user)
    client = api(token)
    client.post("/api/v1/containers/", {"type": ct.pk}, format="json")
    client.post("/api/v1/containers/", {"type": ct.pk}, format="json")
    assert Container.objects.filter(user=user).count() == 2


def test_v1_schema_is_served_and_scoped():
    res = APIClient().get("/api/v1/schema/")
    assert res.status_code == 200
    text = res.content.decode()
    assert "/api/v1/containers/" in text
    assert "PequeRoku Platform API" in text


def test_ide_schema_excludes_v1():
    res = APIClient().get("/api/schema/")
    assert res.status_code == 200
    text = res.content.decode()
    assert "/api/v1/containers/" not in text
    # sanity: the IDE schema still has its own containers path
    assert "/api/containers/" in text
