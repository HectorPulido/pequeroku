import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse
from rest_framework.test import APIClient

from vm_manager.test_utils import create_user

pytestmark = pytest.mark.django_db


def patch_audit_noop(monkeypatch):
    # Avoid touching DB through AuditLog during tests
    monkeypatch.setattr("vm_manager.views.audit_log_http", lambda *a, **k: None)


def test_me_requires_auth(monkeypatch):
    patch_audit_noop(monkeypatch)
    client = APIClient()
    url = reverse("user-me")
    res = client.get(url)
    # Depending on auth settings it could be 401 or 403; accept either
    assert res.status_code in (401, 403)


def test_me_authenticated_returns_payload(monkeypatch):
    patch_audit_noop(monkeypatch)
    user = create_user("bob")
    client = APIClient()
    client.force_authenticate(user=user)

    url = reverse("user-me")
    res = client.get(url)
    assert res.status_code == 200
    data = res.json()
    assert data["username"] == "bob"
    assert data["has_quota"] in (True, False)
    assert isinstance(data["active_containers"], int)


def test_login_success_sets_session_and_me_ok(monkeypatch):
    patch_audit_noop(monkeypatch)
    user = create_user("carol", "s3cret")

    client = APIClient()
    login_url = reverse("user-login")
    res = client.post(
        login_url, {"username": "carol", "password": "s3cret"}, format="json"
    )
    assert res.status_code == 200
    assert res.json()["status"] == "ok"

    me_url = reverse("user-me")
    res_me = client.get(me_url)
    assert res_me.status_code == 200
    assert res_me.json()["username"] == "carol"


def test_login_fail_invalid_credentials(monkeypatch):
    patch_audit_noop(monkeypatch)
    create_user("dave", "rightpass")

    client = APIClient()
    login_url = reverse("user-login")
    res = client.post(
        login_url, {"username": "dave", "password": "wrongpass"}, format="json"
    )
    assert res.status_code == 400
    body = res.json()
    assert "error" in body
    assert body["error"] == "Invalid credentials"


def test_logout_clears_session(monkeypatch):
    patch_audit_noop(monkeypatch)
    user = create_user("erin", "topsecret")

    client = APIClient()
    # Login via the API endpoint to establish a session
    login_url = reverse("user-login")
    res_login = client.post(
        login_url, {"username": "erin", "password": "topsecret"}, format="json"
    )
    assert res_login.status_code == 200

    # Now logout
    logout_url = reverse("user-logout")
    res_logout = client.post(logout_url)
    assert res_logout.status_code == 200
    assert res_logout.json()["status"] == "ok"

    # After logout, me should be unauthorized
    me_url = reverse("user-me")
    res_me = client.get(me_url)
    assert res_me.status_code in (401, 403)
