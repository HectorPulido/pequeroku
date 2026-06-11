from __future__ import annotations

import os
import signal
import threading
import time
import traceback

import settings

from qemu_manager.vm import start_vm
from models import VMState, VMRecord

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from implementations import RedisStore


class Runner:
    # pyrefly: ignore  # unknown-name
    def __init__(self, store: "RedisStore", node_name: str) -> None:
        self.node_name = node_name
        self.store = store

    def workdir(self, vm_id: str) -> str:
        base = os.path.join(settings.VM_BASE_DIR, "vms")
        os.makedirs(base, exist_ok=True)
        wd = os.path.join(base, vm_id)
        os.makedirs(wd, exist_ok=True)
        return wd

    def start(self, vm: VMRecord) -> None:
        # This is blocking
        def _run():
            try:
                vm_ssh_user = settings.VM_SSH_USER
                proc = start_vm(vm.workdir, vm.vcpus, vm.mem_mib, vm.disk_gib, vm.id)
                vm.proc = proc
                vm.ssh_port = proc.port_ssh
                vm.ssh_user = vm_ssh_user

                # start_vm already waited for SSH and warmed the SSH cache
                # (see wait_ssh / finalize_and_cache); no second probe needed.
                self.store.set_status(vm, VMState.running)
            except Exception as e:  # pylint: disable=broad-except
                # Surface the reason: this used to be swallowed into error_reason
                # with no log, so a failed VM showed "error" with nothing in the logs.
                print(f"[vm_service] start_vm FAILED for vm={vm.id}: {e!r}")
                traceback.print_exc()
                self.store.set_status(vm, VMState.error, error_reason=str(e))
            finally:
                self.store.put(vm)

        threading.Thread(target=_run, daemon=True).start()
        vm.booted_at = time.time()
        self.store.put(vm)

    @staticmethod
    def _clean_up(vm: VMRecord):
        for pth in [
            os.path.join(vm.workdir, "disk.qcow2"),
            os.path.join(vm.workdir, "seed.iso"),
            os.path.join(vm.workdir, "console.log"),
            os.path.join(vm.workdir, "qemu.pid"),
            os.path.join(vm.workdir, "user-data"),
            os.path.join(vm.workdir, "meta-data"),
            os.path.join(vm.workdir, "seed.iso.spec"),
        ]:
            try:
                if os.path.exists(pth):
                    os.remove(pth)
            except Exception:
                pass

    @staticmethod
    def _kill_by_pid(pid):
        try:
            os.killpg(pid, signal.SIGTERM)
            time.sleep(1.0)
        except Exception:
            pass
        try:
            os.killpg(pid, signal.SIGKILL)
        except Exception:
            pass

    @staticmethod
    def _kill_by_popen(vm):
        try:
            p = vm.proc.proc
            if p:
                p.terminate()
                try:
                    p.wait(timeout=5)
                except Exception:
                    p.kill()
        except Exception:
            pass

    @staticmethod
    def _try_to_get_pid(vm: VMRecord):
        vm_base_dir = settings.VM_BASE_DIR or ""
        pidfile = os.path.join(vm_base_dir, "vms", vm.id, "qemu.pid")

        pid = None
        if os.path.exists(pidfile):
            try:
                with open(pidfile, "r", encoding="utf-8") as f:
                    pid = int((f.read() or "0").strip())
            except Exception:
                pid = None
        return pid, pidfile

    def stop(self, vm: VMRecord, cleanup_disks: bool = False) -> None:
        def _run():
            try:
                pid, pidfile = self._try_to_get_pid(vm)

                if pid:
                    self._kill_by_pid(pid)
                elif vm.proc and getattr(vm.proc, "proc", None):
                    self._kill_by_popen(vm)

                if cleanup_disks:
                    self._clean_up(vm)

                try:
                    if os.path.exists(pidfile):
                        os.remove(pidfile)
                except Exception:
                    pass

                self.store.set_status(vm, VMState.stopped)
            except Exception as e:  # pylint: disable=broad-except
                print(f"[vm_service] stop FAILED for vm={vm.id}: {e!r}")
                traceback.print_exc()
                self.store.set_status(vm, VMState.error, error_reason=str(e))
            finally:
                self.store.put(vm)

        threading.Thread(target=_run, daemon=True).start()
