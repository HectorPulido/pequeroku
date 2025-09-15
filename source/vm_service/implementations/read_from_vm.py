import os
import shlex


from qemu_manager.models import VMRecord, ListDirItem, FileContent
from .ssh_cache import open_ssh_and_sftp


def list_dir(container: VMRecord, root: str = "/app") -> list[ListDirItem]:
    (
        _,
        cli,
    ) = open_ssh_and_sftp(container, open_sftp=False)

    items: list[ListDirItem] = []
    try:
        cmd = f"find {shlex.quote(root)} -maxdepth 2 -printf '%p||%y\\n' 2>/dev/null || true"
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


def read_file(container: VMRecord, path: str):
    sftp, cli = open_ssh_and_sftp(container, True)

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
