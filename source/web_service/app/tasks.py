"""
Celery tasks for heavy or I/O-bound operations.

Notes:
- We keep endpoints/contracts unchanged. For create(), we enqueue template
  application as a background task to avoid blocking the request.
- For write_file, we provide a task that the view can execute synchronously
  via .apply() to preserve the original contract; if you later choose to
  return a task id instead, switch to .delay() and adapt the HTTP response.
"""

from celery import shared_task
from django.conf import settings
from django.shortcuts import get_object_or_404

import paramiko
import os
import shlex

from docker_manager.models import Container, FileTemplate
from docker_manager.usecases.apply_template import _apply_template_to_vm


@shared_task(bind=True, autoretry_for=(Exception,), retry_backoff=True, max_retries=3)
def sync_status():
    from io import StringIO
    from django.core.management import call_command

    buf = StringIO()
    try:
        call_command("vmctl", "sync", stdout=buf)
    except Exception:
        pass


@shared_task(bind=True, autoretry_for=(Exception,), retry_backoff=True, max_retries=3)
def apply_template_to_vm_task(
    self, container_id: int, template_id: int, dest_path: str, clean: bool = True
):
    """
    Apply a file template to a given container VM.
    This is used during container create() to avoid blocking the request.
    """
    container = get_object_or_404(Container, pk=container_id)
    tpl = get_object_or_404(FileTemplate, pk=template_id)
    _apply_template_to_vm(container, tpl, dest_path=dest_path, clean=clean)
    return {"container": container.pk, "template": tpl.pk, "dest_path": dest_path}


@shared_task(bind=True, autoretry_for=(Exception,), retry_backoff=True, max_retries=2)
def sftp_write_file_task(self, container_id: int, path: str, content: str):
    """
    Write a file via SFTP into the VM (mkdir -p for parent dir).
    """
    container = get_object_or_404(Container, pk=container_id)

    k = paramiko.Ed25519Key.from_private_key_file(settings.VM_SSH_PRIVKEY)
    cli = paramiko.SSHClient()
    cli.set_missing_host_key_policy(paramiko.AutoAddPolicy())

    # Infer SSH port from container_id "qemu:<port>" or store port in model if different.
    port = int(container.container_id.split(":")[1])
    cli.connect(
        "127.0.0.1",
        port=port,
        username=settings.VM_SSH_USER,
        pkey=k,
        look_for_keys=False,
    )

    try:
        # Ensure parent directory exists
        dirn = os.path.dirname(path)
        if dirn:
            _, stdout, _ = cli.exec_command(f"mkdir -p {shlex.quote(dirn)}")
            stdout.channel.recv_exit_status()

        sftp = cli.open_sftp()
        try:
            with sftp.file(path, "wb") as wf:
                wf.write(content.encode("utf-8"))
        finally:
            sftp.close()
    finally:
        cli.close()

    return {"path": path, "bytes": len(content.encode("utf-8"))}
