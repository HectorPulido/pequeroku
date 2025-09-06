"""
Module to apply templates
"""
import os
import shlex
import posixpath
import paramiko

from django.conf import settings

from docker_manager.models import FileTemplate


def _norm_join(dest_path: str, rel: str) -> str:
    # Assure POSIX
    rel = rel.lstrip("/")
    fullp = posixpath.normpath(posixpath.join(dest_path, rel))
    if not fullp.startswith(dest_path.rstrip("/") + "/") and fullp != dest_path:
        raise ValueError(f"Insecure route in template: {rel!r}")
    return fullp


def _sftp_mkdirs(sftp: paramiko.SFTPClient, remote_dir: str):
    # Create if not exist path
    parts = remote_dir.strip("/").split("/")
    cur = "/"
    for p in parts:
        cur = posixpath.join(cur, p)
        try:
            sftp.stat(cur)
        except FileNotFoundError:
            sftp.mkdir(cur)


def _clean_dest(cli: paramiko.SSHClient, dest_path: str):
    # Clean content
    cmd = (
        f"mkdir -p {shlex.quote(dest_path)} && "
        f"rm -rf {shlex.quote(dest_path)}/* "
        f"{shlex.quote(dest_path)}/.[!.]* {shlex.quote(dest_path)}/..?* || true"
    )
    cli.exec_command(cmd)


def _save_file(
    sftp: paramiko.SFTPClient,
    cli: paramiko.SSHClient,
    full_path: str,
    content: str,
    file_mode: int,
):
    dirn = posixpath.dirname(full_path)
    if dirn and dirn not in (".", "/"):
        _sftp_mkdirs(sftp, dirn)

    data = (content or "").encode("utf-8")
    with sftp.open(full_path, "wb") as wf:
        wf.write(data)

    mode = file_mode or 0o644
    try:
        sftp.chmod(full_path, mode)
    except Exception:
        cli.exec_command(f"chmod {oct(mode)} {shlex.quote(full_path)}")


def _prepare_vm_for_transfer(container, dest_path="/app", clean=True):
    key = paramiko.Ed25519Key.from_private_key_file(settings.VM_SSH_PRIVKEY)
    cli = paramiko.SSHClient()
    cli.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    port = int(container.container_id.split(":")[1])
    cli.connect(
        "127.0.0.1",
        port=port,
        username=settings.VM_SSH_USER,
        pkey=key,
        look_for_keys=False,
    )

    dest_path = posixpath.normpath(dest_path) or "/app"
    if clean:
        _clean_dest(cli, dest_path)
    else:
        cli.exec_command(f"mkdir -p {shlex.quote(dest_path)}")

    sftp = cli.open_sftp()

    return sftp, cli


def _apply_template_to_vm(
    container, template: FileTemplate, dest_path="/app", clean=True
):
    """
    Copies the FileTemplate elements to the destination, respecting permissions.
    Requires a VM accessible via SSH. United States VM_SSH_USER/VM_SSH_PRIVKEY.
    """
    sftp, cli = _prepare_vm_for_transfer(container, dest_path, clean)

    for it in template.items.all().order_by("order", "path"):
        fullp = _norm_join(dest_path, it.path)
        _save_file(sftp, cli, fullp, it.content, it.mode)

    sftp.close()
    cli.close()


def apply_ai_generated_project(
    container, ai_generated_code, dest_path="/app", clean=False
):
    """Apply AI generated code on the vm"""

    sftp, cli = _prepare_vm_for_transfer(container, dest_path, clean)

    # Save the ai_generated_code as .txt
    path = "gencode.txt"
    full_path = _norm_join(dest_path, path)

    _save_file(sftp, cli, full_path, ai_generated_code, 0o644)

    # Save the script
    route = os.path.join(
        settings.BASE_DIR, "docker_manager", "usecases", "build_from_gencode.py"
    )

    code = ""
    with open(route, "r", encoding="utf-8") as f:
        code = f.read()

    path = "build_from_gencode.py"
    full_path = _norm_join(dest_path, path)

    _save_file(sftp, cli, full_path, code, 0o644)

    # Exec
    cli.exec_command(f"cd {dest_path} && python3 build_from_gencode.py")
