import os
import re
import shlex
import signal
import socket
import subprocess
import time
from typing import Optional

import paramiko
from django.core.management.base import BaseCommand, CommandError
from django.conf import settings
from django.apps import apps


RUNNING = "running"
STOPPED = "stopped"
CREATING = "creating"
ERROR = "error"
UNKNOWN = "unknown"

Container = apps.get_model("docker_manager", "Container")


def _ssh_ping(port: int, timeout=2.0) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=timeout):
            return True
    except Exception:
        return False


def _ssh_login_ok(port: int | None, timeout=6.0) -> bool:
    try:
        key = paramiko.Ed25519Key.from_private_key_file(settings.VM_SSH_PRIVKEY)
        cli = paramiko.SSHClient()
        cli.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        cli.connect(
            "127.0.0.1",
            port=port,
            username=settings.VM_SSH_USER,
            pkey=key,
            look_for_keys=False,
            timeout=timeout,
            banner_timeout=timeout,
            auth_timeout=timeout,
        )
        cli.close()
        return True
    except Exception:
        return False


def _extract_port(container_id: str) -> Optional[int]:
    try:
        if container_id and container_id.startswith("qemu:"):
            return int(container_id.split(":")[1])
    except Exception:
        pass
    return None


def _find_qemu_pid_by_port(port: int) -> Optional[int]:
    pat = f"hostfwd=tcp:127.0.0.1:{port}-:22"
    try:
        out = subprocess.check_output(["ps", "-eo", "pid,args"], text=True)
        for line in out.splitlines():
            if pat in line and "qemu-system" in line:
                m = re.match(r"\s*(\d+)\s", line)
                if m:
                    return int(m.group(1))
    except Exception:
        pass
    return None


def _graceful_shutdown(port: int, wait_s: int = 45) -> bool:
    """Intenta apagar por SSH; espera a que el puerto cierre."""
    try:
        key = paramiko.Ed25519Key.from_private_key_file(settings.VM_SSH_PRIVKEY)
        cli = paramiko.SSHClient()
        cli.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        cli.connect(
            "127.0.0.1",
            port=port,
            username=settings.VM_SSH_USER,
            pkey=key,
            look_for_keys=False,
            timeout=10,
        )
        cli.exec_command("sudo shutdown -h now || poweroff || halt || init 0")
        cli.close()
    except Exception:
        pass

    start = time.time()
    while time.time() - start < wait_s:
        if not _ssh_ping(port, timeout=1.0):
            return True
        time.sleep(2)
    return False


def _force_kill(port: int) -> bool:
    pid = _find_qemu_pid_by_port(port)
    if not pid:
        return True
    try:
        os.kill(pid, signal.SIGTERM)
        for _ in range(20):
            try:
                os.kill(pid, 0)
                time.sleep(0.5)
            except ProcessLookupError:
                return True
        os.kill(pid, signal.SIGKILL)
        return True
    except Exception:
        return False


def _vm_workdir(container_pk: int) -> str:
    base = settings.VM_BASE_DIR or ""
    return os.path.join(base, "vms", f"vm-{container_pk}")


def _start_vm(container_obj: "Container"):
    from qemu_manager import QemuSession

    sess = QemuSession(container_obj, on_line=None, on_close=None)

    try:
        sess._close_channel()
    except Exception:
        pass
    return container_obj.container_id


def _sync_one(c: "Container") -> str:
    """Devuelve el status nuevo (y si cambia, lo guarda)."""
    old = c.status or UNKNOWN
    port = _extract_port(c.container_id or "")
    new = old

    if port is None:
        new = STOPPED
    else:
        if _ssh_login_ok(port):
            new = RUNNING
        elif _ssh_ping(port):
            new = "booting"
        else:
            pid = _find_qemu_pid_by_port(port)
            new = RUNNING if pid else STOPPED

    if new != old:
        c.status = new
        c.save(update_fields=["status"])
    return new


