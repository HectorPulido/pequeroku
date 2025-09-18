from __future__ import annotations
from typing import Dict, Any
from vm_manager.models import Container, Node
from vm_manager.vm_client import VMServiceClient, VMUploadFiles, VMFile


class DedupPolicy:
    logs = {}


def _get_service(obj: Container) -> VMServiceClient:
    node: Node = obj.node
    return VMServiceClient(
        base_url=str(node.node_host),
        token=str(node.auth_token),
    )


class ToolError(Exception):
    """Raised for user-facing tool errors (validation, not-found, etc.)."""


def read_workspace(
    _: DedupPolicy | None,
    container: Container,
    subdir: str | None = None,
) -> Dict[str, Any]:
    path = f"/app/{subdir}".replace("//", "/").replace("/app/app/", "/app/")
    if subdir is None or len(subdir.strip()) == 0:
        path = "/app"
    service = _get_service(container)
    resp = service.list_dir(str(container.container_id), path)
    return {"path": path, "entries": resp, "finished": True}


def create_file(
    dedup: DedupPolicy,
    container: Container,
    path: str,
    content: str,
) -> Dict[str, Any]:
    subdir = f"/app/{path}".replace("//", "/").replace("/app/app/", "/app/")
    if path is None or len(path.strip()) == 0:
        subdir = "/app"

    if f"create_file_{subdir}" in dedup.logs:
        print("Redup policy applied")
        dedup.logs[f"create_file_{subdir}"]["dedup"] = True
        return dedup.logs[f"create_file_{subdir}"]

    service = _get_service(container)
    resp = service.upload_files(
        str(container.container_id),
        VMUploadFiles(
            dest_path="/",
            clean=False,
            files=[VMFile(path=subdir, text=content)],
        ),
    )
    resp["finished"] = True

    dedup.logs[f"create_file_{subdir}"] = resp
    return resp


def read_file(_: DedupPolicy, container: Container, path: str) -> Dict[str, Any]:
    subdir = f"/app/{path}".replace("//", "/").replace("/app/app/", "/app/")
    if path is None or len(path.strip()) == 0:
        subdir = "/app"
    service = _get_service(container)
    resp = service.read_file(str(container.container_id), subdir)
    resp["finished"] = True
    return resp


def create_full_project(
    dedup: DedupPolicy, container: Container, full_description: str
) -> Dict[str, Any]:
    import os
    from django.conf import settings
    from internal_config.models import Config

    from .schemas import PROJECT_GENERATION_PROMPT
    from ..utils import _get_openai_client

    if "create_full_project" in dedup.logs:
        print("Redup policy applied")
        dedup.logs["create_full_project"]["dedup"] = True
        return dedup.logs["create_full_project"]

    open_ai_data = Config.get_config_values(
        ["openai_api_key", "openai_api_url", "openai_model"]
    )

    openai = _get_openai_client(open_ai_data)
    openai_model: str = open_ai_data.get("openai_model") or "gpt-4"

    prompt_prepared = PROJECT_GENERATION_PROMPT.replace(
        "{objectives}", full_description
    )

    response = openai.chat.completions.create(
        messages=[{"role": "system", "content": prompt_prepared}],
        model=openai_model,
        stream=False,
    )

    generated_content = response.choices[0].message.content

    service = _get_service(container)

    route = os.path.join(
        settings.BASE_DIR, "ai_services", "gencode_scripts", "build_from_gencode.py"
    )

    code = ""
    with open(route, "r", encoding="utf-8") as f:
        code = f.read()

    response = service.upload_files(
        str(container.container_id),
        VMUploadFiles(
            dest_path="/app",
            clean=True,
            files=[
                VMFile(
                    mode=0o644,
                    path="build_from_gencode.py",
                    text=code,
                ),
                VMFile(
                    mode=0o644,
                    path="gencode.txt",
                    text=generated_content,
                ),
            ],
        ),
    )

    if not response:
        print("Could not upload files...")

    response = service.execute_sh(
        str(container.container_id), "cd /app && python3 build_from_gencode.py"
    )
    response["finished"] = True
    response["workspace"] = read_workspace(None, container)

    dedup.logs["create_file"] = response

    return response


def exec_command(_: DedupPolicy, container: Container, command: str) -> Dict[str, Any]:
    service = _get_service(container)
    resp = service.execute_sh(str(container.container_id), command)
    resp["finished"] = True
    return resp
