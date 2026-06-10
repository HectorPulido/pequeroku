import json

import qemu_manager.seed as seed

GOLDEN_BYTES = 10 * 1024**3


def _fake_run_factory(calls):
    """subprocess.run fake: answers `qemu-img info` with a 10 GiB golden."""

    def fake_run(args, **kwargs):
        calls.append(list(args))
        if "info" in args:
            return type(
                "R", (), {"stdout": json.dumps({"virtual-size": GOLDEN_BYTES})}
            )()
        return type("R", (), {"returncode": 0})()

    return fake_run


def _create_size_arg(calls):
    create = next(c for c in calls if "create" in c)
    return create[-1]  # size is the last positional arg to qemu-img create


def test_make_overlay_floors_smaller_request_to_backing(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(seed.subprocess, "run", _fake_run_factory(calls))

    overlay = str(tmp_path / "disk.qcow2")  # does not exist yet
    seed.make_overlay("/base/golden.qcow2", overlay, disk_gib=5)

    # 5 GiB request < 10 GiB golden -> overlay floored to the golden size so the
    # guest's root partition (PARTUUID) is not truncated.
    assert _create_size_arg(calls) == str(GOLDEN_BYTES)


def test_make_overlay_keeps_larger_request(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(seed.subprocess, "run", _fake_run_factory(calls))

    overlay = str(tmp_path / "disk.qcow2")
    seed.make_overlay("/base/golden.qcow2", overlay, disk_gib=25)

    # 25 GiB > 10 GiB golden -> request kept as-is (extra space grows later).
    assert _create_size_arg(calls) == str(25 * 1024**3)


def test_make_overlay_noop_when_overlay_exists(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(seed.subprocess, "run", _fake_run_factory(calls))

    overlay = tmp_path / "disk.qcow2"
    overlay.write_text("already here")
    seed.make_overlay("/base/golden.qcow2", str(overlay), disk_gib=5)

    assert calls == []  # nothing created, nothing inspected
