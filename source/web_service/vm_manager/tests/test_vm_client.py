import pytest
import requests

from vm_manager.vm_client import (
    VMServiceClient,
    VMCreate,
    VMEnsure,
    VMAction,
    VMUploadFiles,
    VMFile,
    VMPaths,
    VMPath,
    SearchRequest,
)
from vm_manager.test_utils import create_node

pytestmark = pytest.mark.django_db


class FakeResponse:
    def __init__(
        self,
        *,
        status_code=200,
        ok=True,
        reason="OK",
        json_data=None,
        text="",
        content=b"OK",
        headers=None,
    ):
        self.status_code = status_code
        self.ok = ok
        self.reason = reason
        self._json_data = json_data
        self.text = text
        self.content = content
        self.headers = headers or {}

    def json(self):
        if self._json_data is not None:
            return self._json_data
        raise ValueError("No JSON data")


class FakeSession:
    def __init__(self):
        self.calls = (
            []
        )  # list of dicts with method, url, json, headers, timeout, params
        self.queue = []  # responses to return in order
        self.last_url = None
        self.last_json = None
        self.last_headers = None
        self.last_timeout = None
        self.last_params = None

    def _record(
        self, method, url, *, json=None, headers=None, timeout=None, params=None
    ):
        self.last_url = url
        self.last_json = json
        self.last_headers = headers
        self.last_timeout = timeout
        self.last_params = params
        self.calls.append(
            {
                "method": method,
                "url": url,
                "json": json,
                "headers": headers,
                "timeout": timeout,
                "params": params,
            }
        )

    def _next_response(self):
        if self.queue:
            return self.queue.pop(0)
        return FakeResponse()

    def get(self, url, *, headers=None, timeout=None, params=None):
        self._record("GET", url, headers=headers, timeout=timeout, params=params)
        return self._next_response()

    def post(self, url, *, json=None, headers=None, timeout=None, params=None):
        self._record(
            "POST", url, json=json, headers=headers, timeout=timeout, params=params
        )
        return self._next_response()

    def delete(self, url, *, headers=None, timeout=None, params=None):
        self._record("DELETE", url, headers=headers, timeout=timeout, params=params)
        return self._next_response()


def test_url_builder_strips_trailing_slash():
    node = create_node(host="http://host:9999/")
    client = VMServiceClient(node=node, session=FakeSession())

    assert client._url("/vms") == "http://host:9999/vms"
    assert client._url("/health") == "http://host:9999/health"


def test_create_vm_posts_filtered_payload_and_handles_json():
    node = create_node()
    session = FakeSession()
    # Response with JSON body; ensure content is non-empty so _handle() calls .json()
    session.queue.append(
        FakeResponse(json_data={"id": "vm-1"}, content=b'{"id":"vm-1"}')
    )

    client = VMServiceClient(node=node, session=session)
    payload = VMCreate(vcpus=2, mem_mib=512, disk_gib=10, base_image=None)
    res = client.create_vm(payload)

    assert res == {"id": "vm-1"}
    assert session.last_url.endswith("/vms")
    # Ensure only non-None fields posted
    assert session.last_json == {"vcpus": 2, "mem_mib": 512, "disk_gib": 10}
    # Headers set by client
    assert session.last_headers.get("Accept") == "application/json"
    assert session.last_headers.get("Content-Type") == "application/json"


def test_get_vm_returns_json():
    node = create_node()
    session = FakeSession()
    session.queue.append(
        FakeResponse(json_data={"id": "abc", "state": "running"}, content=b"ok")
    )

    client = VMServiceClient(node=node, session=session)
    data = client.get_vm("abc")

    assert data["id"] == "abc"
    assert data["state"] == "running"
    assert session.last_url.endswith("/vms/abc")


def test_get_vms_joins_ids_in_path():
    node = create_node()
    session = FakeSession()
    session.queue.append(
        FakeResponse(
            json_data={
                "abc": {"id": "abc", "state": "running"},
                "def": {"id": "def", "state": "stopped"},
            },
            content=b"ok",
        )
    )
    client = VMServiceClient(node=node, session=session)
    data = client.get_vms(["abc", "def"])

    assert "abc" in data and "def" in data
    assert session.last_url.endswith("/vms/list/abc,def")


