import os
import shlex
import mimetypes
import paramiko

from qemu_manager.models import VMRecord, ListDirItem, FileContent
from .ssh_cache import open_ssh, open_sftp


def _execute_list(root: str, cli: paramiko.SSHClient, depth: int = 1):
    items: list[ListDirItem] = []
    try:
        cmd = f"find {shlex.quote(root)} -maxdepth {depth} -printf '%p||%y\\n' 2>/dev/null || true"
        _, stdout, _ = cli.exec_command(cmd)
        lines = (stdout.read().decode() or "").strip().splitlines()

        for ln in lines:
            if "||" not in ln:
                continue
            p, t = ln.split("||", 1)
            base = os.path.basename(p.rstrip("/")) or p
            items.append(
                ListDirItem(
                    path=p,
                    name=base,
                    path_type="directory" if t == "d" else "file",
                )
            )
    except Exception as e:
        print("Exception listing dir ", e)

    return items


def list_dirs(container: VMRecord, paths: list[str], depth: int) -> list[ListDirItem]:
    cli = open_ssh(container)

    items: list[ListDirItem] = []
    for root in paths:
        items.extend(_execute_list(root, cli, depth))

    return list(set(items))


def list_dir(container: VMRecord, path: str) -> list[ListDirItem]:
    return list_dirs(container, [path], 1)


def read_file(container: VMRecord, path: str):
    sftp = open_sftp(container)

    data = ""
    if not sftp:
        return FileContent(
            name=path.split("/")[-1], content=data, length=len(data), found=False
        )

    try:
        # pyrefly: ignore  # missing-attribute
        with sftp.file(path, "rb") as rf:
            data = rf.read().decode("utf-8", errors="ignore")
    except Exception:
        return FileContent(
            name=path.split("/")[-1], content=data, length=len(data), found=False
        )

    return FileContent(
        name=path.split("/")[-1], content=data, length=len(data), found=True
    )


def download_file(vm: VMRecord, path: str):
    sftp = open_sftp(vm)
    if not sftp:
        print("Issue downloading...", "issue with sftp")
        return None

    try:
        st = sftp.stat(path)
    except Exception as e:
        print("Issue downloading... File not found", e)
        return None
    if str(st.st_mode).startswith("4"):
        print("Issue downloading...", "Path is a directory; use /download-folder")
        return None

    try:
        # pyrefly: ignore  # missing-attribute
        with sftp.file(path, "rb") as rf:
            data: bytes = rf.read()
    except Exception as e:
        print("Issue downloading...", f"Cannot open: {path}", e)
        return None

    name = os.path.basename(path) or "download"
    media_type = mimetypes.guess_type(name)[0] or "application/octet-stream"
    headers = {"Content-Disposition": f'attachment; filename="{name}"'}
    return {
        "content": data,
        "media_type": media_type,
        "headers": headers,
    }


def _zip_available(cli: paramiko.SSHClient) -> bool:
    check_cmd = "sh -lc 'command -v zip >/dev/null 2>&1 && echo OK || echo NO'"
    _, out, _ = cli.exec_command(check_cmd)
    return out.read().decode().strip() == "OK"


def download_folder(vm: VMRecord, root: str, prefer_fmt: str = "zip"):
    cli = open_ssh(vm)
    if not cli:
        print("Error generating zip folder", "SSH unavailable")
        return None

    safe_root = shlex.quote(root)
    base = os.path.basename(root.rstrip("/")) or "archive"

    sftp = open_sftp(vm)
    if not sftp:
        print("Error generating zip folder", "SFTP unavailable")
        return None
    try:
        _ = sftp.stat(root)
    except Exception as e:
        print("Error generating zip folder", f"Directory not found: {root}", e)
        return None

    fmt = prefer_fmt
    if fmt == "zip" and not _zip_available(cli):
        fmt = "tar.gz"

    if fmt == "zip":
        cmd = f"sh -lc 'cd {safe_root} && zip -r - . 2>/dev/null'"
        media_type = "application/zip"
        filename = f"{base}.zip"
    elif fmt == "tar.gz":
        cmd = f"sh -lc 'tar -C {safe_root} -czf - . 2>/dev/null'"
        media_type = "application/gzip"
        filename = f"{base}.tar.gz"
    else:
        print("Error generating zip folder", "Invalid format")
        return None

    _, stdout, stderr = cli.exec_command(cmd)

    archive_bytes: bytes = stdout.read()
    if not archive_bytes:
        err = stderr.read().decode(errors="ignore")
        print(
            "Error generating zip folder", f"Pack command returned empty output. {err}"
        )
        return None

    headers = {"Content-Disposition": f'attachment; filename="{filename}"'}

    return {
        "content": archive_bytes,
        "media_type": media_type,
        "headers": headers,
    }
