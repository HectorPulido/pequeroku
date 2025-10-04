import os
import types
import pytest

import models
import qemu_manager.vm as qvm


class FakePopen:
    def __init__(self, args, stdout=None, stderr=None, preexec_fn=None):
        self.args = args
        self._rc = None
        # emulate a file-like with read() in failure path
        self.stdout = types.SimpleNamespace(read=lambda: b"")

    def poll(self):
        return self._rc

    def set_returncode(self, rc):
        self._rc = rc


def test_start_vm_success_x86(monkeypatch, tmp_path):
    workdir = str(tmp_path / "wd")
    os.makedirs(workdir, exist_ok=True)

    # Settings
    monkeypatch.setattr(qvm.settings, "VM_BASE_IMAGE", "/img/base.qcow2", raising=False)
    monkeypatch.setattr(qvm.settings, "VM_SSH_USER", "root", raising=False)
    monkeypatch.setattr(qvm.settings, "VM_SSH_PRIVKEY", "/keys/id_vm", raising=False)
    monkeypatch.setattr(qvm.settings, "VM_TIMEOUT_BOOT_S", 5, raising=False)
    # Disable ownership/perms adjustments
    monkeypatch.setattr(qvm.settings, "VM_RUN_AS_UID", None, raising=False)
    monkeypatch.setattr(qvm.settings, "VM_RUN_AS_GID", None, raising=False)

    # Platform and port
    monkeypatch.setattr(qvm.platform, "machine", lambda: "x86_64")
    monkeypatch.setattr(qvm, "pick_free_port", lambda: 2200)

    # Spy on qemu args builder
    captured = {}

    def fake_vm_x86_args(vcpus, mem_mib, console_log, port, overlay, seed_iso, pidfile):
        captured["x86_args"] = dict(
            vcpus=vcpus,
            mem_mib=mem_mib,
            console_log=console_log,
            port=port,
            overlay=overlay,
            seed_iso=seed_iso,
            pidfile=pidfile,
        )
        return ["QEMU-X86", "-dummy"]

    monkeypatch.setattr(qvm, "vm_qemu_x86_args", fake_vm_x86_args)

    # Spy on seed/overlay creation
    called = {"overlay": None, "seed": None}

    def fake_make_overlay(base_image, overlay, disk_gib):
        called["overlay"] = (base_image, overlay, disk_gib)

    def fake_make_seed_iso(seed_iso, user, pubkey, name):
        called["seed"] = (seed_iso, user, pubkey, name)

    monkeypatch.setattr(qvm, "make_overlay", fake_make_overlay)
    monkeypatch.setattr(qvm, "make_seed_iso", fake_make_seed_iso)

    # Popen and wait_ssh
    popen_calls = {}

    def fake_popen(args, stdout=None, stderr=None, preexec_fn=None):
        popen_calls["args"] = list(args)
        popen_calls["stdout"] = stdout
        popen_calls["stderr"] = stderr
        popen_calls["preexec_fn"] = preexec_fn
        return FakePopen(args, stdout, stderr, preexec_fn)

    monkeypatch.setattr(qvm.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(qvm, "wait_ssh", lambda **kwargs: True)

    # Ensure stale pidfile is cleared if present
    pidfile = os.path.join(workdir, "qemu.pid")
    with open(pidfile, "w", encoding="utf-8") as f:
        f.write("999999")

    # Force _pid_alive to False so stale pidfile is removed
    monkeypatch.setattr(qvm, "_pid_alive", lambda pid: False)

    # Run
    proc = qvm.start_vm(workdir, vcpus=2, mem_mib=1024, disk_gib=8, vm_id="vm-1")

    # Asserts
    overlay_path = os.path.join(workdir, "disk.qcow2")
    seed_iso_path = os.path.join(workdir, "seed.iso")
    console_log_path = os.path.join(workdir, "console.log")
    pidfile_path = os.path.join(workdir, "qemu.pid")

    # VMProc fields
    assert isinstance(proc, models.VMProc)
    assert proc.workdir == workdir
    assert proc.overlay == overlay_path
    assert proc.seed_iso == seed_iso_path
    assert proc.port_ssh == 2200
    assert proc.console_log == console_log_path
    assert proc.pidfile == pidfile_path

    # qemu args builder got correct inputs
    assert captured["x86_args"]["vcpus"] == 2
    assert captured["x86_args"]["mem_mib"] == 1024
    assert captured["x86_args"]["console_log"] == console_log_path
    assert captured["x86_args"]["port"] == 2200
    assert captured["x86_args"]["overlay"] == overlay_path
    assert captured["x86_args"]["seed_iso"] == seed_iso_path
    assert captured["x86_args"]["pidfile"] == pidfile_path

    # Overlay/seed creation arguments
    assert called["overlay"] == ("/img/base.qcow2", overlay_path, 8)
    assert called["seed"] == (
        seed_iso_path,
        "root",
        "/keys/id_vm.pub",
        os.path.basename(workdir),
    )

    # Popen called with our args and preexec_fn passed
    assert popen_calls["args"] == ["QEMU-X86", "-dummy"]

    # Stale pidfile removed by _clear_stale_pidfile
    assert not os.path.exists(pidfile)


def test_start_vm_timeout_shows_tail(monkeypatch, tmp_path):
    workdir = str(tmp_path / "wd_timeout")
    os.makedirs(workdir, exist_ok=True)

    # Settings
    monkeypatch.setattr(qvm.settings, "VM_BASE_IMAGE", "/img/base.qcow2", raising=False)
    monkeypatch.setattr(qvm.settings, "VM_SSH_USER", "root", raising=False)
    monkeypatch.setattr(qvm.settings, "VM_SSH_PRIVKEY", "/keys/id_vm", raising=False)
    monkeypatch.setattr(qvm.settings, "VM_TIMEOUT_BOOT_S", 2, raising=False)
    monkeypatch.setattr(qvm.settings, "VM_RUN_AS_UID", None, raising=False)
    monkeypatch.setattr(qvm.settings, "VM_RUN_AS_GID", None, raising=False)

    # Platform to x86
    monkeypatch.setattr(qvm.platform, "machine", lambda: "x86_64")
    monkeypatch.setattr(qvm, "pick_free_port", lambda: 2300)

    # Args, overlay/seed
    monkeypatch.setattr(qvm, "vm_qemu_x86_args", lambda *a, **k: ["QEMU-X86", "-dummy"])
    monkeypatch.setattr(qvm, "make_overlay", lambda *a, **k: None)
    monkeypatch.setattr(qvm, "make_seed_iso", lambda *a, **k: None)

    # Popen
    monkeypatch.setattr(qvm.subprocess, "Popen", lambda *a, **k: FakePopen(a[0]))

    # wait_ssh fails
    monkeypatch.setattr(
        qvm,
        "wait_ssh",
        lambda **kwargs: (_ for _ in ()).throw(TimeoutError("SSH timeout")),
    )

    # Capture tail subprocess.run call
    run_calls = {}

    def fake_run(args, capture_output=False, text=False, check=False):
        run_calls["args"] = args
        run_calls["capture_output"] = capture_output
        run_calls["text"] = text
        run_calls["check"] = check
        return types.SimpleNamespace(stdout="console tail")

    monkeypatch.setattr(qvm.subprocess, "run", fake_run)

    with pytest.raises(TimeoutError):
        _ = qvm.start_vm(workdir, vcpus=1, mem_mib=512, disk_gib=4, vm_id="vm-2")

    console_log_path = os.path.join(workdir, "console.log")
    assert run_calls["args"] == ["tail", "-n", "120", console_log_path]
    assert run_calls["capture_output"] is True
    assert run_calls["text"] is True
    assert run_calls["check"] is True


def test_start_vm_uses_arm64_args(monkeypatch, tmp_path):
    workdir = str(tmp_path / "wd_arm")
    os.makedirs(workdir, exist_ok=True)

    # Settings
    monkeypatch.setattr(qvm.settings, "VM_BASE_IMAGE", "/img/base.qcow2", raising=False)
    monkeypatch.setattr(qvm.settings, "VM_SSH_USER", "ubuntu", raising=False)
    monkeypatch.setattr(qvm.settings, "VM_SSH_PRIVKEY", "/keys/id_vm", raising=False)
    monkeypatch.setattr(qvm.settings, "VM_TIMEOUT_BOOT_S", 5, raising=False)
    monkeypatch.setattr(qvm.settings, "VM_RUN_AS_UID", None, raising=False)
    monkeypatch.setattr(qvm.settings, "VM_RUN_AS_GID", None, raising=False)

    # Platform arm64 triggers arm args
    monkeypatch.setattr(qvm.platform, "machine", lambda: "arm64")
    monkeypatch.setattr(qvm, "pick_free_port", lambda: 2400)

    # Spy arm64 args
    seen = {}

    def fake_vm_arm_args(vcpus, mem_mib, console_log, port, overlay, seed_iso, pidfile):
        seen["arm_args"] = dict(
            vcpus=vcpus,
            mem_mib=mem_mib,
            console_log=console_log,
            port=port,
            overlay=overlay,
            seed_iso=seed_iso,
            pidfile=pidfile,
        )
        return ["QEMU-ARM64", "-dummy"]

    monkeypatch.setattr(qvm, "vm_qemu_arm64_args", fake_vm_arm_args)

    # Overlay/seed, popen, wait_ssh
    monkeypatch.setattr(qvm, "make_overlay", lambda *a, **k: None)
    monkeypatch.setattr(qvm, "make_seed_iso", lambda *a, **k: None)
    monkeypatch.setattr(qvm.subprocess, "Popen", lambda *a, **k: FakePopen(a[0]))
    monkeypatch.setattr(qvm, "wait_ssh", lambda **kwargs: True)

    proc = qvm.start_vm(workdir, vcpus=3, mem_mib=1536, disk_gib=12, vm_id="vm-arm")

    overlay_path = os.path.join(workdir, "disk.qcow2")
    seed_iso_path = os.path.join(workdir, "seed.iso")
    console_log_path = os.path.join(workdir, "console.log")
    pidfile_path = os.path.join(workdir, "qemu.pid")

    assert seen["arm_args"]["vcpus"] == 3
    assert seen["arm_args"]["mem_mib"] == 1536
    assert seen["arm_args"]["console_log"] == console_log_path
    assert seen["arm_args"]["port"] == 2400
    assert seen["arm_args"]["overlay"] == overlay_path
    assert seen["arm_args"]["seed_iso"] == seed_iso_path
    assert seen["arm_args"]["pidfile"] == pidfile_path
    assert proc.port_ssh == 2400


def test_start_vm_ensures_paths_when_uid_gid_set(monkeypatch, tmp_path):
    workdir = str(tmp_path / "wd_uidgid")
    os.makedirs(workdir, exist_ok=True)

    # Set run as UID/GID so _ensure_paths_for_vm is invoked
    monkeypatch.setattr(qvm.settings, "VM_RUN_AS_UID", 1000, raising=False)
    monkeypatch.setattr(qvm.settings, "VM_RUN_AS_GID", 1000, raising=False)
    monkeypatch.setattr(qvm.settings, "VM_BASE_IMAGE", "/img/base.qcow2", raising=False)
    monkeypatch.setattr(qvm.settings, "VM_SSH_USER", "root", raising=False)
    monkeypatch.setattr(qvm.settings, "VM_SSH_PRIVKEY", "/keys/id_vm", raising=False)
    monkeypatch.setattr(qvm.settings, "VM_TIMEOUT_BOOT_S", 5, raising=False)

    monkeypatch.setattr(qvm.platform, "machine", lambda: "x86_64")
    monkeypatch.setattr(qvm, "pick_free_port", lambda: 2500)
    monkeypatch.setattr(qvm, "vm_qemu_x86_args", lambda *a, **k: ["QEMU-X86", "-dummy"])
    monkeypatch.setattr(qvm, "make_overlay", lambda *a, **k: None)
    monkeypatch.setattr(qvm, "make_seed_iso", lambda *a, **k: None)
    monkeypatch.setattr(qvm.subprocess, "Popen", lambda *a, **k: FakePopen(a[0]))
    monkeypatch.setattr(qvm, "wait_ssh", lambda **kwargs: True)

    seen = {}

    def fake_ensure_paths(run_uid, run_gid, workdir_arg, files):
        seen["ensure"] = dict(
            run_uid=run_uid, run_gid=run_gid, workdir=workdir_arg, files=list(files)
        )

    monkeypatch.setattr(qvm, "_ensure_paths_for_vm", fake_ensure_paths)

    _ = qvm.start_vm(workdir, vcpus=1, mem_mib=512, disk_gib=6, vm_id="vm-uid")

    console_log_path = os.path.join(workdir, "console.log")
    overlay_path = os.path.join(workdir, "disk.qcow2")
    seed_iso_path = os.path.join(workdir, "seed.iso")

    assert seen["ensure"]["run_uid"] == 1000
    assert seen["ensure"]["run_gid"] == 1000
    assert seen["ensure"]["workdir"] == workdir
    # Files list includes overlay, seed, console log
    assert overlay_path in seen["ensure"]["files"]
    assert seed_iso_path in seen["ensure"]["files"]
    assert console_log_path in seen["ensure"]["files"]