def test_upload_files_posts_asdict():
    node = create_node()
    session = FakeSession()
    session.queue.append(FakeResponse(json_data={"ok": True}, content=b"ok"))

    client = VMServiceClient(node=node, session=session)
    files = [
        VMFile(path="a.txt", text="A"),
        VMFile(path="b.txt", text="B", mode=0o600),
    ]
    payload = VMUploadFiles(files=files, dest_path="/app", clean=True)
    res = client.upload_files("vm-1", payload)

    assert res == {"ok": True}
    assert session.last_url.endswith("/vms/vm-1/upload-files")
    # Should be dataclass asdict()
    assert isinstance(session.last_json, dict)
    assert session.last_json["dest_path"] == "/app"
    assert session.last_json["clean"] is True
    assert isinstance(session.last_json["files"], list)
    assert session.last_json["files"][0]["path"] == "a.txt"


def test_upload_files_blob_posts_raw_dict():
    node = create_node()
    session = FakeSession()
    session.queue.append(
        FakeResponse(json_data={"ok": True, "count": 2}, content=b"ok")
    )

    client = VMServiceClient(node=node, session=session)
    payload = {
        "dest_path": "/data",
        "clean": False,
        "files": [{"path": "x.bin", "content_b64": "AAA="}],
    }
    res = client.upload_files_blob("vm-xyz", payload)

    assert res["ok"] is True
    assert session.last_url.endswith("/vms/vm-xyz/upload-files")
    # Ensure dict passed unchanged
    assert session.last_json == payload


def test_error_response_raises_http_error_and_calls_set_healthy(monkeypatch):
    node = create_node()
    session = FakeSession()
    # Return an HTTP 500 with JSON body
    session.queue.append(
        FakeResponse(
            ok=False,
            status_code=500,
            reason="Server Error",
            json_data={"detail": "boom"},
            text="boom",
            content=b"err",
        )
    )
    client = VMServiceClient(node=node, session=session)

    called = {"ok": False, "value": None}

    def fake_set_healthy(val):
        called["ok"] = True
        called["value"] = val

    monkeypatch.setattr(client, "set_healthy", fake_set_healthy)

    with pytest.raises(requests.HTTPError):
        client.get_vm("bad-id")

    # Should mark unhealthy on error path
    assert called["ok"] is True
    assert called["value"] is False


def test_download_file_returns_raw_response_object():
    node = create_node()
    session = FakeSession()
    resp = FakeResponse(
        status_code=200,
        ok=True,
        reason="OK",
        content=b"FILEDATA",
        headers={"Content-Type": "application/octet-stream"},
    )
    session.queue.append(resp)

    client = VMServiceClient(node=node, session=session)
    r = client.download_file("vm-1", "/app/file.txt")

    # Should not pass through _handle (should return the actual response)
    assert r is resp
    assert session.last_params == {"path": "/app/file.txt"}
    assert session.last_url.endswith("/vms/vm-1/download-file")


def test_download_folder_returns_raw_response_object():
    node = create_node()
    session = FakeSession()
    resp = FakeResponse(
        status_code=200,
        ok=True,
        reason="OK",
        content=b"ZIPDATA",
        headers={"Content-Type": "application/zip"},
    )
    session.queue.append(resp)

    client = VMServiceClient(node=node, session=session)
    r = client.download_folder("vm-1", root="/app/src", prefer_fmt="zip")

    assert r is resp
    assert session.last_params == {"root": "/app/src", "prefer_fmt": "zip"}
    assert session.last_url.endswith("/vms/vm-1/download-folder")


def test_headers_include_auth_token_when_present():
    node = create_node()
    node.auth_token = "secret-token"
    node.save(update_fields=["auth_token"])

    session = FakeSession()
    session.queue.append(FakeResponse(json_data={"id": "vm-2"}, content=b"ok"))

    client = VMServiceClient(node=node, session=session)

    _ = client.create_vm(VMCreate(vcpus=1, mem_mib=128, disk_gib=2))
    assert session.last_headers.get("Authorization") == "Bearer secret-token"
    assert session.last_headers.get("Accept") == "application/json"
    assert session.last_headers.get("Content-Type") == "application/json"


def test_action_vm_posts_action_payload_and_returns_json():
    node = create_node()
    session = FakeSession()
    session.queue.append(FakeResponse(json_data={"status": "ok"}, content=b"ok"))

    client = VMServiceClient(node=node, session=session)
    res = client.action_vm("vm-5", VMAction(action="reboot", cleanup_disks=False))

    assert res == {"status": "ok"}
    assert session.last_url.endswith("/vms/vm-5/actions")
    assert session.last_json == {"action": "reboot", "cleanup_disks": False}


