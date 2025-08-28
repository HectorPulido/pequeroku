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
from docker_manager.usecases.vm_management import QemuSession
from docker_manager.usecases.apply_template import _apply_template_to_vm


@shared_task(bind=True, autoretry_for=(Exception,), retry_backoff=True, max_retries=3)
def sync_status(self):
    from io import StringIO
    from django.core.management import call_command

    buf = StringIO()
    try:
        call_command("vmctl", "sync", stdout=buf)
    except Exception:
        pass


@shared_task(bind=True, autoretry_for=(Exception,), retry_backoff=True, max_retries=3)
def create_vm_first_time(self, container_id):
    c = get_object_or_404(Container, pk=container_id)

    # If QemuSession internally boots / attaches, we let it handle its own lifecycle.
    try:
        QemuSession(c, on_line=None, on_close=None)
    except Exception:
        # Don't fail creation if session boot attach fails; controller can handle retries.
        pass

    # Optionally apply default template (move heavy I/O to Celery)
    slug = getattr(settings, "DEFAULT_TEMPLATE_SLUG", None)
    dest = getattr(settings, "DEFAULT_TEMPLATE_DEST", "/app")
    clean = getattr(settings, "DEFAULT_TEMPLATE_CLEAN", True)

    if slug:
        # Try to find the specific template; fallback to the latest one if missing.
        tpl = FileTemplate.objects.filter(slug=slug).first()
        if not tpl:
            tpl = FileTemplate.objects.order_by("-updated_at").first()

        if tpl:
            # Fire-and-forget: do not block creation; contract stays the same.
            apply_template_to_vm_task.delay(
                container_id=c.pk,
                template_id=tpl.pk,
                dest_path=dest,
                clean=bool(clean),
            )


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


@shared_task(bind=True, autoretry_for=(Exception,), retry_backoff=True, max_retries=2)
def send_command(self, container_id, command):
    c = get_object_or_404(Container, pk=container_id)
    try:
        sess = QemuSession(c, on_line=None, on_close=None)
        sess.send(command)
    except Exception:
        pass
