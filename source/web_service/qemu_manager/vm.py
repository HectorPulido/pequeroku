import os
import platform
import subprocess
from django.conf import settings

from .models import VMProc
from .seed import _make_overlay, _make_seed_iso
from .ports import _pick_free_port
from .qemu_args import _vm_qemu_arm64_args, _vm_qemu_x86_args
from .ssh_ready import _wait_ssh


def _start_vm(workdir: str, vcpus: int, mem_mib: int, disk_gib: int) -> VMProc:
    """
    Start a QEMU VM, wait for SSH to be ready, and return a VMProc handle.

    This keeps prints, timeouts, and error paths identical to the original.
    """
    print("Starting vm...")
    os.makedirs(workdir, exist_ok=True)
    overlay = os.path.join(workdir, "disk.qcow2")
    seed_iso = os.path.join(workdir, "seed.iso")
    console_log = os.path.join(workdir, "console.log")
    pidfile = os.path.join(workdir, "qemu.pid")

    vm_base_image: str = settings.VM_BASE_IMAGE or ""
    vm_ssh_user: str = settings.VM_SSH_USER or ""
    vm_ssh_privkey: str = settings.VM_SSH_PRIVKEY or ""
    vm_timeout_boot_s: int = int(settings.VM_TIMEOUT_BOOT_S or "100")

    _make_overlay(vm_base_image, overlay, disk_gib=disk_gib)
    _make_seed_iso(
        seed_iso,
        vm_ssh_user,
        vm_ssh_privkey + ".pub",
        os.path.basename(workdir),
    )

    port = _pick_free_port()

    if platform.machine() in ("aarch64", "arm64"):
        print("Using arm64...")
        args = _vm_qemu_arm64_args(
            vcpus=vcpus,
            mem_mib=mem_mib,
            console_log=console_log,
            port=port,
            overlay=overlay,
            seed_iso=seed_iso,
            pidfile=pidfile,
        )
    else:
        print("Using x86...")
        args = _vm_qemu_x86_args(
            vcpus=vcpus,
            mem_mib=mem_mib,
            console_log=console_log,
            port=port,
            overlay=overlay,
            seed_iso=seed_iso,
            pidfile=pidfile,
        )

    proc = subprocess.Popen(
        args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, preexec_fn=os.setsid
    )
    print("Process executed", proc)

    try:
        ok = _wait_ssh(
            port=port,
            timeout=vm_timeout_boot_s,
            user=vm_ssh_user,
            is_vm_alive=lambda: proc.poll() is None,
        )

        if not ok:
            raise TimeoutError("SSH not ready (returned False early)")
    except Exception as e:
        print("Error waiting for ssh", e)
        # Try to provide helpful diagnostics, preserving original behavior.
        try:
            tail = subprocess.run(
                ["tail", "-n", "120", console_log],
                capture_output=True,
                text=True,
                check=True,
            )
            print("=== console.log (tail) ===\n", tail.stdout)
        except Exception as ex:
            print("Error reading the diagnostic", ex)

        if proc.poll() is not None and proc.stdout is not None:
            out = proc.stdout.read().decode(errors="ignore")
            print("QEMU finished during the startup. STDERR/STDOUT:\n", out)
        raise e

    return VMProc(
        workdir=workdir,
        overlay=overlay,
        seed_iso=seed_iso,
        port_ssh=port,
        proc=proc,
        console_log=console_log,
        pidfile=pidfile,
    )
