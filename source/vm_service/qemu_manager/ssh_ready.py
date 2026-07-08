import socket
import time
from typing import Callable
import paramiko
import settings
from .crypto import load_pkey


def wait_ssh(
    port: int,
    timeout: int,
    user: str,
    is_vm_alive: Callable[[], bool] | None = None,
    vm_id: str | None = None,
) -> bool:
    """
    Wait until an SSH connection is possible to 127.0.0.1:<port>.
    Preserves the original retry/return semantics (including the attempt>100 early return).
    """
    print("Start the wait_ssh process...")
    start = time.time()

    while time.time() - start < timeout:
        try:
            # 1) TCP open?
            with socket.create_connection(("127.0.0.1", port), timeout=1.0):
                pass
            # 2) SSH auth with supplied key
            pkey = load_pkey(settings.VM_SSH_PRIVKEY)
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

            if vm_id is not None:
                try:
                    from implementations.ssh_cache import (
                        cache_data,
                        finalize_and_cache,
                        write_vm_id_marker,
                    )

                    # Warm the cache exactly once, reusing the connection we just
                    # validated. Later accesses go through cache_ssh_and_sftp, which
                    # only reconnects if the entry is missing or the transport died.
                    cached = cache_data.get(vm_id)
                    if not cached or not cached.get("cli"):
                        finalize_and_cache(vm_id, cli)

                    # Stamp this VM's identity into the guest so consumers can detect
                    # a stale ssh_port that now points at a DIFFERENT VM. Written on
                    # every boot to the current vm_id, so a duplicated disk (which
                    # carries the source's stamp) is corrected here on first boot.
                    write_vm_id_marker(cli, vm_id)
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
