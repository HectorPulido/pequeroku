from __future__ import annotations
import time
from typing import cast
from vm_manager.models import Container, Node
from vm_manager.vm_client import (
    VMPaths,
    VMServiceClient,
    VMUploadFiles,
    VMFile,
    SearchRequest,
)
from internal_config.audit import audit_agent_tool


class DedupPolicy:
    def __init__(self):
        self.logs: dict[str, dict[str, object]] = {}


def _get_service(obj: Container) -> VMServiceClient:
    return VMServiceClient(cast(Node, obj.node))


class ToolError(Exception):
    """Raised for user-facing tool errors (validation, not-found, etc.)."""


def read_workspace(
    _: DedupPolicy | None,
    container: Container,
    subdir: str | None = None,
) -> dict[str, object]:
    start = time.monotonic()
    path = f"/app/{subdir}".replace("//", "/").replace("/app/app/", "/app/")
    if subdir is None or len(subdir.strip()) == 0:
        path = "/app"

    container_id: str = cast(str, container.container_id)

    service = _get_service(container)
    resp = service.list_dirs(container_id, VMPaths(paths=[path], depth=5))
    duration_ms = int((time.monotonic() - start) * 1000)
    audit_agent_tool(
        action="agent_tool.read_workspace",
        target_type="container",
        target_id=container_id,
        message="List directory",
        metadata={"path": path, "duration_ms": duration_ms},
        success=True,
    )
    return {"path": path, "entries": resp, "finished": True}


def create_file(
    dedup: DedupPolicy,
    container: Container,
    path: str,
    content: str,
) -> dict[str, object]:
    start = time.monotonic()
    subdir = f"/app/{path}".replace("//", "/").replace("/app/app/", "/app/")
    if len(path.strip()) == 0:
        subdir = "/app"

    container_id: str = cast(str, container.container_id)

    if f"create_file_{subdir}" in dedup.logs:
        print("Redup policy applied")
        dedup.logs[f"create_file_{subdir}"]["dedup"] = True
        duration_ms = int((time.monotonic() - start) * 1000)
        audit_agent_tool(
            action="agent_tool.create_file",
            target_type="container",
            target_id=container_id,
            message="Create file (dedup hit)",
            metadata={"path": subdir, "duration_ms": duration_ms},
            success=True,
        )
        return dedup.logs[f"create_file_{subdir}"]

    service = _get_service(container)
    resp = service.upload_files(
        container_id,
        VMUploadFiles(
            dest_path="/",
            clean=False,
            files=[VMFile(path=subdir, text=content)],
        ),
    )
    resp["finished"] = True
    duration_ms = int((time.monotonic() - start) * 1000)
    audit_agent_tool(
        action="agent_tool.create_file",
        target_type="container",
        target_id=container_id,
        message="File created",
        metadata={"path": subdir, "duration_ms": duration_ms},
        success=True,
    )

    dedup.logs[f"create_file_{subdir}"] = resp
    return resp


def read_file(_: DedupPolicy, container: Container, path: str) -> dict[str, object]:
    start = time.monotonic()
    subdir = f"/app/{path}".replace("//", "/").replace("/app/app/", "/app/")
    if len(path.strip()) == 0:
        subdir = "/app"

    container_id: str = cast(str, container.container_id)

    service = _get_service(container)
    resp = service.read_file(container_id, subdir)
    resp["finished"] = True
    duration_ms = int((time.monotonic() - start) * 1000)
    audit_agent_tool(
        action="agent_tool.read_file",
        target_type="container",
        target_id=container_id,
        message="Read file",
        metadata={"path": subdir, "duration_ms": duration_ms},
        success=True,
    )
    return resp


def create_full_project(
    dedup: DedupPolicy, container: Container, full_description: str
) -> dict[str, object]:
    import os
    from django.conf import settings
    from internal_config.models import Config

    from .schemas import PROJECT_GENERATION_PROMPT
    from ..utils import get_openai_client

    start = time.monotonic()

    container_id: str = cast(str, container.container_id)

    if "create_full_project" in dedup.logs:
        print("Redup policy applied")
        dedup.logs["create_full_project"]["dedup"] = True
        duration_ms = int((time.monotonic() - start) * 1000)
        audit_agent_tool(
            action="agent_tool.create_full_project",
            target_type="container",
            target_id=container_id,
            message="Create full project (dedup hit)",
            metadata={"duration_ms": duration_ms},
            success=True,
        )
        return dedup.logs["create_full_project"]

    open_ai_data = Config.get_config_values(
        ["openai_api_key", "openai_api_url", "openai_model"]
    )

    openai = get_openai_client(open_ai_data)
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
        cast(str, settings.BASE_DIR),
        "ai_services",
        "gencode_scripts",
        "build_from_gencode.py",
    )

    code = ""
    with open(route, "r", encoding="utf-8") as f:
        code = f.read()

    response = service.upload_files(
        container_id,
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
        container_id, "cd /app && python3 build_from_gencode.py"
    )
    response["finished"] = True
    response["workspace"] = read_workspace(None, container)

    dedup.logs["create_full_project"] = response

    duration_ms = int((time.monotonic() - start) * 1000)
    audit_agent_tool(
        action="agent_tool.create_full_project",
        target_type="container",
        target_id=container_id,
        message="Full project created",
        metadata={"duration_ms": duration_ms},
        success=True,
    )
    return response