def test_proxy_posts_payload_and_returns_envelope():
    node = create_node()
    session = FakeSession()
    session.queue.append(
        FakeResponse(
            json_data={"ok": True, "status": 200, "headers": [], "body_b64": "aGk="},
            content=b"ok",
        )
    )

    client = VMServiceClient(node=node, session=session)
    env = client.proxy(
        "vm-1",
        {
            "target_port": 8000,
            "method": "GET",
            "path": "/",
            "headers": {},
            "timeout": 30,
        },
    )

    assert env["ok"] is True
    assert session.last_url.endswith("/vms/vm-1/proxy")
    assert session.last_json["target_port"] == 8000
    assert session.last_json["method"] == "GET"


def test_listening_ports_gets_list_from_node():
    node = create_node()
    session = FakeSession()
    session.queue.append(
        FakeResponse(
            json_data=[
                {"port": 3000, "address": "127.0.0.1", "process": "node", "pid": 12},
                {"port": 8000, "address": "0.0.0.0", "process": "python3", "pid": 34},
            ],
            content=b"ok",
        )
    )

    client = VMServiceClient(node=node, session=session)
    data = client.listening_ports("vm-9")

    assert isinstance(data, list)
    assert {p["port"] for p in data} == {3000, 8000}
    assert session.last_url.endswith("/vms/vm-9/listening-ports")


# --------------------------------------------------------------------------- #
# _handle: 204 / empty body returns None
# --------------------------------------------------------------------------- #
def test_handle_no_content_returns_none():
    node = create_node()
    session = FakeSession()
    session.queue.append(FakeResponse(status_code=204, content=b""))
    client = VMServiceClient(node=node, session=session)
    assert client.delete_vm("vm-1") is None
    assert session.calls[0]["method"] == "DELETE"


# --------------------------------------------------------------------------- #
# remaining GET/POST endpoints
# --------------------------------------------------------------------------- #
def test_list_vms_and_ensure_vm():
    node = create_node()
    session = FakeSession()
    session.queue.append(FakeResponse(json_data=[{"id": "a"}], content=b"ok"))
    session.queue.append(FakeResponse(json_data={"id": "a"}, content=b"ok"))
    client = VMServiceClient(node=node, session=session)

    assert client.list_vms() == [{"id": "a"}]
    assert session.last_url.endswith("/vms")

    client.ensure_vm("a", VMEnsure(vcpus=1, mem_mib=128, disk_gib=2, base_image=None))
    assert session.last_url.endswith("/vms/a/ensure")
    assert session.last_json == {"vcpus": 1, "mem_mib": 128, "disk_gib": 2}


def test_get_health_and_tail_console_and_statistics():
    node = create_node()
    session = FakeSession()
    session.queue.append(FakeResponse(json_data={"ok": "True"}, content=b"ok"))
    session.queue.append(FakeResponse(json_data={"log": "boot"}, content=b"ok"))
    session.queue.append(FakeResponse(json_data={"cpu": 1.0}, content=b"ok"))
    client = VMServiceClient(node=node, session=session)

    h = client.get_health()
    assert h.json() == {"ok": "True"} and session.last_url.endswith("/health")

    client.tail_console("vm-1", lines=10)
    assert session.last_url.endswith("/vms/vm-1/console/tail")
    assert session.last_params == {"lines": 10}

    client.statistics("vm-1")
    assert session.last_url.endswith("/metrics/vm-1")


def test_execute_sh_widens_timeout_when_given():
    node = create_node()
    session = FakeSession()
    session.queue.append(FakeResponse(json_data={"ok": True}, content=b"ok"))
    session.queue.append(FakeResponse(json_data={"ok": True}, content=b"ok"))
    client = VMServiceClient(node=node, session=session)

    client.execute_sh("vm-1", "echo hi")  # no timeout -> default http timeout
    assert session.last_json == {"command": "echo hi"}
    assert session.last_timeout == client.timeout

    client.execute_sh("vm-1", "make", timeout=60)
    assert session.last_json == {"command": "make", "timeout": 60}
    assert session.last_timeout == max(client.timeout, 70.0)  # widened


