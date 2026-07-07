import pytest

from vm_manager.models import Container
from vm_manager.test_utils import create_container, create_user

from .conftest import make_key

pytestmark = pytest.mark.django_db


def test_create_with_type_id_and_name(api, fake_vm, user_with_type):
    user, ct = user_with_type
    token = make_key(user)
    res = api(token).post(
        "/api/v1/containers/", {"type": ct.pk, "name": "myc"}, format="json"
    )
    assert res.status_code == 201, res.content
    body = res.json()
    assert body["name"] == "myc"
    assert body["type"]["name"] == "small"
    obj = Container.objects.get(pk=body["id"])
    assert obj.user == user
    assert obj.container_id.startswith("vm-new-")
    # API/MCP workspaces must never carry the armed welcome-seed flag, so a later
    # IDE connect can't overwrite the agent's programmatically-populated /app.
    assert obj.first_start is False


def test_create_with_type_name(api, fake_vm, user_with_type):
    user, ct = user_with_type
    token = make_key(user)
    res = api(token).post("/api/v1/containers/", {"type": "small"}, format="json")
    assert res.status_code == 201, res.content


def test_create_with_ttl_sets_expires_at(api, fake_vm, user_with_type):
    user, ct = user_with_type
    token = make_key(user)
    res = api(token).post(
        "/api/v1/containers/", {"type": ct.pk, "ttl_seconds": 60}, format="json"
    )
    assert res.status_code == 201
    obj = Container.objects.get(pk=res.json()["id"])
    assert obj.expires_at is not None


def test_create_unknown_type_is_invalid_request(api, fake_vm, user_with_type):
    user, ct = user_with_type
    token = make_key(user)
    res = api(token).post("/api/v1/containers/", {"type": "nope"}, format="json")
    assert res.status_code == 400
    assert res.json()["error"]["code"] == "invalid_request"


def test_create_type_not_allowed(api, fake_vm, node):
    from vm_manager.test_utils import create_container_type, create_quota

    user = create_user("napi")
    allowed = create_container_type(container_type_name="ok", credits_cost=1)
    other = create_container_type(container_type_name="locked", credits_cost=1)
    create_quota(user=user, credits=5, allowed_types=[allowed])
    token = make_key(user)
    res = api(token).post("/api/v1/containers/", {"type": other.pk}, format="json")
    assert res.status_code == 403
    assert res.json()["error"]["code"] == "type_not_allowed"


def test_create_insufficient_credits(api, fake_vm, node):
    from vm_manager.test_utils import create_container_type, create_quota

    user = create_user("poor")
    ct = create_container_type(container_type_name="big", credits_cost=5)
    create_quota(user=user, credits=1, allowed_types=[ct])
    token = make_key(user)
    res = api(token).post("/api/v1/containers/", {"type": ct.pk}, format="json")
    assert res.status_code == 403
    assert res.json()["error"]["code"] == "quota_exceeded"


def test_list_only_owned_and_excludes_pool(api, fake_vm, owned_container, node):
    user, ct, c = owned_container
    other = create_user("other")
    create_container(user=other, node=node, status=Container.Status.RUNNING)
    # a pool VM owned by this user must be hidden
    create_container(
        user=user, node=node, status=Container.Status.RUNNING, is_pool=True
    )
    token = make_key(user)
    res = api(token).get("/api/v1/containers/")
    assert res.status_code == 200
    body = res.json()
    assert "results" in body  # paginated
    ids = {row["id"] for row in body["results"]}
    assert ids == {c.pk}


def test_retrieve_refreshes_status(api, fake_vm, owned_container):
    user, ct, c = owned_container
    c.status = Container.Status.STOPPED
    c.save(update_fields=["status"])
    token = make_key(user)
    res = api(token).get(f"/api/v1/containers/{c.pk}/")
    assert res.status_code == 200
    assert res.json()["status"] == "running"  # fake get_vm reports running


def test_retrieve_other_users_container_is_404(api, fake_vm, owned_container, node):
    user, ct, c = owned_container
    intruder = create_user("intruder")
    token = make_key(intruder)
    res = api(token).get(f"/api/v1/containers/{c.pk}/")
    assert res.status_code == 404
    assert res.json()["error"]["code"] == "not_found"


def test_destroy(api, fake_vm, owned_container):
    user, ct, c = owned_container
    token = make_key(user)
    res = api(token).delete(f"/api/v1/containers/{c.pk}/")
    assert res.status_code == 204
    assert not Container.objects.filter(pk=c.pk).exists()


def test_actions_set_desired_state(api, fake_vm, owned_container):
    user, ct, c = owned_container
    token = make_key(user)
    res = api(token).post(
        f"/api/v1/containers/{c.pk}/actions/", {"action": "stop"}, format="json"
    )
    assert res.status_code == 200
    c.refresh_from_db()
    assert c.desired_state == Container.DesirableStatus.STOPPED