def _classify_risk(command: str) -> str:
    if not command:
        return "LOW"
    high_markers = [
        "docker push",
        "kubectl",
        "helm ",
        " rm -rf /",
        "curl ",
        "| sh",
        "systemctl",
        "iptables",
        "shutdown",
        "reboot",
    ]
    if any(m in command for m in high_markers):
        return "HIGH"
    medium_markers = [
        "apt-get ",
        "pip install",
        "npm install",
        "docker build",
        "docker compose up",
        "pytest",
        "make ",
    ]
    if any(m in command for m in medium_markers):
        return "MEDIUM"
    return "LOW"


def exec_command(
    _: DedupPolicy, container: Container, command: str
) -> dict[str, object]:
    start = time.monotonic()
    risk_level = _classify_risk(command)
    service = _get_service(container)

    container_id: str = cast(str, container.container_id)

    resp = service.execute_sh(container_id, command)
    resp["finished"] = True
    duration_ms = int((time.monotonic() - start) * 1000)
    audit_agent_tool(
        action="agent_tool.exec_command",
        target_type="container",
        target_id=container_id,
        message="Exec command",
        metadata={
            "command": command,
            "risk_level": risk_level,
            "duration_ms": duration_ms,
        },
        success=True,
    )
    return resp


def search(
    _: DedupPolicy, container: Container, pattern: str, root: str
) -> dict[str, object]:
    start = time.monotonic()
    service = _get_service(container)

    container_id: str = cast(str, container.container_id)

    resp = service.search(
        container_id,
        SearchRequest(
            pattern=pattern,
            root=root,
            case_insensitive=False,
            max_results_total=250,
            timeout_seconds=5,
        ),
    )
    duration_ms = int((time.monotonic() - start) * 1000)
    audit_agent_tool(
        action="agent_tool.search",
        target_type="container",
        target_id=container_id,
        message="Search in workspace",
        metadata={"pattern": pattern, "root": root, "duration_ms": duration_ms},
        success=True,
    )
    return {"response": resp, "finished": True}


def search_on_internet(
    _: DedupPolicy, container: Container, search_query: str
) -> dict[str, object]:
    start = time.monotonic()
    from ddgs import DDGS

    container_id: str = cast(str, container.container_id)

    results = list(DDGS().text(search_query, max_results=5, timeout=5))
    duration_ms = int((time.monotonic() - start) * 1000)
    audit_agent_tool(
        target_type="container",
        target_id=container_id,
        action="agent_tool.search_on_internet",
        message="Web search",
        metadata={"query": search_query, "duration_ms": duration_ms},
        success=True,
    )
    return {"response": results, "finished": True}


def read_from_internet(
    _: DedupPolicy, container: Container, url: str
) -> dict[str, object]:
    start = time.monotonic()
    from newspaper import Article

    container_id: str = cast(str, container.container_id)

    ok: bool = True
    title: str | None = None
    text: str = ""
    error: str | None = None
    try:
        article = Article(url)
        article.download()
        article.parse()
        title = cast(str, article.title or "")
        text = cast(str, article.text or "")
    except Exception as e:
        ok = False
        error = f"{e.__class__.__name__}: {e}"
        title = title or ""
        text = text or ""
    duration_ms = int((time.monotonic() - start) * 1000)
    audit_agent_tool(
        target_type="container",
        target_id=container_id,
        action="agent_tool.read_from_internet",
        message="Read from internet",
        metadata=(
            {"url": url, "title": title, "error": error, "duration_ms": duration_ms}
            if not ok
            else {"url": url, "title": title, "duration_ms": duration_ms}
        ),
        success=ok,
    )

    # Truncate very long content to avoid overwhelming the caller
    max_len = 8000
    if len(text) > max_len:
        text = text[:max_len]

    result: dict[str, bool | str | None] = {
        "finished": True,
        "text": text,
        "title": title,
    }
    if not ok:
        result["error"] = error
    return cast(dict[str, object], result)
