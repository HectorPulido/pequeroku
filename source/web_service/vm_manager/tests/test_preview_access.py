import base64
import re
from types import SimpleNamespace

import pytest
from django.test import Client

from vm_manager import orchestration
from vm_manager.test_utils import create_container, create_node, create_user

pytestmark = pytest.mark.django_db


@pytest.fixture
def preview(settings, monkeypatch):
    settings.PREVIEW_ORIGIN_TEMPLATE = "https://{preview}.preview.testserver"
    settings.PREVIEW_HOST_SUFFIX = "preview.testserver"
    settings.ALLOWED_HOSTS += [".preview.testserver"]
    user = create_user("preview-owner")
    vm = create_container(user=user, node=create_node())
    captured = []

    def proxy(vm_id, payload):
        captured.append((vm_id, payload))
        return {
            "ok": True,
            "status": 200,
            "headers": [
                ["Content-Type", "text/html"],
                ["Service-Worker-Allowed", "/"],
                ["Access-Control-Allow-Origin", "https://elsewhere.test"],
                ["Set-Cookie", "guest-session=guest"],
            ],
            "body_b64": base64.b64encode(b"<html><body>Guest</body></html>").decode(),
        }

    monkeypatch.setattr(
        orchestration, "get_service", lambda obj: SimpleNamespace(proxy=proxy)
    )
    panel = Client(enforce_csrf_checks=True)
    panel.force_login(user)
    return vm, panel, captured


def test_browser_preview_uses_one_time_host_scoped_grant(preview):
    vm, panel, captured = preview
    prefix = f"/api/containers/{vm.pk}/preview/8000/"
    host = f"vm-{vm.pk}-8000.preview.testserver"
    launch = panel.get(
        f"/api/containers/{vm.pk}/preview-launch/8000/app?hello=1", secure=True
    )
    assert launch.status_code == 200
    assert f"https://{host}{prefix}.pequeroku-auth" in launch.content.decode()
    assert launch["X-Frame-Options"] == "SAMEORIGIN"
    assert not captured
    ticket = re.search(rb'name="ticket" value="([^"]+)"', launch.content)[1].decode()

    def redeem(origin):
        return panel.post(
            f"{prefix}.pequeroku-auth",
            {"ticket": ticket},
            secure=True,
            HTTP_HOST=host,
            HTTP_ORIGIN=origin,
        )

    assert redeem("https://wrong.test").status_code == 404
    granted = redeem("https://testserver")
    assert granted.status_code == 303
    assert granted["Location"] == f"{prefix}app?hello=1"
    cookie = granted.cookies["__Host-pequeroku-preview"]
    assert cookie["secure"] and cookie["httponly"] and not cookie["domain"]
    assert redeem("https://testserver").status_code == 404

    first = panel.get(granted["Location"], secure=True, HTTP_HOST=host)
    assert first.status_code == 200
    assert b"Guest" in first.content
    assert first["Content-Security-Policy"].startswith(
        "frame-ancestors https://testserver"
    )
    assert "Service-Worker-Allowed" not in first
    assert "Access-Control-Allow-Origin" not in first
    assert not first.cookies
    assert "Cookie" not in captured[0][1]["headers"]
    assert panel.get(prefix, secure=True, HTTP_HOST=host).status_code == 200
    assert captured[-1][1]["headers"]["Cookie"] == "guest-session=guest"
    assert panel.get(prefix, secure=True).status_code == 401
    assert panel.get("/api/user/me/", secure=True, HTTP_HOST=host).status_code == 404
    assert (
        panel.get(
            prefix, secure=True, HTTP_HOST=host, HTTP_SERVICE_WORKER="script"
        ).status_code
        == 403
    )
    assert (
        panel.get(
            prefix, secure=True, HTTP_HOST=f"vm-{vm.pk}-8001.preview.testserver"
        ).status_code
        == 401
    )
    assert (
        panel.post(
            prefix, secure=True, HTTP_HOST=host, HTTP_ORIGIN="https://wrong.test"
        ).status_code
        == 403
    )

    panel.logout()
    assert panel.get(prefix, secure=True, HTTP_HOST=host).status_code == 401


def test_browser_preview_fails_closed_without_isolated_origin(settings, preview):
    settings.PREVIEW_ORIGIN_TEMPLATE = ""
    vm, panel, captured = preview
    response = panel.head(f"/api/containers/{vm.pk}/preview-launch/8000/", secure=True)
    assert response.status_code == 503
    assert not captured
