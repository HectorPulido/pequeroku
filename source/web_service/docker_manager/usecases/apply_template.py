import os
import stat
import shlex
import paramiko
import posixpath
from django.conf import settings
from docker_manager.models import FileTemplate


def _norm_join(dest_path: str, rel: str) -> str:
    # Siempre tratamos la ruta remota como POSIX
    rel = rel.lstrip("/")  # evitar que te sobrescriba dest si viene con "/"
    fullp = posixpath.normpath(posixpath.join(dest_path, rel))
    # Bloquear traversal accidental
    if not fullp.startswith(dest_path.rstrip("/") + "/") and fullp != dest_path:
        raise ValueError(f"Ruta insegura en template: {rel!r}")
    return fullp


def _sftp_mkdirs(sftp: paramiko.SFTPClient, remote_dir: str):
    # Crear recursivamente, ignorando si existe
    parts = remote_dir.strip("/").split("/")
    cur = "/"
    for p in parts:
        cur = posixpath.join(cur, p)
        try:
            sftp.stat(cur)
        except FileNotFoundError:
            sftp.mkdir(cur)


def _clean_dest(cli: paramiko.SSHClient, dest_path: str):
    # Limpia contenido, incluidos dotfiles
    cmd = (
        f"mkdir -p {shlex.quote(dest_path)} && "
        f"rm -rf {shlex.quote(dest_path)}/* {shlex.quote(dest_path)}/.[!.]* {shlex.quote(dest_path)}/..?* || true"
    )
    cli.exec_command(cmd)


def _apply_template_to_vm(
    container, template: FileTemplate, dest_path="/app", clean=True
):
    """
    Copia los items del FileTemplate al destino, respetando permisos.
    Requiere VM accesible por SSH. Usa VM_SSH_USER/VM_SSH_PRIVKEY.
    """
    # Conexión
    key = paramiko.Ed25519Key.from_private_key_file(settings.VM_SSH_PRIVKEY)
    cli = paramiko.SSHClient()
    cli.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    port = int(container.container_id.split(":")[1])  # qemu:<port>
    cli.connect(
        "127.0.0.1",
        port=port,
        username=settings.VM_SSH_USER,
        pkey=key,
        look_for_keys=False,
    )

    # Asegura destino y opcionalmente limpia
    dest_path = posixpath.normpath(dest_path) or "/app"
    if clean:
        _clean_dest(cli, dest_path)
    else:
        cli.exec_command(f"mkdir -p {shlex.quote(dest_path)}")

    sftp = cli.open_sftp()

    # Crear directorios/archivos
    for it in template.items.all().order_by("order", "path"):
        fullp = _norm_join(dest_path, it.path)  # path seguro
        dirn = posixpath.dirname(fullp)
        if dirn and dirn not in (".", "/"):
            _sftp_mkdirs(sftp, dirn)

        # Escribir archivo
        data = (it.content or "").encode("utf-8")
        with sftp.open(fullp, "wb") as wf:
            wf.write(data)

        # Permisos
        mode = it.mode or 0o644
        try:
            sftp.chmod(fullp, mode)
        except Exception:
            # fallback por shell si el FS remoto lo requiere
            cli.exec_command(f"chmod {oct(mode)} {shlex.quote(fullp)}")

    sftp.close()
    cli.close()
