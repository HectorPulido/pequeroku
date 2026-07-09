"""Token auth for the preview endpoint.

An agent (or a browser embed that can't set request headers) reaches the SAME
preview URL the IDE uses by presenting its platform API key as an
``Authorization: Bearer`` header, an ``__pk_token`` query param, or the
short-lived ``__pk_preview_token`` cookie. Ownership stays enforced by the view's
``get_object()``.
"""

import base64
import types

import pytest
from rest_framework.request import Request
from rest_framework.test import APIClient, APIRequestFactory

from platform_api.models import APIKey
from vm_manager import orchestration
from vm_manager.models import Container
from vm_manager.preview_proxy import (
    PREVIEW_TOKEN_COOKIE,
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
        raw.COOKIES[PREVIEW_TOKEN_COOKIE] = cookie
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


def test_query_token_authenticates_and_flags_bootstrap_cookie():
    user = create_user("qry")
    req = _drf_request(query=(token := _read_key(user)))
    result = PreviewTokenAuthentication().authenticate(req)
    assert result is not None and result[0] == user
    # The flag tells the view to drop the path-scoped subresource cookie.
    assert getattr(req, "_preview_query_token", None) == token


def test_cookie_token_authenticates_without_reflagging():
    user = create_user("cke")
    req = _drf_request(cookie=_read_key(user))
    result = PreviewTokenAuthentication().authenticate(req)
    assert result is not None and result[0] == user
    assert getattr(req, "_preview_query_token", None) is None


def test_no_token_returns_none():
    assert PreviewTokenAuthentication().authenticate(_drf_request()) is None


def test_unknown_token_returns_none_not_raises():
    # Must fall through (None), never raise, so session auth can still run.
    got = PreviewTokenAuthentication().authenticate(
        _drf_request(header="pk_deadbeef_nope")
    )
    assert got is None


def test_revoked_key_returns_none():
    user = create_user("rev")
    obj, token = APIKey.create_key(user=user, name="k", scopes=["read"])
    obj.revoked = True
    obj.save(update_fields=["revoked"])
    assert PreviewTokenAuthentication().authenticate(_drf_request(header=token)) is None


def test_key_without_read_scope_denied():
    user = create_user("nos")
    # create_key floors scopes at ["read"], so strip them directly to exercise the
    # guard (a scopeless key must not be able to preview).
    obj, token = APIKey.create_key(user=user, name="k", scopes=["read"])
    obj.scopes = []
    obj.save(update_fields=["scopes"])
    assert PreviewTokenAuthentication().authenticate(_drf_request(header=token)) is None


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


def test_preview_via_query_token_sets_pathscoped_cookie(running_container):
    user, container = running_container
    resp = APIClient().get(f"{_url(container)}?{PREVIEW_TOKEN_QUERY}={_read_key(user)}")
    assert resp.status_code == 200
    assert PREVIEW_TOKEN_COOKIE in resp.cookies
    assert resp.cookies[PREVIEW_TOKEN_COOKIE]["path"] == _url(container)


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
