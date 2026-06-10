import pytest
from rest_framework.test import APIClient

from platform_api.models import APIKey
from vm_manager.test_utils import create_user

pytestmark = pytest.mark.django_db

BASE = "/api/account/api-keys/"


def auth_client(user):
    c = APIClient()
    c.force_authenticate(user=user)
    return c


def test_requires_authentication():
    res = APIClient().get(BASE)
    assert res.status_code in (401, 403)


def test_create_returns_token_once():
    user = create_user("acct1")
    res = auth_client(user).post(
        BASE, {"name": "laptop", "scopes": ["read", "exec"]}, format="json"
    )
    assert res.status_code == 201, res.content
    body = res.json()
    assert body["token"].startswith("pk_")
    assert body["name"] == "laptop"
    assert set(body["scopes"]) == {"read", "exec"}
    key = APIKey.objects.get(pk=body["id"])
    assert key.user == user


def test_create_without_scopes_400():
    user = create_user("acct2")
    res = auth_client(user).post(BASE, {"name": "x", "scopes": []}, format="json")
    assert res.status_code == 400


def test_list_excludes_token_and_is_isolated():
    a = create_user("acct_a")
    b = create_user("acct_b")
    APIKey.create_key(user=a, name="akey", scopes=["read"])

    res = auth_client(a).get(BASE)
    assert res.status_code == 200
    rows = res.json()
    assert len(rows) == 1
    assert "token" not in rows[0]
    assert rows[0]["prefix"]

    # b sees none of a's keys
    assert auth_client(b).get(BASE).json() == []


def test_revoke_own_key_only():
    owner = create_user("acct_owner")
    other = create_user("acct_other")
    obj, _ = APIKey.create_key(user=owner, name="k", scopes=["read"])

    # other can't revoke
    assert auth_client(other).delete(f"{BASE}{obj.pk}/").status_code == 404
    obj.refresh_from_db()
    assert obj.revoked is False

    # owner can
    assert auth_client(owner).delete(f"{BASE}{obj.pk}/").status_code == 204
    obj.refresh_from_db()
    assert obj.revoked is True


def test_mcp_info():
    user = create_user("acct_mcp")
    res = auth_client(user).get(f"{BASE}mcp-info/")
    assert res.status_code == 200
    body = res.json()
    assert body["mcp_url"].endswith("/mcp")
    assert body["api_base"].endswith("/api/v1")
    assert "swagger-ui" in body["swagger_url"]
