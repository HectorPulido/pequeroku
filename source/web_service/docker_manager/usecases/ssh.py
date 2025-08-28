"""
Small SSH helpers to keep the views lean and consistent.
"""

import os
import shlex
import paramiko
from django.conf import settings


def _build_ssh_client(container):
    """
    Build and return a connected paramiko.SSHClient for a given container.
    Assumes container.container_id encodes the port as '...:<port>'.
    """
    k = paramiko.Ed25519Key.from_private_key_file(settings.VM_SSH_PRIVKEY)
    cli = paramiko.SSHClient()
    cli.set_missing_host_key_policy(paramiko.AutoAddPolicy())

    port = int(container.container_id.split(":")[1])
    cli.connect(
        "127.0.0.1",
        port=port,
        username=settings.VM_SSH_USER,
        pkey=k,
        look_for_keys=False,
    )
    return cli


def open_ssh_and_sftp(container, open_sftp=True):
    """
    Return (cli, sftp) where cli is SSHClient and sftp is an SFTPClient or None.
    Caller is responsible for closing both (sftp first, then cli).
    """
    cli = _build_ssh_client(container)
    sftp = cli.open_sftp() if open_sftp else None
    return cli, sftp


def ensure_remote_dir(cli, path: str):
    """
    Ensure a directory exists on remote host (mkdir -p).
    """
    if not path:
        return
    _, stdout, _ = cli.exec_command(f"mkdir -p {shlex.quote(path)}")
    stdout.channel.recv_exit_status()
