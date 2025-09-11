import posixpath
import shlex
import paramiko
import settings
from qemu_manager.models import VMUploadFiles, VMRecord, ElementResponse


def open_ssh_and_sftp(container: VMRecord, open_sftp=False):
    key = paramiko.Ed25519Key.from_private_key_file(settings.VM_SSH_PRIVKEY)
    cli = paramiko.SSHClient()
    cli.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    port = container.ssh_port or 22

    cli.connect(
        "127.0.0.1",
        port=port,
        username=container.ssh_user,
        pkey=key,
        look_for_keys=False,
    )

    sftp = None

    if open_sftp:
        sftp = cli.open_sftp()

    return sftp, cli


def _norm_join(dest_path: str, rel: str) -> str:
    # Assure POSIX
    rel = rel.lstrip("/")
    fullp = posixpath.normpath(posixpath.join(dest_path, rel))
    if not fullp.startswith(dest_path.rstrip("/") + "/") and fullp != dest_path:
        raise ValueError(f"Insecure route in template: {rel!r}")
    return fullp


def _clean_dest(cli: paramiko.SSHClient, dest_path: str):
    cmd = (
        f"mkdir -p {shlex.quote(dest_path)} && "
        f"rm -rf {shlex.quote(dest_path)}/* "
        f"{shlex.quote(dest_path)}/.[!.]* {shlex.quote(dest_path)}/..?* || true"
    )
    cli.exec_command(cmd)


def _prepare_vm_for_transfer(container: VMRecord, dest_path="/app", clean=True):
    sftp, cli = open_ssh_and_sftp(container, True)

    dest_path = posixpath.normpath(dest_path) or "/app"
    if clean:
        _clean_dest(cli, dest_path)
    else:
        cli.exec_command(f"mkdir -p {shlex.quote(dest_path)}")

    return sftp, cli


def _sftp_mkdirs(sftp: paramiko.SFTPClient, remote_dir: str):
    # Create if not exist path
    parts = remote_dir.strip("/").split("/")
    cur = "/"
    # pyrefly: ignore  # bad-assignment
    for p in parts:
        cur = posixpath.join(cur, p)
        try:
            sftp.stat(cur)
        except FileNotFoundError:
            sftp.mkdir(cur)


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


def send_files(container: VMRecord, files: VMUploadFiles):
    """
    Copies the FileTemplate elements to the destination, respecting permissions.
    Requires a VM accessible via SSH. United States VM_SSH_USER/VM_SSH_PRIVKEY.
    """

    clean = files.clean or False
    dest_path = files.dest_path or "/app"

    try:
        sftp, cli = _prepare_vm_for_transfer(container, dest_path, clean)

        if not sftp:
            return ElementResponse(ok=False, reason="No sftp ready")

        for it in files.files:
            fullp = _norm_join(dest_path, it.path)
            # pyrefly: ignore  # bad-argument-type
            _save_file(sftp, cli, fullp, it.content, it.mode)

        # pyrefly: ignore  # missing-attribute
        sftp.close()
        cli.close()
    except Exception as e:
        return ElementResponse(ok=False, reason=str(e))
    return ElementResponse(ok=True)


def create_dir(container: VMRecord, path: str = "/app"):
    _, cli = open_ssh_and_sftp(container, open_sftp=False)
    try:
        _, __, ___ = cli.exec_command(f"mkdir -p {shlex.quote(path)}")
        cli.close()
    except Exception as e:
        cli.close()
        return ElementResponse(ok=False, reason=str(e))

    return ElementResponse(ok=True)
