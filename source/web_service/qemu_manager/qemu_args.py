import os
import platform
import glob
import shutil
import subprocess
from typing import List, Optional

from django.conf import settings


def _first_existing(paths) -> Optional[str]:
    """Return the first path that exists from a list of candidates."""
    for p in paths:
        if p and os.path.exists(p):
            return p
    return None


def _qemu_datadir(qemu_bin: str) -> Optional[str]:
    """
    Try to infer QEMU's datadir (where firmware files usually live).
    Heuristic: parse `qemu-system-aarch64 -help` or `-version` for paths containing 'share/qemu'.
    """
    try:
        out = subprocess.run(
            [qemu_bin, "-help"], capture_output=True, text=True, check=True
        ).stdout
        for line in out.splitlines():
            if "/share/qemu" in line:
                start = line.find("/")
                cand = line[start:].strip()
                if os.path.isfile(cand):
                    cand = os.path.dirname(cand)
                if os.path.isdir(cand):
                    return cand
    except Exception as e:
        print("Error getting qemu_bin help", e)
    try:
        out = subprocess.run(
            [qemu_bin, "-version"], capture_output=True, text=True, check=True
        ).stdout
        for tok in out.split():
            if tok.endswith("/share/qemu") and os.path.isdir(tok):
                return tok
    except Exception as e:
        print("Error getting qemu_bin version", e)
    return None


def _resolve_qemu_bin_arm64() -> str:
    """Resolve qemu-system-aarch64 binary path for ARM64 hosts."""
    if settings.VM_QEMU_BIN:
        return settings.VM_QEMU_BIN
    cand = shutil.which("qemu-system-aarch64")
    if cand:
        return cand
    for p in (
        "/opt/homebrew/opt/qemu/bin/qemu-system-aarch64",
        "/usr/local/opt/qemu/bin/qemu-system-aarch64",
        "/opt/homebrew/bin/qemu-system-aarch64",
        "/usr/local/bin/qemu-system-aarch64",
    ):
        if os.path.exists(p):
            return p
    return "qemu-system-aarch64"


def _find_uefi_firmware_arm64() -> str:
    """
    Locate UEFI firmware for QEMU ARM64.

    Priority:
      1. Explicit override via settings.VM_UEFI_ARM64
      2. Known distro-specific paths (Ubuntu, Fedora, Arch, Homebrew, MacPorts)
      3. Paths discovered from QEMU's datadir
    """
    # 1) explicit override
    override = getattr(settings, "VM_UEFI_ARM64", None)
    if override and os.path.exists(override):
        return override

    # 2) known candidates
    candidates = [
        "/usr/share/qemu-efi-aarch64/QEMU_EFI.fd",  # Ubuntu/Debian
        "/usr/share/edk2/aarch64/QEMU_EFI.fd",  # Fedora/RHEL
        "/usr/share/AAVMF/AAVMF_CODE.fd",  # AAVMF
        "/usr/share/qemu/edk2-aarch64-code.fd",  # Generic
        "/opt/homebrew/share/qemu/edk2-aarch64-code.fd",  # Homebrew
        "/usr/local/share/qemu/edk2-aarch64-code.fd",
        "/opt/local/share/qemu/edk2-aarch64-code.fd",  # MacPorts
    ]

    # Add Homebrew Cellar versioned paths
    hb_globs = [
        "/opt/homebrew/Cellar/qemu/*/share/qemu/edk2-aarch64-code.fd",
        "/usr/local/Cellar/qemu/*/share/qemu/edk2-aarch64-code.fd",
    ]
    for pattern in hb_globs:
        matches = sorted(glob.glob(pattern), reverse=True)
        candidates[:0] = matches

    found = _first_existing(candidates)
    if found:
        return found

    # 3) fallback: QEMU datadir
    qemu_bin = _resolve_qemu_bin_arm64()
    datadir = _qemu_datadir(qemu_bin)
    if datadir:
        dd_candidates = [
            os.path.join(datadir, "edk2-aarch64-code.fd"),
            os.path.join(datadir, "QEMU_EFI.fd"),
        ]
        found = _first_existing(dd_candidates)
        if found:
            return found

    raise FileNotFoundError(
        "UEFI firmware for ARM64 not found. Please install it "
        "(Ubuntu: qemu-efi-aarch64, Fedora: edk2-aarch64, Arch: edk2-armvirt, "
        "macOS: brew install qemu) or set settings.VM_UEFI_ARM64 explicitly."
    )


def _no_kvm(
    arm_64_bin,
    vcpus,
    mem_mib,
    console_log,
    uefi,
    port,
    overlay,
    seed_iso,
    pidfile: Optional[str],
):
    args = []
    args += [
        arm_64_bin,
        "-accel",
        "tcg,thread=multi",
        "-cpu",
        "max",
        "-machine",
        "virt",
        "-smp",
        str(vcpus),
        "-m",
        str(mem_mib),
        "-bios",
        uefi,
        "-nographic",
        "-serial",
        f"file:{console_log}",
        "-netdev",
        f"user,id=n0,hostfwd=tcp:127.0.0.1:{port}-:22",
        "-device",
        "virtio-net-device,netdev=n0",
        "-drive",
        f"if=none,format=qcow2,file={overlay},id=vd0",
        "-device",
        "virtio-blk-device,drive=vd0",
    ]
    if pidfile:
        args += ["-pidfile", pidfile]
    if seed_iso:
        args += [
            "-drive",
            f"if=none,format=raw,readonly=on,file={seed_iso},id=cidata",
            "-device",
            "virtio-blk-device,drive=cidata",
        ]
    return args


