import pytest
from typing import Any, cast
from django.http import HttpRequest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser
from asgiref.sync import async_to_sync

from internal_config.audit import audit_log_http, audit_log_ws
from internal_config.models import AuditLog

pytestmark = pytest.mark.django_db


class DummyRequest(HttpRequest):
    def __init__(self, meta, user):
        self.META = meta
        self.user = user


ALog = cast(Any, AuditLog)


def test_audit_log_http_with_xff_ua_and_user():
    User = get_user_model()
    user = User.objects.create_user(username="alice", password="secret")
    request = DummyRequest(
        meta={
            "HTTP_X_FORWARDED_FOR": "10.0.0.1, 127.0.0.1",
            "HTTP_USER_AGENT": "pytest-agent",
        },
        user=user,
    )

    audit_log_http(
        request,
        action="login",
        target_type="user",
        target_id=str(user.pk),
        message="successful login",
        metadata={"k": "v"},
        success=True,
    )

    assert ALog.objects.count() == 1
    log = ALog.objects.first()
    assert log is not None
    assert log.user == user
    assert log.action == "login"
    assert log.target_type == "user"
    assert log.target_id == str(user.pk)
    assert log.message == "successful login"
    assert log.metadata == {"k": "v"}
    assert log.ip == "10.0.0.1"
    assert log.user_agent == "pytest-agent"
    assert log.success is True


def test_audit_log_http_without_xff_uses_remote_addr_and_anonymous_user_and_default_metadata():
    request = DummyRequest(
        meta={"REMOTE_ADDR": "8.8.8.8"},
        user=AnonymousUser(),
    )

    audit_log_http(
        request,
        action="logout",
        message="bye",
        metadata=None,
        success=False,
    )

    assert ALog.objects.count() == 1
    log = ALog.objects.first()
    assert log is not None
    assert log.user is None
    assert log.action == "logout"
    assert log.message == "bye"
    assert log.metadata == {}
    assert log.ip == "8.8.8.8"
    assert log.user_agent == ""
    assert log.success is False


def test_audit_log_ws_with_values_and_defaults():
    User = get_user_model()
    user = User.objects.create_user(username="bob", password="secret")

    log1 = async_to_sync(audit_log_ws)(
        action="ws.connect",
        user=user,
        ip="1.1.1.1",
        user_agent="ws-agent",
        target_type="socket",
        target_id="abc",
        message="hello",
        metadata={"x": 1},
        success=True,
    )
    assert isinstance(log1, AuditLog)
    assert log1.user == user
    assert log1.ip == "1.1.1.1"
    assert log1.user_agent == "ws-agent"
    assert log1.metadata == {"x": 1}
    assert log1.action == "ws.connect"
    assert log1.success is True

    log2 = async_to_sync(audit_log_ws)(
        action="ws.disconnect",
        user=None,
        ip="",
        user_agent="",
        metadata=None,
    )
    assert isinstance(log2, AuditLog)
    assert log2.user is None
    assert log2.ip is None
    assert log2.user_agent == ""
    assert log2.metadata == {}
    assert log2.action == "ws.disconnect"
    assert log2.success is True
