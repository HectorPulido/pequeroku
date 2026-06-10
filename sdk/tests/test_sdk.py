import json

import httpx
import pytest

from pequeroku import PequeRoku, PequeRokuError, RunResult


def make(handler):
    return PequeRoku(
        api_key="pk_a_b",
        base_url="https://host",
        transport=httpx.MockTransport(handler),
    )


def test_run_sync_returns_runresult():
    def handler(request):
        body = json.loads(request.read())
        assert body["command"] == "echo hi"
        assert request.url.path == "/api/v1/runs/"
        return httpx.Response(
            200,
            json={"id": "r1", "status": "succeeded", "stdout": "hi\n", "exit_code": 0},
        )

    r = make(handler).run("echo hi")
    assert isinstance(r, RunResult)
    assert r.ok
    assert r.stdout == "hi\n"


def test_run_async_sets_flag_and_is_pending():
    def handler(request):
        body = json.loads(request.read())
        assert body["async"] is True
        return httpx.Response(202, json={"id": "r2", "status": "pending"})

    r = make(handler).run("sleep 5", wait=False)
    assert r.status == "pending"
    assert not r.ok


def test_create_container_with_ttl():
    def handler(request):
        body = json.loads(request.read())
        assert body == {"type": "small", "ttl_seconds": 60}
        return httpx.Response(201, json={"id": 3, "name": "x", "status": "creating"})

    out = make(handler).create_container("small", ttl_seconds=60)
    assert out["id"] == 3


def test_list_containers_unwraps_pagination():
    def handler(request):
        return httpx.Response(200, json={"results": [{"id": 1}], "count": 1})

    assert make(handler).list_containers() == [{"id": 1}]


def test_exec_passes_timeout():
    def handler(request):
        body = json.loads(request.read())
        assert body["timeout"] == 30
        return httpx.Response(200, json={"stdout": "ok", "exit_code": 0})

    out = make(handler).exec(1, "ls", timeout=30)
    assert out["exit_code"] == 0


def test_error_envelope_raises():
    def handler(request):
        return httpx.Response(
            409, json={"error": {"code": "machine_not_running", "message": "off"}}
        )

    with pytest.raises(PequeRokuError) as e:
        make(handler).exec(1, "ls")
    assert e.value.code == "machine_not_running"


def test_wait_run_polls_until_done():
    states = iter(["running", "running", "succeeded"])

    def handler(request):
        return httpx.Response(200, json={"id": "r", "status": next(states)})

    r = make(handler).wait_run("r", poll_interval=0, max_wait=5)
    assert r.status == "succeeded"
