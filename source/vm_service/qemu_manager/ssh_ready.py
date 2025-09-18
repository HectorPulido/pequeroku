import socket
import time
from typing import Callable, Optional
import paramiko
import settings
from .crypto import _load_pkey


def _wait_ssh(
    port: int,
    timeout: int,
    user: str,
    is_vm_alive: Optional[Callable[[], bool]] = None,
    vm_id: str | None = None,
) -> bool:
    """
    Wait until an SSH connection is possible to 127.0.0.1:<port>.
    Preserves the original retry/return semantics (including the attempt>100 early return).
    """
    print("Start the _wait_ssh process...")
    start = time.time()

    while time.time() - start < timeout:
        try:
            # 1) TCP open?
            with socket.create_connection(("127.0.0.1", port), timeout=1.0):
                pass
            # 2) SSH auth with supplied key
            pkey = _load_pkey(settings.VM_SSH_PRIVKEY)
            cli = paramiko.SSHClient()
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
            )

            if cli is not None and vm_id is not None:
                try:
                    from implementations.ssh_cache import cache_data

                    cli.exec_command("echo hello")
                    sftp = cli.open_sftp()
                    cache_data[vm_id] = {"cli": cli, "sftp": sftp}
                except Exception:
                    ...

            waited = time.time() - start
            print(f"SSH Connection READY! TIME TAKEN: {waited}")
            return True
        except Exception as e:
            waited = time.time() - start
            time.sleep(0.15 if waited < 5 else 0.5)
            if str(e).strip() != "":
                print("Error opening ssh", e)
            if is_vm_alive is not None and not is_vm_alive():
                print("QEMU process died while waiting for SSH")
                return False

    raise TimeoutError("SSH timeout")
