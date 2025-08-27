import os
import shutil
import socket
import subprocess
import tempfile
import threading
import time
import json
import hashlib
import platform
from dataclasses import dataclass
from typing import Callable, Optional

import paramiko
from django.conf import settings


@dataclass
class VMProc:
    workdir: str
    overlay: str
    seed_iso: str
    port_ssh: int
    proc: Optional[subprocess.Popen] = None
    console_log: Optional[str] = None


# ========== QEMU helpers ==========
def _pick_free_port() -> int:
    print("Picking a port...")
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    print("Port selected", port)
    return port


def _spec_hash(user: str, pubkey_path: str) -> str:
    pub = open(pubkey_path).read().strip()
    blob = json.dumps({"user": user, "pub": pub}, sort_keys=True).encode()
    return hashlib.sha256(blob).hexdigest()


def _load_pkey(path: str):
    for K in (paramiko.Ed25519Key, paramiko.RSAKey, paramiko.ECDSAKey):
        try:
            return K.from_private_key_file(path)
        except Exception:
            continue
    raise RuntimeError(f"Could not load the private key: {path}")


def _make_overlay(base_image: str, overlay: str, disk_gib: int = 10):
    print("Creating the overlay with: ", base_image, overlay, disk_gib)
    if os.path.exists(overlay):
        return
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
    print("Creating the seed iso: ", seed_iso, user, pubkey_path, instance_id)
    spec_path = seed_iso + ".spec"
    want = _spec_hash(user, pubkey_path)

    if os.path.exists(seed_iso) and os.path.exists(spec_path):
        if open(spec_path).read().strip() == want:
            return
    assert os.path.exists(pubkey_path), f"No existe {pubkey_path}"
    pubkey = open(pubkey_path, encoding="utf-8").read().strip()
    user_data = f"""#cloud-config
disable_root: false
ssh_pwauth: false

users:
  - name: {settings.VM_SSH_USER}   # p.ej. ubuntu si sigues usando eso
    sudo: ALL=(ALL) NOPASSWD:ALL
    groups: sudo,docker
    ssh_authorized_keys:
      - {pubkey}
  - name: root
    ssh_authorized_keys:
      - {pubkey}

packages:
  - docker.io

write_files:
  - path: /etc/ssh/sshd_config.d/pequeroku.conf
    owner: root:root
    permissions: '0644'
    content: |
      PermitRootLogin yes
      PasswordAuthentication no

runcmd:
  - systemctl restart ssh
  - usermod -aG docker {settings.VM_SSH_USER}
  - mkdir -p /app
  - chown {settings.VM_SSH_USER}:{settings.VM_SSH_USER} /app
  - chmod 0777 /app
  - systemctl enable --now docker
  - cd /app
"""
    meta_data = f"""instance-id: {instance_id}
local-hostname: {instance_id}
"""
    open(spec_path, "w").write(want)

    wd = os.path.dirname(seed_iso)
    ud = os.path.join(wd, "user-data")
    md = os.path.join(wd, "meta-data")
    open(ud, "w", encoding="utf-8").write(user_data)
    open(md, "w", encoding="utf-8").write(meta_data)

    cloud_localds = shutil.which("cloud-localds")
    geniso = shutil.which("genisoimage") or shutil.which("mkisofs")
    if cloud_localds:
        print("Using cloud localds")
        subprocess.run([cloud_localds, seed_iso, ud, md], check=True)
    else:
        print("Using geniso image")
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
            k = _load_pkey(settings.VM_SSH_PRIVKEY)
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
    raise TimeoutError("SSH timeout")


def _vm_qemu_arm64_args(
    vcpus,
    mem_mib,
    console_log,
    port,
    overlay,
    seed_iso,
):
    uefi_candidates = [
        "/usr/share/qemu-efi-aarch64/QEMU_EFI.fd",
        "/usr/share/AAVMF/AAVMF_CODE.fd",
    ]
    uefi = None
    for candidate in uefi_candidates:
        if os.path.exists(candidate):
            uefi = candidate
            break

    if uefi is None:
        raise FileNotFoundError("Not valid UEFI installed")

    args: list = [settings.VM_QEMU_BIN]
    if os.path.exists("/dev/kvm") and platform.machine() in ("aarch64", "arm64"):
        print("Using KVM")
        args += ["-accel", "kvm"]
    else:
        print("Not using KVM")
        args += ["-accel", "tcg,thread=multi"]

    args += [
        "-machine",
        "virt",
        "-cpu",
        "cortex-a57",
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
        "-drive",
        f"if=none,format=raw,readonly=on,file={seed_iso},id=cidata",
        "-device",
        "virtio-blk-device,drive=cidata",
    ]
    return args


def _vm_qemu_x86_args(
    vcpus,
    mem_mib,
    console_log,
    port,
    overlay,
    seed_iso,
):
    args: list = [settings.VM_QEMU_BIN]
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
    return args


def _start_vm(workdir: str, vcpus=2, mem_mib=2048, disk_gib=10) -> VMProc:
    print("Starting vm...")
    os.makedirs(workdir, exist_ok=True)
    overlay = os.path.join(workdir, "disk.qcow2")
    seed_iso = os.path.join(workdir, "seed.iso")
    console_log = os.path.join(workdir, "console.log")

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

    args: list[str] = []
    if platform.machine() in ("aarch64", "arm64"):
        print("Using arm64...")
        args = _vm_qemu_arm64_args(
            vcpus,
            mem_mib,
            console_log,
            port,
            overlay,
            seed_iso,
        )
    else:
        print("Using x86...")
        args = _vm_qemu_x86_args(
            vcpus,
            mem_mib,
            console_log,
            port,
            overlay,
            seed_iso,
        )

    proc = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    print("Process executed", proc)
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
        if (
            self.container_obj.container_id
            and self.container_obj.container_id.startswith("qemu:")
        ):
            try:
                old_port = int(self.container_obj.container_id.split(":")[1])
            except Exception:
                old_port = None
        else:
            old_port = None

        if old_port and self._ping_ssh_port(old_port):
            self.vm = VMProc(
                workdir=self.workdir,
                overlay="",
                seed_iso="",
                port_ssh=old_port,
                proc=None,
            )
            return

        self.vm = _start_vm(self.workdir, 1, 512)
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
