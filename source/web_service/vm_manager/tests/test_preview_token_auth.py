"""Authorization and method scopes for the real preview endpoint."""

import base64
import types

import pytest
from rest_framework.exceptions import AuthenticationFailed, PermissionDenied
from rest_framework.request import Request
from rest_framework.test import APIClient, APIRequestFactory

from platform_api.models import APIKey
from vm_manager import orchestration
from vm_manager.models import Container
from vm_manager.preview_proxy import (
    PREVIEW_TOKEN_QUERY,
    PreviewTokenAuthentication,
)
from vm_manager.test_utils import create_container, create_node, create_user

pytestmark = pytest.mark.django_db


# --- unit: PreviewTokenAuthentication --------------------------------------- #
def _drf_request(*, header=None, query=None, cookie=None):
    extra = {"HTTP_AUTHORIZATION": f"Bearer {header}"} if header else {}
    path = "/api/containers/1/preview/8000/"
    if query:
        path += f"?{PREVIEW_TOKEN_QUERY}={query}"
    raw = APIRequestFactory().get(path, **extra)
    if cookie:
        raw.COOKIES["__pk_preview_token"] = cookie
    return Request(raw)


def _read_key(user, scopes=("read",)):
    _obj, token = APIKey.create_key(user=user, name="k", scopes=list(scopes))
    return token


def test_header_bearer_token_authenticates():
    user = create_user("hdr")
    result = PreviewTokenAuthentication().authenticate(
        _drf_request(header=_read_key(user))
    )
    assert result is not None
    auth_user, key = result
    assert auth_user == user
    assert isinstance(key, APIKey)


@pytest.mark.parametrize("via", ["query", "cookie"])
def test_legacy_token_transports_do_not_authenticate(via):
    user = create_user("legacy")
    request = _drf_request(**{via: _read_key(user)})
    assert PreviewTokenAuthentication().authenticate(request) is None


def test_no_token_returns_none():
    assert PreviewTokenAuthentication().authenticate(_drf_request()) is None


@pytest.mark.parametrize("revoke", [False, True])
def test_invalid_and_revoked_header_credentials_are_rejected(revoke):
    if revoke:
        user = create_user("rev")
        key, token = APIKey.create_key(user=user, name="k", scopes=["read"])
        key.revoked = True
        key.save(update_fields=["revoked"])
    else:
        token = "pk_deadbeef_nope"
    with pytest.raises(AuthenticationFailed):
        PreviewTokenAuthentication().authenticate(_drf_request(header=token))


def test_key_without_read_scope_denied():
    user = create_user("nos")
    # create_key floors scopes at ["read"], so strip them directly to exercise the
    # guard (a scopeless key must not be able to preview).
    obj, token = APIKey.create_key(user=user, name="k", scopes=["read"])
    obj.scopes = []
    obj.save(update_fields=["scopes"])
    with pytest.raises(PermissionDenied):
        PreviewTokenAuthentication().authenticate(_drf_request(header=token))


# --- integration: through the real URL + auth stack ------------------------- #
def _html_env():
    return {
        "ok": True,
        "status": 200,
        "headers": [["Content-Type", "text/html; charset=utf-8"]],
        "body_b64": base64.b64encode(b"<html><body>ok</body></html>").decode("ascii"),
    }


@pytest.fixture
def running_container(monkeypatch):
    node = create_node()
    user = create_user("owner")
    container = create_container(user=user, node=node, status=Container.Status.RUNNING)
    monkeypatch.setattr(
        orchestration,
        "get_service",
        lambda obj: types.SimpleNamespace(proxy=lambda vm_id, payload: _html_env()),
    )
    return user, container


def _url(container, port=8000):
    return f"/api/containers/{container.pk}/preview/{port}/"


def test_preview_via_header_token(running_container):
    user, container = running_container
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {_read_key(user)}")
    resp = client.get(_url(container))
    assert resp.status_code == 200
    assert b"ok" in resp.content
    assert resp["Content-Security-Policy"].startswith("sandbox;")


def test_legacy_preview_link_and_panel_session_cannot_open_raw_preview(
    running_container,
):
    user, container = running_container
    client = APIClient()
    url = f"{_url(container)}?{PREVIEW_TOKEN_QUERY}={_read_key(user)}"
    assert client.get(url).status_code == 401
    client.force_login(user)
    response = client.get(url)
    assert response.status_code == 401
    assert "__pk_preview_token" not in response.cookies


@pytest.mark.parametrize("method", ["post", "put", "patch", "delete"])
def test_preview_unsafe_methods_require_exec_scope(running_container, method):
    user, container = running_container
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {_read_key(user)}")
    request = getattr(client, method)
    assert request(_url(container)).status_code == 403
    token = _read_key(user, scopes=("exec",))
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
    assert request(_url(container)).status_code == 200


def test_preview_without_auth_rejected(running_container):
    _user, container = running_container
    resp = APIClient().get(_url(container))
    assert resp.status_code in (401, 403)


def test_preview_other_users_container_not_found(running_container):
    _owner, container = running_container
    intruder = create_user("intruder")
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {_read_key(intruder)}")
    resp = client.get(_url(container))
    assert resp.status_code == 404  # ownership enforced by get_object()


def test_preview_invalid_token_rejected(running_container):
    _user, container = running_container
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION="Bearer pk_deadbeef_nope")
    resp = client.get(_url(container))
    assert resp.status_code in (401, 403)
