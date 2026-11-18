import socket
import time
from typing import Callable

import paramiko

import settings
from .crypto import load_pkey
from .ssh_peer import verify_ssh_peer


def wait_ssh(
    port: int,
    timeout: int,
    user: str,
    pidfile: str,
    is_vm_alive: Callable[[], bool] | None = None,
) -> bool:
    """Wait for an authenticated SSH connection to the expected QEMU process."""
    print("Start the wait_ssh process...")
    start = time.monotonic()

    while time.monotonic() - start < timeout:
        if is_vm_alive is not None and not is_vm_alive():
            print("QEMU process died while waiting for SSH")
            return False
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=1.0) as sock:
                pkey = load_pkey(settings.VM_SSH_PRIVKEY)
                with paramiko.SSHClient() as cli:
                    cli.set_missing_host_key_policy(paramiko.AutoAddPolicy())
                    cli.connect(
                        "127.0.0.1",
                        port=port,
                        username=user,
                        pkey=pkey,
                        banner_timeout=10,
                        auth_timeout=10,
                        timeout=3,
                        look_for_keys=False,
                        sock=sock,
                    )
                    verify_ssh_peer(sock, pidfile)
            print(f"SSH Connection READY! TIME TAKEN: {time.monotonic() - start}")
            return True
        except Exception as e:
            if str(e).strip():
                print("Error opening ssh", e)
            time.sleep(0.15 if time.monotonic() - start < 5 else 0.5)

    raise TimeoutError("SSH timeout")