def _kvm(
    arm_64_bin,
    vcpus,
    mem_mib,
    console_log,
    uefi,
    port,
    overlay,
    seed_iso,
    pidfile: Optional[str],
):
    args = []
    args += [
        "taskset",
        "-c",
        "0-3",
        arm_64_bin,
        "-accel",
        "kvm",
        "-cpu",
        "host",
        "-M",
        "virt-7.1,gic-version=3,its=off",
        "-smp",
        str(vcpus),
        "-m",
        str(mem_mib),
        "-nographic",
        "-serial",
        f"file:{console_log}",
        "-bios",
        uefi,
        "-nodefaults",
        "-no-user-config",
        "-netdev",
        f"user,id=n0,hostfwd=tcp:127.0.0.1:{port}-:22",
        "-device",
        "virtio-net-device,netdev=n0",
        "-device",
        "virtio-scsi-device,id=scsi0",
        "-drive",
        f"if=none,format=qcow2,file={overlay},id=vd0",
        "-device",
        "scsi-hd,drive=vd0,bus=scsi0.0",
    ]
    if pidfile:
        args += ["-pidfile", pidfile]
    if seed_iso:
        args += [
            "-drive",
            f"if=none,format=raw,readonly=on,file={seed_iso},id=cidata",
            "-device",
            "scsi-cd,drive=cidata,bus=scsi0.0",
        ]
    return args


def _hvf(
    arm_64_bin,
    vcpus,
    mem_mib,
    console_log,
    uefi,
    port,
    overlay,
    seed_iso,
    pidfile: Optional[str],
):
    # For mac
    args = []
    args += [
        arm_64_bin,
        "-accel",
        "hvf",
        "-cpu",
        "max",
        "-machine",
        "virt",
        "-smp",
        str(vcpus),
        "-m",
        str(mem_mib),
        "-bios",
        uefi,
        "-nographic",
        "-serial",
        f"file:{console_log}",
        "-netdev",
        f"user,id=n0,hostfwd=tcp:127.0.0.1:{port}-:22",
        "-device",
        "virtio-net-device,netdev=n0",
        "-drive",
        f"if=none,format=qcow2,file={overlay},id=vd0",
        "-device",
        "virtio-blk-device,drive=vd0",
    ]
    if pidfile:
        args += ["-pidfile", pidfile]
    if seed_iso:
        args += [
            "-drive",
            f"if=none,format=raw,readonly=on,file={seed_iso},id=cidata",
            "-device",
            "virtio-blk-device,drive=cidata",
        ]
    return args


def _vm_qemu_arm64_args(
    vcpus: int,
    mem_mib: int,
    console_log: str,
    port: int,
    overlay: str,
    seed_iso: str,
    pidfile: Optional[str],
) -> List[str]:
    """
    Build QEMU args for ARM64 hosts, preserving original accel branches and device layout.
    """
    uefi = _find_uefi_firmware_arm64()
    if uefi is None:
        raise FileNotFoundError("Not valid UEFI installed")

    arm_64_bin = _resolve_qemu_bin_arm64()
    if not bool(arm_64_bin):
        raise FileNotFoundError("Not valid QEMU bin for arm64")

    args: list = []

    use_kvm = os.path.exists("/dev/kvm") and platform.machine() in ("aarch64", "arm64")
    use_hvf = platform.system() == "Darwin"

    print(
        f"[qemu] Using bin: {arm_64_bin}  using uefi: {uefi}  kvm:{use_kvm}  hvf:{use_hvf}"
    )

    if use_kvm:
        print("Using KVM")
        args += _kvm(
            arm_64_bin,
            vcpus,
            mem_mib,
            console_log,
            uefi,
            port,
            overlay,
            seed_iso,
            pidfile,
        )
    elif use_hvf:
        print("Using HVF")
        args += _hvf(
            arm_64_bin,
            vcpus,
            mem_mib,
            console_log,
            uefi,
            port,
            overlay,
            seed_iso,
            pidfile,
        )
    else:
        print("Not using KVM")
        args += _no_kvm(
            arm_64_bin,
            vcpus,
            mem_mib,
            console_log,
            uefi,
            port,
            overlay,
            seed_iso,
            pidfile,
        )
    print(args)
    return args


def _vm_qemu_x86_args(
    vcpus: int,
    mem_mib: int,
    console_log: str,
    port: int,
    overlay: str,
    seed_iso: str,
    pidfile: Optional[str],
) -> List[str]:
    """
    Build QEMU args for x86 hosts; writes serial output to console_log.
    """
    args: List[str] = [settings.VM_QEMU_BIN]
    if os.path.exists("/dev/kvm"):
        print("Using KVM")
        args += ["-enable-kvm", "-machine", "accel=kvm,type=q35", "-cpu", "host"]
    else:
        print("Not using KVM")
        args += ["-machine", "type=q35", "-accel", "tcg,thread=multi", "-cpu", "max"]

    args += [
        "-smp",
        str(vcpus),
        "-m",
        str(mem_mib),
        "-display",
        "none",
        "-serial",
        f"file:{console_log}",
        "-device",
        "virtio-net-pci,netdev=n0",
        "-netdev",
        f"user,id=n0,hostfwd=tcp:127.0.0.1:{port}-:22",
        "-device",
        "virtio-rng-pci",
        "-drive",
        f"if=virtio,format=qcow2,file={overlay}",
        "-drive",
        f"if=virtio,format=raw,readonly=on,file={seed_iso}",
    ]

    if pidfile:
        args += ["-pidfile", pidfile]
    return args
