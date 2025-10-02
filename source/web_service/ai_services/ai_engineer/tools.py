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

from ai_services.agents import DedupPolicy, ToolResult
from asgiref.sync import sync_to_async


def _get_service(obj: Container) -> VMServiceClient:
    return VMServiceClient(cast(Node, obj.node))


@sync_to_async
def read_workspace(
    dedup_policy: DedupPolicy | None,
    container: Container,
    subdir: str | None = None,
) -> ToolResult:
    start = time.monotonic()
    path = f"/app/{subdir}".replace("//", "/").replace("/app/app", "/app")
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


@sync_to_async
def create_file(
    dedup_policy: DedupPolicy,
    container: Container,
    path: str,
    content: str,
) -> ToolResult:
    start = time.monotonic()
    subdir = f"/app/{path}".replace("//", "/").replace("/app/app/", "/app/")
    if len(path.strip()) == 0:
        subdir = "/app"

    container_id: str = cast(str, container.container_id)

    if f"create_file_{subdir}" in dedup_policy.logs:
        print("Redup policy applied")
        dedup_policy.logs[f"create_file_{subdir}"]["dedup"] = True
        duration_ms = int((time.monotonic() - start) * 1000)
        audit_agent_tool(
            action="agent_tool.create_file",
            target_type="container",
            target_id=container_id,
            message="Create file (dedup hit)",
            metadata={"path": subdir, "duration_ms": duration_ms},
            success=True,
        )
        return dedup_policy.logs[f"create_file_{subdir}"]

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

    dedup_policy.logs[f"create_file_{subdir}"] = resp
    return resp


@sync_to_async
def read_file(dedup_policy: DedupPolicy, container: Container, path: str) -> ToolResult:
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


PROJECT_GENERATION_PROMPT = """
Your task is to create a minimum viable product (MVP) application that achieves the following objectives:

<objective>
{objectives}
</objective>

Additionally:
The target OS is Debian, so be careful with details like preferring "python3" instead of "python", for example.

Instructions (process you must follow):

1. Plan and structure your approach: Think carefully about how you will write the required code. Document and explain your reasoning.
2. Write the code: Implement the solution as normal, and explain what you are doing.
3. Review your code: Analyze potential issues and risks in your implementation. Document this review.
4. Iterate if needed: If problems are found, go back to step 1 and refine your approach.
5. Follow the steps in order: You must complete at least one full cycle of steps 1–4 before moving forward. Skipping directly to step 6 is not allowed.
6. Finalize and export: Once you are confident the code works, finish with `---HERE-YAML--` and then immediately output the complete project in YAML format, structured like this:

<example>
...
ports:
    - "8080:8080"
environment:
    - PORT=8080

---HERE-YAML--

project: bottle-demo
description: "Small web server with Bottle, HTML, Dockerfile, and Docker Compose"
files:
  - path: app/main.py
    mode: "0644"
    text: |-
      import os
      from bottle import Bottle, static_file, template

      app = Bottle()

      from bottle import TEMPLATE_PATH
      TEMPLATE_PATH.insert(0, os.path.join(os.path.dirname(__file__), "..", "templates"))

      STATIC_DIR = os.path.join(os.path.dirname(__file__), "..", "static")

      @app.route("/")
      def index():
          return template("index", name="Bottle Demo")

      @app.route("/static/<filepath:path>")
      def server_static(filepath):
          return static_file(filepath, root=STATIC_DIR)

      if __name__ == "__main__":
          port = int(os.getenv("PORT", "8080"))
          app.run(host="0.0.0.0", port=port, debug=True, reloader=False)

  - path: templates/index.tpl
    mode: "0644"
    text: |-
      <!doctype html>
      <html lang="en">
        <head>
          <meta charset="utf-8" />
          <meta name="viewport" content="width=device-width, initial-scale=1" />
          <title>{{name}}</title>
        </head>
        <body>
          <main>
            <h1>{{name}}</h1>
            <p>Hello from Bottle running in Docker! 🚀</p>
            <p>Server time: {{!import time; time.strftime('%Y-%m-%d %H:%M:%S')}}</p>
            <p><a href="https://bottlepy.org/docs/dev/">Bottle Docs</a></p>
          </main>
        </body>
      </html>

  - path: requirements.txt
    mode: "0644"
    text: |-
      bottle

  - path: Dockerfile
    mode: "0644"
    text: |-
      FROM python:3.12-slim

      ENV PYTHONDONTWRITEBYTECODE=1 \
          PYTHONUNBUFFERED=1

      WORKDIR /app

      RUN apt-get update && apt-get install -y --no-install-recommends \
          ca-certificates \
          && rm -rf /var/lib/apt/lists/*

      COPY requirements.txt ./requirements.txt
      RUN pip install --no-cache-dir -r requirements.txt

      # Copy the rest of the project
      COPY . .

      EXPOSE 8080

      CMD ["python", "app/main.py"]

  - path: docker-compose.yml
    mode: "0644"
    text: |-
      services:
        web:
          build: .
          container_name: bottle-demo
          ports:
            - "8080:8080"
          environment:
            - PORT=8080

  - path: readme.txt
    mode: "0644"
    text: |-
      This is a simple project that uses Bottle and is containerized.

  - path: config.json
    mode: "0644"
    text: |-
      {"run": "docker compose down ; docker compose up -d --build"}
</example>

Additional notes:

* Notice that the files `readme.txt` and `config.json` must always be included, especially `config.json`, which should contain the `"run"` field with the command needed to run the project.
* The project does not need to be dockerized unless the objective explicitly requires it.
* After the `---HERE-YAML--` separator, do not write anything except the YAML file.
* The YAML must be valid and clean; do not include Markdown formatting (no bold/italics) or code fences (```) either.
* Do not include titles or anything other than YAML after the ---HERE-YAML-- line.
* If you want to explain something or add comments, place them in `readme.txt` or before the `---HERE-YAML--`, never after.
"""