def test_process_lifecycle_endpoints():
    node = create_node()
    session = FakeSession()
    for _ in range(4):
        session.queue.append(FakeResponse(json_data={"ok": True}, content=b"ok"))
    client = VMServiceClient(node=node, session=session)

    client.start_process("vm-1", "python3 main.py")
    assert session.last_url.endswith("/vms/vm-1/start-process")

    # status with delta polling + server-side wait widens the http timeout
    client.process_status("vm-1", "j1", lines=20, since_bytes=100, wait=120)
    assert session.last_url.endswith("/vms/vm-1/process-status")
    assert session.last_json == {"job_id": "j1", "lines": 20, "since_bytes": 100, "wait": 120}
    assert session.last_timeout == max(client.timeout, 145.0)

    # plain status: no since_bytes / wait keys
    client.process_status("vm-1", "j1")
    assert session.last_json == {"job_id": "j1", "lines": 80}

    client.stop_process("vm-1", "j1")
    assert session.last_url.endswith("/vms/vm-1/stop-process")
    assert session.last_json == {"job_id": "j1"}


def test_fs_endpoints_list_read_create_search():
    node = create_node()
    session = FakeSession()
    for _ in range(5):
        session.queue.append(FakeResponse(json_data={"ok": True}, content=b"ok"))
    client = VMServiceClient(node=node, session=session)

    # list_dirs accepts a VMPaths...
    client.list_dirs("vm-1", VMPaths(paths=["/app"], depth=2))
    assert session.last_json == {"paths": ["/app"], "depth": 2}
    # ...or a bare list (wrapped with depth=1)
    client.list_dirs("vm-1", ["/app", "/tmp"])
    assert session.last_json == {"paths": ["/app", "/tmp"], "depth": 1}

    # read_file accepts a str...
    client.read_file("vm-1", "/app/a.py")
    assert session.last_json == {"path": "/app/a.py"}
    # ...or a VMPath
    client.create_dir("vm-1", VMPath(path="/app/new"))
    assert session.last_url.endswith("/vms/vm-1/create-dir")
    assert session.last_json == {"path": "/app/new"}

    client.search("vm-1", SearchRequest(pattern="TODO", root="/app"))
    assert session.last_url.endswith("/vms/vm-1/search")
    assert session.last_json["pattern"] == "TODO" and session.last_json["root"] == "/app"


# --------------------------------------------------------------------------- #
# set_healthy (blocking mode persists node health)
# --------------------------------------------------------------------------- #
def test_set_healthy_noop_when_not_blocking():
    node = create_node()
    client = VMServiceClient(node=node, session=FakeSession(), blocking=False)
    client.set_healthy(False)  # must be a no-op and not touch the node
    # healthy unchanged from the factory default (True)
    assert node.healthy is True


@pytest.mark.django_db
def test_set_healthy_true_marks_node_healthy():
    node = create_node(healthy=False)
    client = VMServiceClient(node=node, session=FakeSession(), blocking=True)
    client.set_healthy(True)
    node.refresh_from_db()
    assert node.healthy is True and node.heartbeat_at is not None


@pytest.mark.django_db
def test_set_healthy_false_consults_health_endpoint():
    node = create_node(healthy=True)
    session = FakeSession()
    # /health says ok -> node stays healthy
    session.queue.append(FakeResponse(json_data={"ok": "True"}, content=b"ok"))
    client = VMServiceClient(node=node, session=session, blocking=True)
    client.set_healthy(False)
    node.refresh_from_db()
    assert node.healthy is True


@pytest.mark.django_db
def test_set_healthy_false_marks_unhealthy_on_bad_health():
    node = create_node(healthy=True)
    session = FakeSession()
    # /health returns not-ok -> node marked unhealthy
    session.queue.append(FakeResponse(ok=False, status_code=503, content=b"x",
                                      json_data={"ok": "False"}))
    client = VMServiceClient(node=node, session=session, blocking=True)
    client.set_healthy(False)
    node.refresh_from_db()
    assert node.healthy is False


@pytest.mark.django_db
def test_set_healthy_false_marks_unhealthy_on_exception():
    node = create_node(healthy=True)
    session = FakeSession()
    # /health body is not JSON -> .json() raises -> bare except -> unhealthy
    session.queue.append(FakeResponse(content=b"not-json"))
    client = VMServiceClient(node=node, session=session, blocking=True)
    client.set_healthy(False)
    node.refresh_from_db()
    assert node.healthy is False
