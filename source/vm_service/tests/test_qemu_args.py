import qemu_manager.qemu_args as qemu_args


def _make_paths(tmp_path):
    console = str(tmp_path / "console.log")
    overlay = str(tmp_path / "disk.qcow2")
    seed = str(tmp_path / "seed.iso")
    pid = str(tmp_path / "qemu.pid")
    return console, overlay, seed, pid


def test_vm_qemu_x86_args_with_kvm(monkeypatch, tmp_path):
    console, overlay, seed, pid = _make_paths(tmp_path)

    # Force KVM present
    monkeypatch.setattr(
        qemu_args.os.path, "exists", lambda p: True if p == "/dev/kvm" else False
    )
    monkeypatch.setattr(
        qemu_args.settings, "VM_QEMU_BIN", "/usr/bin/qemu-system-x86_64", raising=False
    )

    args = qemu_args.vm_qemu_x86_args(
        vcpus=2,
        mem_mib=1024,
        console_log=console,
        port=2222,
        overlay=overlay,
        seed_iso=seed,
        pidfile=pid,
    )

    # First arg is the QEMU bin from settings
    assert args[0] == "/usr/bin/qemu-system-x86_64"
    # KVM flags should be present; TCG flags should not
    assert "-enable-kvm" in args
    assert "tcg,thread=multi" not in args
    # Serial file and port forward are included
    assert f"file:{console}" in args
    assert f"user,id=n0,hostfwd=tcp:127.0.0.1:2222-:22" in args
    # pidfile included
    assert "-pidfile" in args and pid in args


def test_vm_qemu_x86_args_without_kvm(monkeypatch, tmp_path):
    console, overlay, seed, pid = _make_paths(tmp_path)

    # Force no KVM
    monkeypatch.setattr(qemu_args.os.path, "exists", lambda p: False)
    monkeypatch.setattr(
        qemu_args.settings, "VM_QEMU_BIN", "/usr/bin/qemu-system-x86_64", raising=False
    )

    args = qemu_args.vm_qemu_x86_args(
        vcpus=4,
        mem_mib=2048,
        console_log=console,
        port=3333,
        overlay=overlay,
        seed_iso=seed,
        pidfile=None,
    )

    # Uses TCG acceleration
    assert "-accel" in args and "tcg,thread=multi" in args
    assert "-cpu" in args and "max" in args
    # Port forward is included
    assert f"user,id=n0,hostfwd=tcp:127.0.0.1:3333-:22" in args
    # No pidfile flag when pidfile is None
    assert "-pidfile" not in args


def test_vm_qemu_arm64_args_kvm(monkeypatch, tmp_path):
    console, overlay, seed, pid = _make_paths(tmp_path)

    # Mock firmware and qemu bin resolution
    monkeypatch.setattr(qemu_args, "_find_uefi_firmware_arm64", lambda: "/fw/uefi.fd")
    monkeypatch.setattr(
        qemu_args, "_resolve_qemu_bin_arm64", lambda: "/bin/qemu-system-aarch64"
    )

    # Platform and KVM available
    monkeypatch.setattr(qemu_args.platform, "machine", lambda: "arm64")
    monkeypatch.setattr(qemu_args.platform, "system", lambda: "Linux")
    monkeypatch.setattr(
        qemu_args.os.path, "exists", lambda p: True if p == "/dev/kvm" else False
    )

    args = qemu_args.vm_qemu_arm64_args(
        vcpus=2,
        mem_mib=1024,
        console_log=console,
        port=2222,
        overlay=overlay,
        seed_iso=seed,
        pidfile=pid,
    )

    # KVM branch uses taskset prefix and -accel kvm
    assert args[0:3] == ["taskset", "-c", "0-3"]
    assert "-accel" in args and "kvm" in args
    # BIOS/UEFI path is used
    assert "-bios" in args and "/fw/uefi.fd" in args
    # Port forward
    assert f"user,id=n0,hostfwd=tcp:127.0.0.1:2222-:22" in args
    # pidfile included
    assert "-pidfile" in args and pid in args


