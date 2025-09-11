from __future__ import annotations

import os
import signal
import threading
import time

import settings

from qemu_manager.vm import _start_vm
from qemu_manager.ssh_ready import _wait_ssh
from qemu_manager.models import VMState, VMRecord


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
        # Bloqueante: ejecutar en thread para no bloquear event loop
        def _run():
            try:
                # Overrides temporales de settings si se especifican
                vm_ssh_user = settings.VM_SSH_USER
                # Lanzar QEMU con utilidades existentes
                proc = _start_vm(vm.workdir, vm.vcpus, vm.mem_mib, vm.disk_gib)
                vm.proc = proc
                vm.ssh_port = proc.port_ssh
                vm.ssh_user = vm_ssh_user
                # Espera de SSH si _start_vm no lo garantiza (defensivo):
                try:
                    _wait_ssh(
                        port=proc.port_ssh,
                        timeout=settings.VM_TIMEOUT_BOOT_S,
                        user=vm_ssh_user,
                    )
                except Exception:
                    pass
                vm.state = VMState.running
                vm.error_reason = None
            except Exception as e:  # pylint: disable=broad-except
                vm.state = VMState.error
                vm.error_reason = str(e)
            finally:
                self.store.put(vm)

        threading.Thread(target=_run, daemon=True).start()

    def stop(self, vm: VMRecord, cleanup_disks: bool = False) -> None:
        def _run():
            try:
                # Señal de apagado "suave" vía SSH (opcional) o matar proceso
                if vm.proc and vm.proc.pidfile and os.path.exists(vm.proc.pidfile):
                    try:
                        with open(vm.proc.pidfile, "r", encoding="utf-8") as f:
                            pid = int(f.read().strip())
                        os.killpg(pid, signal.SIGTERM)
                        time.sleep(1)
                        os.killpg(pid, signal.SIGKILL)
                    except Exception:
                        pass
                elif vm.proc and getattr(vm.proc, "proc", None):
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
                if cleanup_disks:
                    for pth in [
                        getattr(vm.proc, "overlay", None),
                        getattr(vm.proc, "seed_iso", None),
                        getattr(vm.proc, "console_log", None),
                    ]:
                        if pth and os.path.exists(pth):
                            try:
                                os.remove(pth)
                            except Exception:
                                pass
                vm.state = VMState.stopped
                vm.updated_at = time.time()
            except Exception as e:  # pylint: disable=broad-except
                vm.state = VMState.error
                vm.error_reason = str(e)
            finally:
                self.store.put(vm)

        threading.Thread(target=_run, daemon=True).start()
