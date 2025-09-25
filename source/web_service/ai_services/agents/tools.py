from __future__ import annotations
from typing import Dict, Any
from vm_manager.models import Container
from vm_manager.vm_client import VMServiceClient, VMUploadFiles, VMFile, SearchRequest
from internal_config.audit import audit_agent_tool


class DedupPolicy:
    def __init__(self):
        self.logs = {}


def _get_service(obj: Container) -> VMServiceClient:
    return VMServiceClient(obj.node)


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
    audit_agent_tool(
        action="agent_tool.read_workspace",
        target_type="container",
        target_id=str(container.container_id),
        message="List directory",
        metadata={"path": path},
        success=True,
    )
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
        audit_agent_tool(
            action="agent_tool.create_file",
            target_type="container",
            target_id=str(container.container_id),
            message="Create file (dedup hit)",
            metadata={"path": subdir},
            success=True,
        )
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
    audit_agent_tool(
        action="agent_tool.create_file",
        target_type="container",
        target_id=str(container.container_id),
        message="File created",
        metadata={"path": subdir},
        success=True,
    )

    dedup.logs[f"create_file_{subdir}"] = resp
    return resp


def read_file(_: DedupPolicy, container: Container, path: str) -> Dict[str, Any]:
    subdir = f"/app/{path}".replace("//", "/").replace("/app/app/", "/app/")
    if path is None or len(path.strip()) == 0:
        subdir = "/app"
    service = _get_service(container)
    resp = service.read_file(str(container.container_id), subdir)
    resp["finished"] = True
    audit_agent_tool(
        action="agent_tool.read_file",
        target_type="container",
        target_id=str(container.container_id),
        message="Read file",
        metadata={"path": subdir},
        success=True,
    )
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
        audit_agent_tool(
            action="agent_tool.create_full_project",
            target_type="container",
            target_id=str(container.container_id),
            message="Create full project (dedup hit)",
            metadata={},
            success=True,
        )
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

    audit_agent_tool(
        action="agent_tool.create_full_project",
        target_type="container",
        target_id=str(container.container_id),
        message="Full project created",
        metadata={},
        success=True,
    )
    return response


def exec_command(_: DedupPolicy, container: Container, command: str) -> Dict[str, Any]:
    service = _get_service(container)
    resp = service.execute_sh(str(container.container_id), command)
    resp["finished"] = True
    audit_agent_tool(
        action="agent_tool.exec_command",
        target_type="container",
        target_id=str(container.container_id),
        message="Exec command",
        metadata={"command": command},
        success=True,
    )
    return resp


def search(
    _: DedupPolicy, container: Container, pattern: str, root: str
) -> Dict[str, Any]:
    service = _get_service(container)
    resp = service.search(
        str(container.container_id),
        SearchRequest(
            pattern=pattern,
            root=root,
            case_insensitive=False,
            max_results_total=250,
            timeout_seconds=5,
        ),
    )
    audit_agent_tool(
        action="agent_tool.search",
        target_type="container",
        target_id=str(container.container_id),
        message="Search in workspace",
        metadata={"pattern": pattern, "root": root},
        success=True,
    )
    return {"response": resp, "finished": True}


def search_on_internet(
    _: DedupPolicy, container: Container, search_query: str
) -> Dict[str, Any]:
    from ddgs import DDGS

    results = DDGS().text(search_query, max_results=5, timeout=5)
    audit_agent_tool(
        target_type="container",
        target_id=str(container.container_id),
        action="agent_tool.search_on_internet",
        message="Web search",
        metadata={"query": search_query},
        success=True,
    )
    return {"response": results, "finished": True}


def read_from_internet(
    _: DedupPolicy, container: Container, url: str
) -> Dict[str, Any]:
    from newspaper import Article

    article = Article(url)
    article.download()
    article.parse()
    audit_agent_tool(
        target_type="container",
        target_id=str(container.container_id),
        action="agent_tool.read_from_internet",
        message="Read from internet",
        metadata={"url": url, "title": article.title},
        success=True,
    )

    return {
        "finished": True,
        "text": article.text,
        "title": article.title,
    }