def test_vm_qemu_arm64_args_hvf_on_darwin(monkeypatch, tmp_path):
    console, overlay, seed, pid = _make_paths(tmp_path)

    monkeypatch.setattr(qemu_args, "_find_uefi_firmware_arm64", lambda: "/fw/uefi.fd")
    monkeypatch.setattr(
        qemu_args, "_resolve_qemu_bin_arm64", lambda: "/bin/qemu-system-aarch64"
    )

    # macOS HVF path, no KVM
    monkeypatch.setattr(qemu_args.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(qemu_args.platform, "machine", lambda: "arm64")
    monkeypatch.setattr(qemu_args.os.path, "exists", lambda p: False)

    args = qemu_args.vm_qemu_arm64_args(
        vcpus=2,
        mem_mib=512,
        console_log=console,
        port=2022,
        overlay=overlay,
        seed_iso=seed,
        pidfile=None,
    )

    # HVF acceleration present, no "taskset"
    assert "-accel" in args and "hvf" in args
    assert "taskset" not in args
    assert "kvm" not in args
    assert "-bios" in args and "/fw/uefi.fd" in args
    assert f"user,id=n0,hostfwd=tcp:127.0.0.1:2022-:22" in args


def test_vm_qemu_arm64_args_no_kvm_no_hvf(monkeypatch, tmp_path):
    console, overlay, seed, pid = _make_paths(tmp_path)

    monkeypatch.setattr(qemu_args, "_find_uefi_firmware_arm64", lambda: "/fw/uefi.fd")
    monkeypatch.setattr(
        qemu_args, "_resolve_qemu_bin_arm64", lambda: "/bin/qemu-system-aarch64"
    )

    # Linux without /dev/kvm (fallback to TCG)
    monkeypatch.setattr(qemu_args.platform, "system", lambda: "Linux")
    monkeypatch.setattr(qemu_args.platform, "machine", lambda: "arm64")
    monkeypatch.setattr(qemu_args.os.path, "exists", lambda p: False)

    args = qemu_args.vm_qemu_arm64_args(
        vcpus=1,
        mem_mib=256,
        console_log=console,
        port=2200,
        overlay=overlay,
        seed_iso=seed,
        pidfile=None,
    )

    assert "-accel" in args and "tcg,thread=multi" in args
    assert "-cpu" in args and "max" in args
    assert "taskset" not in args
    assert f"user,id=n0,hostfwd=tcp:127.0.0.1:2200-:22" in args


def test_find_uefi_firmware_arm64_override(monkeypatch, tmp_path):
    # If override is set and exists, it should be returned
    override = "/custom/uefi.fd"

    def fake_exists(path):
        return path == override

    monkeypatch.setattr(qemu_args.settings, "VM_UEFI_ARM64", override, raising=False)
    monkeypatch.setattr(qemu_args.os.path, "exists", fake_exists)

    found = qemu_args._find_uefi_firmware_arm64()
    assert found == override


def test_find_uefi_firmware_arm64_datadir_fallback(monkeypatch):
    # No override and no known candidates; fallback to datadir candidates
    monkeypatch.setattr(qemu_args.settings, "VM_UEFI_ARM64", None, raising=False)

    # Force no known candidate path exists except from datadir
    def fake_exists(path):
        # Only the datadir candidate exists
        return path == "/share/qemu/edk2-aarch64-code.fd"

    monkeypatch.setattr(qemu_args.os.path, "exists", fake_exists)
    monkeypatch.setattr(
        qemu_args, "_resolve_qemu_bin_arm64", lambda: "/bin/qemu-system-aarch64"
    )
    monkeypatch.setattr(qemu_args, "_qemu_datadir", lambda q: "/share/qemu")

    found = qemu_args._find_uefi_firmware_arm64()
    assert found == "/share/qemu/edk2-aarch64-code.fd"
