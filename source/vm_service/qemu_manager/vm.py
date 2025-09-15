import os
import platform
import subprocess
import errno

import settings

from .models import VMProc
from .seed import _make_overlay, _make_seed_iso
from .ports import _pick_free_port
from .qemu_args import _vm_qemu_arm64_args, _vm_qemu_x86_args
from .ssh_ready import _wait_ssh


def _as_int(x, default=None):
    try:
        return int(x) if x is not None else default
    except Exception:
        return default


def _ensure_owner_and_perms(path: str, uid: int, gid: int, dmode=0o775, fmode=0o664):
    if not path:
        return

    os.makedirs(path, exist_ok=True)
    try:
        os.chown(path, uid, gid)
    except PermissionError:
        pass
    os.chmod(path, dmode)

    with os.scandir(path) as it:
        for entry in it:
            try:
                if entry.is_dir(follow_symlinks=False):
                    try:
                        os.chown(entry.path, uid, gid)
                    except PermissionError:
                        pass
                    os.chmod(entry.path, dmode)
                else:
                    try:
                        os.chown(entry.path, uid, gid)
                    except PermissionError:
                        pass
                    os.chmod(entry.path, fmode)
            except FileNotFoundError:
                continue


def _ensure_paths_for_vm(run_uid: int, run_gid: int, workdir: str, files: list[str]):
    old_umask = os.umask(0o002)
    try:
        _ensure_owner_and_perms(workdir, run_uid, run_gid, dmode=0o775, fmode=0o664)

        for p in files:
            d = os.path.dirname(p)
            if d:
                os.makedirs(d, exist_ok=True)
                try:
                    os.chown(d, run_uid, run_gid)
                except PermissionError:
                    pass
                os.chmod(d, 0o775)
            if os.path.exists(p):
                try:
                    os.chown(p, run_uid, run_gid)
                except PermissionError:
                    pass
                os.chmod(p, 0o664)
    finally:
        os.umask(old_umask)


def _drop_privs():
    import pwd, os

    os.setsid()
    run_uid = int(getattr(settings, "VM_RUN_AS_UID", 0) or 0)
    run_gid = int(getattr(settings, "VM_RUN_AS_GID", 0) or 0)
    os.umask(0o002)
    if run_gid:
        os.setgid(run_gid)

        try:
            username = pwd.getpwuid(run_uid).pw_name if run_uid else None
        except KeyError:
            username = None
        if username:
            try:
                os.initgroups(username, run_gid)
            except Exception:
                try:
                    kvm_gid = os.stat("/dev/kvm").st_gid
                    os.setgroups(list({run_gid, kvm_gid}))
                except Exception:
                    os.setgroups([run_gid])
        else:
            try:
                kvm_gid = os.stat("/dev/kvm").st_gid
                os.setgroups(list({run_gid, kvm_gid}))
            except Exception:
                os.setgroups([run_gid])
    if run_uid:
        os.setuid(run_uid)


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except OSError as e:
        return e.errno != errno.ESRCH


def _clear_stale_pidfile(pidfile: str) -> None:
    try:
        if not pidfile or not os.path.exists(pidfile):
            return
        pid = None
        try:
            with open(pidfile, "r", encoding="utf-8") as f:
                pid = int(f.read().strip() or "0")
        except Exception:
            pid = None
        if not pid or not _pid_alive(pid):
            try:
                os.remove(pidfile)
                print(f"Removed stale pidfile: {pidfile}")
            except Exception as e:
                print("Error removing stale pidfile", e)
    except Exception as e:
        print("Error clearing stale pidfile", e)


def _start_vm(
    workdir: str, vcpus: int, mem_mib: int, disk_gib: int, vm_id: str | None = None
) -> VMProc:
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

    _clear_stale_pidfile(pidfile)

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

    run_uid = _as_int(getattr(settings, "VM_RUN_AS_UID", None))
    run_gid = _as_int(getattr(settings, "VM_RUN_AS_GID", None))

    if run_uid is not None and run_gid is not None:
        _ensure_paths_for_vm(
            run_uid, run_gid, workdir, files=[overlay, seed_iso, console_log]
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
        args,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        preexec_fn=_drop_privs,
    )
    print("Process executed", proc)

    try:
        ok = _wait_ssh(
            port=port,
            timeout=vm_timeout_boot_s,
            user=vm_ssh_user,
            is_vm_alive=lambda: proc.poll() is None,
            vm_id=vm_id,
        )
        if not ok:
            raise TimeoutError("SSH not ready (returned False early)")
    except Exception as e:
        print("Error waiting for ssh", e)
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
