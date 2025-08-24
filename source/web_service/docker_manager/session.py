import os
import shutil
import socket
import subprocess
import tempfile
import threading
import time
from dataclasses import dataclass
from typing import Callable, Optional

import paramiko
from django.conf import settings


# ========== QEMU helpers ==========
def _pick_free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


@dataclass
class VMProc:
    workdir: str
    overlay: str
    seed_iso: str
    port_ssh: int
    proc: Optional[subprocess.Popen] = None
    console_log: Optional[str] = None


def _make_overlay(base_image: str, overlay: str, disk_gib: int = 10):
    subprocess.run(
        [
            "qemu-img",
            "create",
            "-f",
            "qcow2",
            "-F",
            "qcow2",
            "-b",
            base_image,
            overlay,
            f"{disk_gib}G",
        ],
        check=True,
    )


def _make_seed_iso(seed_iso: str, user: str, pubkey_path: str, instance_id: str):
    assert os.path.exists(pubkey_path), f"No existe {pubkey_path}"
    pubkey = open(pubkey_path, encoding="utf-8").read().strip()
    user_data = f"""#cloud-config
users:
  - name: {user}
    sudo: ALL=(ALL) NOPASSWD:ALL
    groups: sudo
    ssh_authorized_keys:
      - {pubkey}
ssh_pwauth: false
disable_root: true
package_update: true
packages:
  - docker.io
runcmd:
  - systemctl enable --now docker
"""
    meta_data = f"""instance-id: {instance_id}
local-hostname: {instance_id}
"""
    wd = os.path.dirname(seed_iso)
    ud = os.path.join(wd, "user-data")
    md = os.path.join(wd, "meta-data")
    open(ud, "w", encoding="utf-8").write(user_data)
    open(md, "w", encoding="utf-8").write(meta_data)

    cloud_localds = shutil.which("cloud-localds")
    geniso = shutil.which("genisoimage") or shutil.which("mkisofs")
    if cloud_localds:
        subprocess.run([cloud_localds, seed_iso, ud, md], check=True)
    else:
        input_data: list = [
            geniso,
            "-output",
            seed_iso,
            "-volid",
            "cidata",
            "-joliet",
            "-rock",
            ud,
            md,
        ]
        subprocess.run(
            input_data,
            check=True,
        )


def _wait_ssh(port: int, timeout: int, user: str, key_path: str):
    start = time.time()
    while time.time() - start < timeout:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=2):
                pass
            # prueba SSH real
            k = paramiko.Ed25519Key.from_private_key_file(key_path)
            cli = paramiko.SSHClient()
            cli.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            cli.connect(
                "127.0.0.1",
                port=port,
                username=user,
                pkey=k,
                banner_timeout=120,
                auth_timeout=120,
                timeout=30,
                look_for_keys=False,
            )
            cli.close()
            return
        except Exception:
            time.sleep(2)
    raise TimeoutError("SSH no respondió a tiempo")


def _start_vm(workdir: str, vcpus=2, mem_mib=2048, disk_gib=10) -> VMProc:
    os.makedirs(workdir, exist_ok=True)
    overlay = os.path.join(workdir, "disk.qcow2")
    seed_iso = os.path.join(workdir, "seed.iso")
    console_log = os.path.join(workdir, "console.log")
    port = _pick_free_port()

    vm_base_image: str = settings.VM_BASE_IMAGE or ""
    vm_ssh_user: str = settings.VM_SSH_USER or ""
    vm_ssh_user: str = settings.VM_SSH_PRIVKEY or ""
    vm_timeout_boot_s: str = settings.VM_TIMEOUT_BOOT_S or ""
    vm_ssh_user: str = settings.VM_SSH_USER or ""
    vm_ssh_privkey: str = settings.VM_SSH_PRIVKEY or ""

    _make_overlay(vm_base_image, overlay, disk_gib=disk_gib)
    _make_seed_iso(
        seed_iso,
        vm_ssh_user,
        vm_ssh_user + ".pub",
        os.path.basename(workdir),
    )

    args: list = [settings.VM_QEMU_BIN]
    if os.path.exists("/dev/kvm"):
        args += ["-enable-kvm", "-machine", "accel=kvm,type=q35", "-cpu", "host"]
    else:
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

    proc = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    try:
        _wait_ssh(
            port,
            vm_timeout_boot_s,
            vm_ssh_user,
            vm_ssh_privkey,
        )
    except Exception:
        try:
            tail = subprocess.run(
                ["tail", "-n", "120", console_log],
                capture_output=True,
                text=True,
                check=True,
            )
            print("=== console.log (tail) ===\n", tail.stdout)
        except Exception:
            pass
        if proc.poll() is not None and proc.stdout is not None:
            out = proc.stdout.read().decode(errors="ignore")
            print("QEMU terminó durante el arranque. STDERR/STDOUT:\n", out)
        raise
    return VMProc(
        workdir=workdir,
        overlay=overlay,
        seed_iso=seed_iso,
        port_ssh=port,
        proc=proc,
        console_log=console_log,
    )


