import pytest

from platform_api.models import Run
from vm_manager.models import Container

from .conftest import make_key

pytestmark = pytest.mark.django_db


def test_sync_run_executes_and_destroys(api, fake_vm, user_with_type):
    user, ct = user_with_type
    token = make_key(user)
    res = api(token).post(
        "/api/v1/runs/",
        {"command": "echo hi", "type": ct.pk},
        format="json",
    )
    assert res.status_code == 200, res.content
    body = res.json()
    assert body["status"] == "succeeded"
    assert body["stdout"] == "hi\n"
    assert body["exit_code"] == 0
    # Ephemeral VM is gone (created then destroyed); no leftover container.
    assert Container.objects.filter(user=user).count() == 0
    run = Run.objects.get(pk=body["id"])
    assert run.container is None
    assert run.files == []


def test_sync_run_with_files(api, fake_vm, user_with_type):
    user, ct = user_with_type
    token = make_key(user)
    res = api(token).post(
        "/api/v1/runs/",
        {
            "command": "python main.py",
            "files": [{"path": "main.py", "content": "print('x')"}],
            "type": ct.pk,
        },
        format="json",
    )
    assert res.status_code == 200, res.content
    assert res.json()["status"] == "succeeded"


def test_run_defaults_to_cheapest_allowed_type(api, fake_vm, node):
    from vm_manager.test_utils import create_container_type, create_quota, create_user

    user = create_user("runuser")
    cheap = create_container_type(container_type_name="cheap", credits_cost=1)
    pricey = create_container_type(container_type_name="pricey", credits_cost=3)
    create_quota(user=user, credits=9, allowed_types=[cheap, pricey])
    token = make_key(user)
    res = api(token).post("/api/v1/runs/", {"command": "echo hi"}, format="json")
    assert res.status_code == 200, res.content
    assert res.json()["status"] == "succeeded"


def test_async_run_returns_202_and_is_pending(api, fake_vm, user_with_type):
    user, ct = user_with_type
    token = make_key(user)
    res = api(token).post(
        "/api/v1/runs/",
        {"command": "echo hi", "type": ct.pk, "async": True},
        format="json",
    )
    assert res.status_code == 202, res.content
    body = res.json()
    assert body["status"] == "pending"
    run_id = body["id"]

    # Pollable via GET /runs/{id}
    poll = api(token).get(f"/api/v1/runs/{run_id}/")
    assert poll.status_code == 200
    assert poll.json()["status"] == "pending"


def test_run_worker_executes_pending(api, fake_vm, user_with_type):
    from platform_api.management.commands.run_worker import Command

    user, ct = user_with_type
    token = make_key(user)
    res = api(token).post(
        "/api/v1/runs/",
        {"command": "echo hi", "type": ct.pk, "async": True},
        format="json",
    )
    run_id = res.json()["id"]

    processed = Command().run_once()
    assert processed == 1

    run = Run.objects.get(pk=run_id)
    assert run.status == "succeeded"
    assert run.stdout == "hi\n"
    assert run.container is None


def test_run_requires_exec_scope(api, fake_vm, user_with_type):
    user, ct = user_with_type
    token = make_key(user, scopes=["read"])
    res = api(token).post(
        "/api/v1/runs/", {"command": "echo hi", "type": ct.pk}, format="json"
    )
    assert res.status_code == 403


def test_run_retrieve_other_user_is_404(api, fake_vm, user_with_type):
    from vm_manager.test_utils import create_user

    user, ct = user_with_type
    token = make_key(user)
    res = api(token).post(
        "/api/v1/runs/", {"command": "echo hi", "type": ct.pk}, format="json"
    )
    run_id = res.json()["id"]

    intruder = create_user("intruder2")
    itoken = make_key(intruder)
    poll = api(itoken).get(f"/api/v1/runs/{run_id}/")
    assert poll.status_code == 404
