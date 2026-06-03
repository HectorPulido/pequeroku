import os
import shlex
import mimetypes
from typing import Any
import paramiko

from models import VMRecord, ListDirItem, FileContent
from .ssh_cache import exec_and_close
from .ssh_pool import borrow


def _execute_list(
    root: str, cli: paramiko.SSHClient, depth: int = 1
) -> list[ListDirItem]:
    items: list[ListDirItem] = []
    try:
        cmd = f"find {shlex.quote(root)} -maxdepth {depth} -printf '%p||%y\\n' 2>/dev/null || true"
        out, _ = exec_and_close(cli, cmd)
        lines = (out.decode() or "").strip().splitlines()

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
    items: list[ListDirItem] = []
    with borrow(container) as conn:
        for root in paths:
            items.extend(_execute_list(root, conn.cli, depth))

    return list(set(items))


def list_dir(container: VMRecord, path: str) -> list[ListDirItem]:
    return list_dirs(container, [path], 1)


def read_file(container: VMRecord, path: str) -> FileContent:
    with borrow(container) as conn:
        sftp = conn.sftp

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


def download_file(vm: VMRecord, path: str) -> dict[str, Any] | None:
    with borrow(vm) as conn:
        sftp = conn.sftp
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
    out, _ = exec_and_close(cli, check_cmd)
    return out.decode().strip() == "OK"


def download_folder(
    vm: VMRecord, root: str, prefer_fmt: str = "zip"
) -> dict[str, Any] | None:
    safe_root = shlex.quote(root)
    base = os.path.basename(root.rstrip("/")) or "archive"

    with borrow(vm) as conn:
        cli = conn.cli
        sftp = conn.sftp
        if not cli or not sftp:
            print("Error generating zip folder", "SSH/SFTP unavailable")
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

        archive_bytes, err_bytes = exec_and_close(cli, cmd)

    if not archive_bytes:
        err = err_bytes.decode(errors="ignore")
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