# ========== Sesión interactiva (SSH + pty) ==========
class QemuSession:  # mantenemos el nombre para no tocar imports
    """
    Reimplementada para hablar con una VM QEMU vía SSH (Paramiko).
    Proporciona:
      - stream interactivo (PTY) con callbacks on_line / on_close
      - send(text) para escribir al shell
      - reopen() para reabrir el canal si muere
      - is_alive()
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

        # Paths por-usuario/PK del modelo
        vm_base_dir = settings.VM_BASE_DIR or ""
        base = os.path.join(vm_base_dir, "vms")
        self.workdir = os.path.join(base, f"vm-{container_obj.pk}")
        os.makedirs(self.workdir, exist_ok=True)

        self.vm: Optional[VMProc] = None
        self.cli: Optional[paramiko.SSHClient] = None
        self.chan: Optional[paramiko.Channel] = None
        self.reader_thread: Optional[threading.Thread] = None
        self.alive = False

        self._ensure_vm()
        self._open_exec()

    # ---- control de VM ----
    def _ensure_vm(self):
        # Si ya hay un puerto recordado en container_id (guardamos ahí)
        if (
            self.container_obj.container_id
            and self.container_obj.container_id.startswith("qemu:")
        ):
            # formato qemu:<port>
            try:
                port = int(self.container_obj.container_id.split(":")[1])
            except Exception:
                port = None
        else:
            port = None

        # ¿puerto usable?
        if port:
            if self._ping_ssh_port(port):
                self.vm = VMProc(
                    workdir=self.workdir,
                    overlay="",
                    seed_iso="",
                    port_ssh=port,
                    proc=None,
                )
                return

        # Arranca nueva VM
        self.vm = _start_vm(self.workdir)
        # Guarda el “id” como qemu:<port> para reusar
        self.container_obj.container_id = f"qemu:{self.vm.port_ssh}"
        self.container_obj.status = "running"
        self.container_obj.save(update_fields=["container_id", "status"])

    def _ping_ssh_port(self, port: int) -> bool:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=1.5):
                return True
        except Exception:
            return False

    # ---- control de canal/pty ----
    def _open_exec(self):
        if not self.vm:
            return

        self._close_channel()

        k = paramiko.Ed25519Key.from_private_key_file(settings.VM_SSH_PRIVKEY)
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
        chan = cli.invoke_shell(width=120, height=32)  # PTY interactivo
        chan.settimeout(0.0)  # non-blocking

        self.cli = cli
        self.chan = chan
        self.alive = True

        t = threading.Thread(target=self._reader, daemon=True)
        t.start()
        self.reader_thread = t

    def _reader(self):
        try:
            while self.alive and self.chan and not self.chan.closed:
                try:
                    data = self.chan.recv(4096)
                    if not data:
                        break
                    text = data.decode(errors="ignore")
                    if self._on_line and text:
                        for line in text.splitlines(True):  # conserva \n
                            self._on_line(line)
                except Exception:
                    time.sleep(0.02)
        finally:
            self.alive = False
            if self._on_close:
                self._on_close()

    def set_on_line(self, cb):
        self._on_line = cb

    def set_on_close(self, cb):
        self._on_close = cb

    def is_alive(self) -> bool:
        return bool(self.alive and self.chan and not self.chan.closed)

    def reopen(self):
        self._open_exec()

    def send(self, text: str):
        if not self.chan or self.chan.closed:
            raise RuntimeError("Shell no activo")
        # asegúrate de agregar \n cuando sea un comando
        if not text.endswith("\n"):
            text = text + "\n"
        self.chan.send(text)

    def _close_channel(self):
        try:
            if self.chan and not self.chan.closed:
                self.chan.close()
        except Exception:
            ...
        try:
            if self.cli:
                self.cli.close()
        except Exception:
            ...
        self.chan = None
        self.cli = None
        self.alive = False
