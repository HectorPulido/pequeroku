import pytest
from rest_framework.test import APIClient

from platform_api.models import APIKey, hash_secret
from vm_manager.models import Container
from vm_manager.test_utils import create_user

from .conftest import make_key

pytestmark = pytest.mark.django_db


# --- model ------------------------------------------------------------------


def test_create_key_returns_token_and_stores_only_hash():
    user = create_user("k1")
    obj, token = APIKey.create_key(user=user, name="t", scopes=["read"])
    assert token.startswith("pk_")
    prefix, _, secret = token[3:].partition("_")
    assert obj.prefix == prefix
    assert obj.hashed_key == hash_secret(secret)
    assert obj.hashed_key != secret  # secret itself is never stored
    assert obj.verify_secret(secret) is True
    assert obj.verify_secret("wrong") is False


def test_scope_hierarchy():
    user = create_user("k2")
    admin, _ = APIKey.create_key(user=user, name="a", scopes=["admin"])
    execk, _ = APIKey.create_key(user=user, name="e", scopes=["exec"])
    readk, _ = APIKey.create_key(user=user, name="r", scopes=["read"])

    assert all(admin.has_scope(s) for s in ("read", "exec", "admin"))
    assert execk.has_scope("read") and execk.has_scope("exec")
    assert not execk.has_scope("admin")
    assert readk.has_scope("read")
    assert not readk.has_scope("exec")


# --- authentication ---------------------------------------------------------


def test_no_token_is_unauthorized():
    res = APIClient().get("/api/v1/containers/")
    assert res.status_code == 401
    assert res.json()["error"]["code"] == "unauthorized"


def test_garbage_bearer_is_unauthorized(api):
    res = api("not-a-key").get("/api/v1/containers/")
    assert res.status_code == 401


def test_unknown_prefix_is_unauthorized():
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION="Bearer pk_deadbeef_secret")
    res = client.get("/api/v1/containers/")
    assert res.status_code == 401


def test_revoked_key_is_unauthorized(api):
    user = create_user("k3")
    obj, token = APIKey.create_key(user=user, name="t", scopes=["read"])
    obj.revoked = True
    obj.save()
    res = api(token).get("/api/v1/containers/")
    assert res.status_code == 401


def test_valid_key_updates_last_used(api):
    user = create_user("k4")
    obj, token = APIKey.create_key(user=user, name="t", scopes=["read"])
    assert obj.last_used_at is None
    res = api(token).get("/api/v1/containers/")
    assert res.status_code == 200
    obj.refresh_from_db()
    assert obj.last_used_at is not None


# --- scope enforcement on endpoints ----------------------------------------


def test_read_key_cannot_exec(api, fake_vm, owned_container):
    user, ct, c = owned_container
    token = make_key(user, scopes=["read"])
    res = api(token).post(
        f"/api/v1/containers/{c.pk}/exec/", {"command": "ls"}, format="json"
    )
    assert res.status_code == 403
    assert res.json()["error"]["code"] == "forbidden_scope"


def test_exec_key_cannot_destroy(api, fake_vm, owned_container):
    user, ct, c = owned_container
    token = make_key(user, scopes=["read", "exec"])
    res = api(token).delete(f"/api/v1/containers/{c.pk}/")
    assert res.status_code == 403


def test_exec_key_cannot_create(api, fake_vm, user_with_type):
    user, ct = user_with_type
    token = make_key(user, scopes=["read", "exec"])
    res = api(token).post("/api/v1/containers/", {"type": ct.pk}, format="json")
    assert res.status_code == 403


def test_admin_key_can_create(api, fake_vm, user_with_type):
    user, ct = user_with_type
    token = make_key(user, scopes=["admin"])
    res = api(token).post("/api/v1/containers/", {"type": ct.pk}, format="json")
    assert res.status_code == 201, res.content
