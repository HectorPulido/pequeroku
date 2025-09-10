import os
import socket
import threading
import time
import signal
from typing import Callable, Optional

import paramiko


import settings

from .models import VMProc
from .vm import _start_vm
from .crypto import _load_pkey
from .ssh_ready import _wait_ssh


def _remove_pidfile_safe(pidfile: Optional[str]) -> None:
    if not pidfile:
        return
    try:
        if os.path.exists(pidfile):
            os.remove(pidfile)
            print(f"Removed pidfile: {pidfile}")
    except Exception as e:
        print("Error removing pidfile", e)


class QemuSession:
    """
    SSH-backed interactive session to a QEMU VM using Paramiko.

    Provides:
      - Interactive PTY stream with on_line / on_close callbacks
      - send(text) to write to the shell (auto-append newline if missing)
      - reopen() to re-open the channel if it dies
      - is_alive() to check channel health

    """

    def __init__(
        self,
        container_obj,
        on_line: Optional[Callable[[str], None]] = None,
        on_close: Optional[Callable[[], None]] = None,
    ):
        self.container_obj = container_obj
        self._on_line = on_line
        self._on_close = on_close

        # Per-user/PK workspace
        vm_base_dir = settings.VM_BASE_DIR or ""
        base = os.path.join(vm_base_dir, "vms")
        self.workdir = os.path.join(base, f"vm-{container_obj.pk}")
        os.makedirs(self.workdir, exist_ok=True)

        self.vm: Optional[VMProc] = None
        self.cli: Optional[paramiko.SSHClient] = None
        self.chan: Optional[paramiko.Channel] = None
        self.reader_thread: Optional[threading.Thread] = None
        self.alive: bool = False

        self.mem_mib = container_obj.memory_mb
        self.vcpus = container_obj.vcpu
        self.disk_gib = container_obj.disk_gib

        self._ensure_vm()
        self._open_exec()

    # ---- VM control ----
    def _ensure_vm(self) -> None:
        """
        Reuse an existing qemu:<port> if alive; otherwise boot a new VM and update
        container state accordingly.
        """
        old_port: Optional[int]
        if getattr(self.container_obj, "container_id", None) and str(
            self.container_obj.container_id
        ).startswith("qemu:"):
            try:
                old_port = int(str(self.container_obj.container_id).split(":")[1])
            except Exception as e:
                old_port = None
                print(
                    f"Error getting the port from {self.container_obj.container_id}", e
                )
        else:
            old_port = None

        pidfile_path = os.path.join(self.workdir, "qemu.pid")

        def _quick_ssh_ok(p: int) -> bool:
            try:
                _wait_ssh(port=p, timeout=5, user=settings.VM_SSH_USER)
                return True
            except Exception as e:
                print("Quick SSH check failed on reattach", e)
                return False

        if old_port and _quick_ssh_ok(old_port):
            self.vm = VMProc(
                workdir=self.workdir,
                overlay="",
                seed_iso="",
                port_ssh=old_port,
                proc=None,
                console_log=os.path.join(self.workdir, "console.log"),
                pidfile=pidfile_path if os.path.exists(pidfile_path) else None,
            )
            return

        if os.path.exists(pidfile_path):
            try:
                os.remove(pidfile_path)
                print(f"Removed stale pidfile before boot: {pidfile_path}")
            except Exception as e:
                print("Error removing stale pidfile (pre-boot)", e)

        self.vm = _start_vm(
            self.workdir,
            self.vcpus,
            self.mem_mib,
            self.disk_gib,
        )
        self.container_obj.container_id = f"qemu:{self.vm.port_ssh}"
        self.container_obj.status = "running"
        self.container_obj.save(update_fields=["container_id", "status"])

    def _ping_ssh_port(self, port: int) -> bool:
        """Quick TCP check to see if a previous VM is still reachable."""
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=1.5):
                return True
        except Exception as e:
            print("Error pinging ssh port", e)
            return False

    # ---- Channel / PTY control ----
    def _open_exec(self) -> None:
        """
        Open a new interactive shell channel (PTY) and start the reader thread.
        """
        if not self.vm:
            return

        self._close_channel()

        k = _load_pkey(settings.VM_SSH_PRIVKEY)
        cli = paramiko.SSHClient()
        cli.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        cli.connect(
            "127.0.0.1",
            port=self.vm.port_ssh,
            username=settings.VM_SSH_USER,
            pkey=k,
            look_for_keys=False,
            banner_timeout=120,
            auth_timeout=120,
            timeout=30,
        )

        if cli.get_transport() is not None:
            # pyrefly: ignore  # missing-attribute
            cli.get_transport().set_keepalive(15)

        chan = cli.invoke_shell(width=120, height=32)  # interactive PTY
        chan.settimeout(0.0)  # non-blocking

        self.cli = cli
        self.chan = chan
        self.alive = True

        t = threading.Thread(target=self._reader, daemon=True)
        t.start()
        self.reader_thread = t

    def _reader(self) -> None:
        """Continuously read from the channel and fan out lines to on_line callback."""
        try:
            while self.alive and self.chan and not self.chan.closed:
                try:
                    data = self.chan.recv(4096)
                    if not data:
                        break
                    text = data.decode(errors="ignore")
                    if self._on_line and text:
                        # Preserve newline characters when splitting
                        for line in text.splitlines(True):
                            self._on_line(line)
                except Exception as e:
                    time.sleep(0.02)
                    if str(e).strip() != "":
                        print("Error on reader", e)
        finally:
            self.alive = False
            if self._on_close:
                self._on_close()

    # ---- Public API ----
    def set_on_line(self, cb: Optional[Callable[[str], None]]) -> None:
        """Set on line"""
        self._on_line = cb

    def set_on_close(self, cb: Optional[Callable[[], None]]) -> None:
        """Set on close"""
        self._on_close = cb

    def is_alive(self) -> bool:
        """Get if alive"""
        return bool(self.alive and self.chan and not self.chan.closed)

    def reopen(self) -> None:
        """Reopen interactive shell"""
        self._open_exec()

    def send(self, text: str) -> None:
        """
        Send text to the PTY. Ensures a trailing newline to execute commands.
        """
        if not self.chan or self.chan.closed:
            raise RuntimeError("Shell no activo")
        if not text.endswith("\n"):
            text = text + "\n"
        self.chan.send(text)

    def _close_channel(self) -> None:
        """Close channel and client, mirroring original exception swallowing."""
        try:
            if self.chan and not self.chan.closed:
                self.chan.close()
        except Exception as e:
            print("Error closing channel", e)
        try:
            if self.cli:
                self.cli.close()
        except Exception as e:
            print("Error closing cli", e)
        self.chan = None
        self.cli = None
        self.alive = False

    # ---- VM lifecycle ----
    def stop(self, cleanup_disks: bool = False, wait_s: int = 20) -> None:
        """
        Shutdown the VM and clean the resources
        if channel alive, try: sudo poweroff
        if not, use terminate/kill on qemu
        wait for the port to stop
        lastly clean up averything
        """

        try:
            if self.is_alive():
                try:
                    # pyrefly: ignore  # missing-attribute
                    self.chan.send("sudo poweroff\n")
                except Exception as e:
                    print("Error sending poweroff", e)
        except Exception as e:
            print("Error powering off", e)

        deadline = time.time() + wait_s
        while time.time() < deadline:
            if not self.vm or not self._ping_ssh_port(self.vm.port_ssh):
                break
            time.sleep(0.5)

        pid = None
        try:
            if self.vm and self.vm.pidfile and os.path.exists(self.vm.pidfile):
                try:
                    with open(self.vm.pidfile, "r", encoding="utf-8") as f:
                        pid = int(f.read().strip())
                    try:
                        os.killpg(pid, signal.SIGTERM)
                        time.sleep(1.0)
                    except Exception as e:
                        print("Error SIGTERM pgid", e)
                    try:
                        os.killpg(pid, signal.SIGKILL)
                    except Exception as e:
                        print("Error SIGKILL pgid", e)
                except Exception as e:
                    print("Error killing by pidfile", e)
            elif self.vm and self.vm.proc:
                try:
                    self.vm.proc.terminate()
                    try:
                        self.vm.proc.wait(timeout=5)
                    except Exception:
                        self.vm.proc.kill()
                except Exception as e:
                    print("Error terminating process", e)
        except Exception as e:
            print("Error terminating process (outer)", e)

        if cleanup_disks and self.vm:
            for p in (self.vm.overlay, self.vm.seed_iso, self.vm.console_log):
                try:
                    if p and os.path.exists(p):
                        os.remove(p)
                except Exception as e:
                    print("Error clearning up", e)

        try:
            self.container_obj.status = "stopped"
            self.container_obj.save(update_fields=["status"])
        except Exception as e:
            print("Error changing status", e)

        t = self.reader_thread
        self._close_channel()
        try:
            if t:
                t.join(timeout=2.0)
        except Exception as e:
            print("Error joining reader thread", e)

        # pyrefly: ignore  # missing-attribute
        _remove_pidfile_safe(self.vm.pidfile)
