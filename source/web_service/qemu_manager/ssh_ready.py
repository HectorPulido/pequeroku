import socket
import time
from typing import Callable, Optional

import paramiko
from django.conf import settings

from .crypto import _load_pkey


def _wait_ssh(
    port: int,
    timeout: int,
    user: str,
    is_vm_alive: Optional[Callable[[], bool]] = None,
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
                banner_timeout=30,
                auth_timeout=30,
                timeout=5,
                look_for_keys=False,
            )
            cli.close()
            return True
        except Exception as e:
            time.sleep(1.0)
            if str(e).strip() != "":
                print("Error opening ssh", e)
            if is_vm_alive is not None and not is_vm_alive():
                print("QEMU process died while waiting for SSH")
                return False

    raise TimeoutError("SSH timeout")