def test_exec_returns_exit_code(api, fake_vm, owned_container):
    user, ct, c = owned_container
    token = make_key(user)
    res = api(token).post(
        f"/api/v1/containers/{c.pk}/exec/", {"command": "echo hi"}, format="json"
    )
    assert res.status_code == 200
    body = res.json()
    assert body["stdout"] == "hi\n"
    assert body["exit_code"] == 0
    assert body["truncated"] is False


def test_exec_on_stopped_machine_is_409(api, fake_vm, owned_container):
    user, ct, c = owned_container
    token = make_key(user)
    res = api(token).post(
        f"/api/v1/containers/{c.pk}/exec/",
        {"command": "__notrunning__"},
        format="json",
    )
    assert res.status_code == 409
    assert res.json()["error"]["code"] == "machine_not_running"


def test_exec_background_returns_process_id(api, fake_vm, owned_container):
    user, ct, c = owned_container
    token = make_key(user)
    res = api(token).post(
        f"/api/v1/containers/{c.pk}/exec/",
        {"command": "sleep 100", "background": True},
        format="json",
    )
    assert res.status_code == 200
    assert res.json()["process_id"] == "job-123"


def test_process_status_and_stop(api, fake_vm, owned_container):
    user, ct, c = owned_container
    token = make_key(user)
    start = api(token).post(
        f"/api/v1/containers/{c.pk}/processes/", {"command": "sleep 1"}, format="json"
    )
    pid = start.json()["process_id"]
    st = api(token).get(f"/api/v1/containers/{c.pk}/processes/{pid}/")
    assert st.status_code == 200
    assert st.json()["status"] == "running"
    stop = api(token).delete(f"/api/v1/containers/{c.pk}/processes/{pid}/")
    assert stop.status_code == 200
    assert stop.json()["stopped"] is True


def test_files_put_and_get(api, fake_vm, owned_container):
    user, ct, c = owned_container
    token = make_key(user)
    put = api(token).put(
        f"/api/v1/containers/{c.pk}/files/",
        {"files": [{"path": "a.txt", "content": "hello"}]},
        format="json",
    )
    assert put.status_code == 200, put.content
    assert put.json()["written"] == 1

    get = api(token).get(f"/api/v1/containers/{c.pk}/files/?path=/app/a.txt")
    assert get.status_code == 200
    assert get.json()["content"] == "data"
    assert get.json()["found"] is True


def test_files_get_requires_path(api, fake_vm, owned_container):
    user, ct, c = owned_container
    token = make_key(user)
    res = api(token).get(f"/api/v1/containers/{c.pk}/files/")
    assert res.status_code == 400
    assert res.json()["error"]["code"] == "invalid_request"


def test_dirs(api, fake_vm, owned_container):
    user, ct, c = owned_container
    token = make_key(user)
    res = api(token).get(f"/api/v1/containers/{c.pk}/dirs/?path=/app")
    assert res.status_code == 200
    assert res.json()[0]["name"] == "f.txt"


def test_ports_includes_preview_path(api, fake_vm, owned_container):
    user, ct, c = owned_container
    token = make_key(user)
    res = api(token).get(f"/api/v1/containers/{c.pk}/ports/")
    assert res.status_code == 200
    row = res.json()[0]
    assert row["port"] == 8000
    assert row["preview_path"] == f"/api/containers/{c.pk}/preview/8000/"


def test_collaborator_can_list_and_exec_shared_container(api, fake_vm, owned_container):
    """A collaborator's API key can drive a container shared with them."""
    owner, ct, c = owned_container
    collab = create_user("api_collab")
    c.allowed_users.add(collab)
    token = make_key(collab)

    # It shows up in their listing...
    res = api(token).get("/api/v1/containers/")
    assert res.status_code == 200
    ids = {row["id"] for row in res.json()["results"]}
    assert c.pk in ids

    # ...and they can exec against it.
    ex = api(token).post(
        f"/api/v1/containers/{c.pk}/exec/", {"command": "echo hi"}, format="json"
    )
    assert ex.status_code == 200
    assert ex.json()["exit_code"] == 0


def test_collaborator_cannot_destroy_shared_container(api, fake_vm, owned_container):
    """Even with an admin-scoped key, a collaborator can't delete a container
    they don't own — destroy is gated on ownership, not just visibility."""
    owner, ct, c = owned_container
    collab = create_user("api_collab_del")
    c.allowed_users.add(collab)
    token = make_key(collab)  # read+exec+admin, but not the owner

    res = api(token).delete(f"/api/v1/containers/{c.pk}/")
    assert res.status_code == 404
    assert res.json()["error"]["code"] == "not_found"
    assert Container.objects.filter(pk=c.pk).exists()


def test_types_lists_allowed(api, fake_vm, user_with_type):
    user, ct = user_with_type
    token = make_key(user)
    res = api(token).get("/api/v1/types/")
    assert res.status_code == 200
    names = {t["name"] for t in res.json()}
    assert "small" in names
    assert res.json()[0]["credits_cost"] == 1