@sync_to_async
def create_full_project(
    dedup_policy: DedupPolicy, container: Container, full_description: str
) -> ToolResult:
    import os
    from django.conf import settings
    from internal_config.models import Config

    from ..utils import get_openai_client

    start = time.monotonic()

    container_id: str = cast(str, container.container_id)

    if "create_full_project" in dedup_policy.logs:
        print("Redup policy applied")
        dedup_policy.logs["create_full_project"]["dedup"] = True
        duration_ms = int((time.monotonic() - start) * 1000)
        audit_agent_tool(
            action="agent_tool.create_full_project",
            target_type="container",
            target_id=container_id,
            message="Create full project (dedup hit)",
            metadata={"duration_ms": duration_ms},
            success=True,
        )
        return dedup_policy.logs["create_full_project"]

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

    dedup_policy.logs["create_full_project"] = response

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


@sync_to_async
def exec_command(
    dedup_policy: DedupPolicy, container: Container, command: str
) -> ToolResult:
    start = time.monotonic()
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
            "duration_ms": duration_ms,
        },
        success=True,
    )
    return resp


@sync_to_async
def search(
    dedup_policy: DedupPolicy, container: Container, pattern: str, root: str
) -> ToolResult:
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
        ).apply_exclude_diff(),
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


@sync_to_async
def search_on_internet(
    dedup_policy: DedupPolicy, container: Container, search_query: str
) -> ToolResult:
    start = time.monotonic()
    from ddgs import DDGS

    container_id: str = cast(str, container.container_id)

    key = f"search_on_internet_{search_query}"
    if key in dedup_policy.logs:
        print("Redup policy applied")
        dedup_policy.logs[key]["dedup"] = True
        duration_ms = int((time.monotonic() - start) * 1000)
        audit_agent_tool(
            target_type="container",
            target_id=container_id,
            action="agent_tool.search_on_internet",
            message="Web search (dedup hit)",
            metadata={"query": search_query, "duration_ms": duration_ms},
            success=True,
        )
        return dedup_policy.logs[key]

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
    resp: dict[str, object] = {"response": results, "finished": True}
    dedup_policy.logs[key] = resp
    return resp


@sync_to_async
def read_from_internet(
    dedup_policy: DedupPolicy, container: Container, url: str
) -> ToolResult:
    start = time.monotonic()

    import requests
    from bs4 import BeautifulSoup

    container_id: str = cast(str, container.container_id)

    key = f"read_from_internet_{url}"
    if key in dedup_policy.logs:
        print("Redup policy applied")
        dedup_policy.logs[key]["dedup"] = True
        duration_ms = int((time.monotonic() - start) * 1000)
        audit_agent_tool(
            target_type="container",
            target_id=container_id,
            action="agent_tool.read_from_internet",
            message="Read from internet (dedup hit)",
            metadata={"url": url, "duration_ms": duration_ms},
            success=True,
        )
        return dedup_policy.logs[key]

    DEFAULT_UA = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    )
    headers = {"User-Agent": DEFAULT_UA}

    error = None
    resp = None
    cleaned = ""
    text = ""

    try:
        resp = requests.get(url, headers=headers, timeout=10)
        resp.raise_for_status()
    except Exception as e:
        error = str(e)

    if not error and resp:
        soup = BeautifulSoup(resp.text, "html.parser")
        # Remove script/style elements
        for element in soup(["script", "style", "noscript"]):
            element.decompose()
        # Get text
        text = soup.get_text(separator="\n")
        # Collapse whitespace lines
        lines = [line.strip() for line in text.splitlines()]
        cleaned = "\n".join([ln for ln in lines if ln])

    # Truncate very long content to avoid overwhelming the caller
    max_len = 8000

    if len(cleaned) > max_len:
        cleaned = cleaned[:max_len]

    result: dict[str, object] = {
        "finished": True,
        "text": cleaned,
    }
    if error is not None:
        result["error"] = error

    duration_ms = int((time.monotonic() - start) * 1000)
    audit_agent_tool(
        target_type="container",
        target_id=container_id,
        action="agent_tool.read_from_internet",
        message="Read from internet",
        metadata=(
            {"url": url, "error": error, "duration_ms": duration_ms}
            if not error
            else {"url": url, "duration_ms": duration_ms}
        ),
        success=error is None,
    )

    dedup_policy.logs[key] = result

    return result