class Command(BaseCommand):
    help = "Control y sincronización de VMs QEMU asociadas a Containers."

    def add_arguments(self, parser):
        sub = parser.add_subparsers(dest="cmd", required=True)

        sub.add_parser("status", help="Muestra estado de todas las VMs")

        p_sync = sub.add_parser("sync", help="Sincroniza estado real → BD")
        p_sync.add_argument("--id", type=int, help="Sólo este container id")

        p_start = sub.add_parser("start", help="Enciende una VM parada")
        p_start.add_argument("id", type=int)

        p_stop = sub.add_parser(
            "stop", help="Apaga una VM (intento suave; --force para matar)"
        )
        p_stop.add_argument("id", type=int)
        p_stop.add_argument("--force", action="store_true")

    def handle(self, *args, **opts):
        cmd = opts["cmd"]

        if cmd == "status":
            self._cmd_status()
        elif cmd == "sync":
            self._cmd_sync(opts.get("id"))
        elif cmd == "start":
            self._cmd_start(opts["id"])
        elif cmd == "stop":
            self._cmd_stop(opts["id"], opts["force"])
        elif cmd == "prune-orphans":
            self._cmd_prune()
        else:
            raise CommandError("Comando desconocido")

    def _cmd_status(self):
        qs = Container.objects.all().order_by("id")
        if not qs.exists():
            self.stdout.write("No hay containers.")
            return
        for c in qs:
            port = _extract_port(c.container_id or "")
            pid = _find_qemu_pid_by_port(port) if port else None
            self.stdout.write(
                f"#{c.pk}: status={c.status} cid={c.container_id} pid={pid or '-'}"
            )

    def _cmd_sync(self, only_id: Optional[int]):
        qs = Container.objects.all()
        if only_id:
            qs = qs.filter(pk=only_id)
            if not qs.exists():
                raise CommandError(f"No existe Container {only_id}")

        changed = 0
        for c in qs:
            new = _sync_one(c)
            self.stdout.write(f"#{c.pk}: {new}")
            changed += 1
        self.stdout.write(self.style.SUCCESS(f"Sincronizados {changed} registros."))

    def _cmd_start(self, cid: int):
        c = Container.objects.filter(pk=cid).first()
        if not c:
            raise CommandError(f"No existe Container {cid}")

        port = _extract_port(c.container_id or "")
        if port and (_ssh_login_ok(port) or _find_qemu_pid_by_port(port)):
            self.stdout.write(self.style.WARNING("Ya está encendida."))
            return

        c.status = CREATING
        c.save(update_fields=["status"])
        new_cid = _start_vm(c)
        self.stdout.write(f"Booting VM on {new_cid} ...")

        port = _extract_port(new_cid)
        for _ in range(int(settings.VM_TIMEOUT_BOOT_S or 120) // 2):
            if _ssh_login_ok(port, timeout=3):
                c.status = RUNNING
                c.save(update_fields=["status"])
                self.stdout.write(self.style.SUCCESS("VM RUNNING"))
                return
            time.sleep(2)

        c.status = ERROR
        c.save(update_fields=["status"])
        raise CommandError("Timeout esperando SSH")

    def _cmd_stop(self, cid: int, force: bool):
        c = Container.objects.filter(pk=cid).first()
        if not c:
            raise CommandError(f"No existe Container {cid}")

        port = _extract_port(c.container_id or "")
        if not port:
            self.stdout.write(
                self.style.WARNING("No hay puerto/VM asignada (ya estará parada).")
            )
            c.status = STOPPED
            c.save(update_fields=["status"])
            return

        ok = _graceful_shutdown(port)
        if not ok and force:
            self.stdout.write("No bajó suave, matando proceso...")
            ok = _force_kill(port)

        new = _sync_one(c)
        self.stdout.write(self.style.SUCCESS(f"Estado final: {new}"))

    def _cmd_prune(self):
        out = subprocess.check_output(["ps", "-eo", "pid,args"], text=True)
        lines = [
            ln
            for ln in out.splitlines()
            if "qemu-system" in ln and "hostfwd=tcp:127.0.0.1:" in ln
        ]
        pruned = 0
        for ln in lines:
            m = re.search(r"hostfwd=tcp:127\.0\.0\.1:(\d+)-:22", ln)
            if not m:
                continue
            port = int(m.group(1))
            pid = _find_qemu_pid_by_port(port)

            has = Container.objects.filter(
                container_id=f"qemu:{port}", status=RUNNING
            ).exists()
            if not has and pid:
                try:
                    os.kill(pid, signal.SIGTERM)
                    pruned += 1
                    self.stdout.write(f"Pruned QEMU pid={pid} port={port}")
                except Exception as e:
                    self.stderr.write(str(e))
        self.stdout.write(self.style.SUCCESS(f"Pruned {pruned} procesos."))
