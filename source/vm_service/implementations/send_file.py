import time
import posixpath
import shlex
import paramiko
from qemu_manager.models import VMUploadFiles, VMRecord, ElementResponse
from .ssh_cache import open_ssh_and_sftp


def _run_and_check(cli: paramiko.SSHClient, cmd: str, timeout: float | None = None):
    stdin, stdout, stderr = cli.exec_command(cmd, timeout=timeout)
    exit_status = stdout.channel.recv_exit_status()
    if exit_status != 0:
        err = stderr.read().decode("utf-8", "ignore")
        out = stdout.read().decode("utf-8", "ignore")
        raise RuntimeError(
            f"Command failed ({exit_status}): {cmd}\nSTDERR: {err}\nSTDOUT: {out}"
        )


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
    _run_and_check(cli, cmd)


def _prepare_vm_for_transfer(container: VMRecord, dest_path="/app", clean=True):
    sftp, cli = open_ssh_and_sftp(container, True)

    dest_path = sftp.normalize(dest_path or "/app")
    if clean:
        _clean_dest(cli, dest_path)
    else:
        _run_and_check(cli, f"mkdir -p {shlex.quote(dest_path)}")
    return sftp, cli, dest_path


def _sftp_mkdirs(sftp: paramiko.SFTPClient, remote_dir: str):
    parts = remote_dir.strip("/").split("/")
    cur = "/"
    for p in parts:
        cur = posixpath.join(cur, p)
        try:
            sftp.stat(cur)
        except (IOError, OSError) as e:
            # ENOENT: no existe -> crearlo
            if getattr(e, "errno", None) in (errno.ENOENT, 2):
                sftp.mkdir(cur)
            else:
                raise


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
    time.sleep(0.02)

    data = (content or "").encode("utf-8")
    with sftp.open(full_path, "wb") as wf:
        wf.write(data)
    time.sleep(0.02)

    mode = file_mode or 0o644
    try:
        sftp.chmod(full_path, mode)
    except Exception:
        _run_and_check(cli, f"chmod {oct(mode)} {shlex.quote(full_path)}")


def send_files(container: VMRecord, files: VMUploadFiles):
    """
    Copies the FileTemplate elements to the destination, respecting permissions.
    Requires a VM accessible via SSH. United States VM_SSH_USER/VM_SSH_PRIVKEY.
    """

    clean = files.clean or False
    dest_path = files.dest_path or "/app"

    try:
        sftp, cli, dest_path = _prepare_vm_for_transfer(container, dest_path, clean)

        if not sftp:
            return ElementResponse(ok=False, reason="No sftp ready")

        failed = []
        for it in files.files:
            try:
                fullp = _norm_join(dest_path, it.path)
                _save_file(sftp, cli, fullp, it.content, it.mode)
            except Exception as e:
                failed.append({"path": it.path, "reason": str(e)})

        if failed:
            return ElementResponse(ok=False, reason=f"Failed files: {failed}")
        return ElementResponse(ok=True)

    except Exception as e:
        return ElementResponse(ok=False, reason=str(e))


def create_dir(container: VMRecord, path: str = "/app"):
    _, cli = open_ssh_and_sftp(container, open_sftp=False)
    try:
        _run_and_check(cli, f"mkdir -p {shlex.quote(path)}")
    except Exception as e:
        return ElementResponse(ok=False, reason=str(e))

    return ElementResponse(ok=True)
