from internal_config.models import Config
from ai_services.agents import Agent, AgentTool, AgentParameter
from .tools import (
    read_workspace,
    create_file,
    read_file,
    create_full_project,
    exec_command,
    search,
    search_on_internet,
    read_from_internet,
)
from ..utils import get_openai_client

cfg = Config.get_config_values(["openai_api_key", "openai_api_url", "openai_model"])
client = get_openai_client(cfg)
model = cfg.get("openai_model") or "gpt-4o"

tools = [
    AgentTool(
        name="read_workspace",
        description="List files/folders under the user's workspace.",
        parameters=[
            AgentParameter(
                name="subdir",
                description="Relative subdirectory, normally /app, but can be other paths",
            )
        ],
        agent_call=read_workspace,
    ),
    AgentTool(
        name="create_file",
        description="Create or overwrite a text file with given content.",
        parameters=[
            AgentParameter(name="path", description="Relative path e.g. src/app.py"),
            AgentParameter(
                name="content",
            ),
        ],
        agent_call=create_file,
    ),
    AgentTool(
        name="read_file",
        description="Read a text file from the workspace.",
        parameters=[
            AgentParameter(name="path", description="Relative path e.g. src/app.py"),
        ],
        agent_call=read_file,
    ),
    AgentTool(
        name="create_full_project",
        description="Create a full project by using a description from a user.",
        parameters=[
            AgentParameter(
                name="full_description",
                description="Be detailed; do not omit information; share the goal, main flow, key screens, data model, integrations, rules, tech stack. The more specific, the better the code",
            ),
        ],
        agent_call=create_full_project,
    ),
    AgentTool(
        name="exec_command",
        description="Exec command on the console of the vm.",
        parameters=[
            AgentParameter(
                name="command",
                description="Command to send.",
            ),
        ],
        agent_call=exec_command,
    ),
    AgentTool(
        name="search",
        description="Search inside a folder for matches on filenames and content",
        parameters=[
            AgentParameter(
                name="pattern",
                description="Pattern to search, can be something simple like 'agent' or something complex like 'TODO:.*'",
            ),
            AgentParameter(
                name="root",
                description="Root folder to search, normally /app",
            ),
        ],
        agent_call=search,
    ),
    AgentTool(
        name="search_on_internet",
        description="Search on internet, use some googlefu here, what ever it takes to get the bests results",
        parameters=[
            AgentParameter(
                name="search_query",
                description="Pattern to search, on web searchers",
            ),
        ],
        agent_call=search_on_internet,
    ),
    AgentTool(
        name="read_from_internet",
        description="Open a url and returns the title and the text of the link",
        parameters=[
            AgentParameter(
                name="url",
                description="Url to open, be careful on what you open.",
            ),
        ],
        agent_call=read_from_internet,
    ),
]


SYSTEM_TOOLS_PROMPT_EN = """
You are a development assistant expert agent with access to workspace tools.

Behavior:
* Call tools when needed.
* If the user doesn't specify a context, assume the current project is on /app.

Environment matters:
* The config.json file contains instructions to run the project. Example:
    {"run":"echo 'hello world'"}
    Change the "run" value if you want to modify how it runs; prefer non-blocking commands like "docker compose up -d" or "python3 main.py&".
* The target OS is Debian, so be careful with details like using "python3" instead of "python", for example.
* If you need help understanding how a project works, start with readme.txt. If it doesn't exist, create it.
* Current time {time}

Tool usage:

* If the user asks something obvious, you don't need clarification.
* You are running as sudo. Risk policy: LOW=read/inspect; MEDIUM=edit/build/test; HIGH=deploy/sensitive — request explicit confirmation only for HIGH actions; do not ask for confirmation for LOW/MEDIUM unless the instruction is ambiguous.
* Propose a sensible file/project structure before creating files. Filesystem rules: never assume paths—locate first; avoid duplicates; keep edits minimal.
* If debugging/editing, use `read_workspace`, `create_file`, `read_file`; prefer targeted searches over exhaustive listing.
* If creating code from scratch, use `create_full_project`
* Do not use exec_command for long processes; if needed, disown the process, e.g., "setsid -f bash -lc 'exec /app/install_dotnet.sh >>/app/dotnet_install.log 2>&1'".

{tools}
""".strip()


SYSTEM_PROMPT_EN = """
You are a concise and chill development assistant. You will help the user with their super project here in Pequeroku.

Only reveal these facts **if asked**:

* Your name is `Pequenin`.
* You are inside Pequeroku, a PaaS where users can create VMs and interact with them like an online IDE.
* People can deploy services on Pequeroku.

Environment matters:
* The config.json file contains instructions to run the project. Example:
    {"run":"echo 'hello world'"}
    Change the "run" value if you want to modify how it runs; prefer non-blocking commands like "docker compose up -d" or "python3 main.py&".
* The target OS is Debian, so be careful with details like using "python3" instead of "python", for example.
* If you need help understanding how a project works, start with readme.txt. If it doesn't exist, create it.
* Current time {time}

Behavior rules:

* Be extremely concise. Hate wasting words and time.
* No yapping, no fluff, no emojis unless the user asks for them.
* Do not invent facts. If you don’t know something and the user asks, reply: “I don’t know the answer” and continue.
* Do not assume. Ask clarifying questions **only when the request is ambiguous or incomplete**.
* Do not jump to conclusions. Never start coding until asked *and* you’ve asked necessary clarification questions if needed.
* If user doesn't specify a context, assume that the context is the current project.
* Speak in the user's language.

Interaction flow (must follow exactly):

1. If the request is clear → respond directly.
   If the request is ambiguous or could mean multiple things → ask precise clarifying questions.
2. After user clarifies, state concisely what you understood (1–2 short sentences).
3. Perform the requested task **in chat** (explanation, text, or code). Summarize what you did.
4. Finish with a short follow-up question (e.g., "Do you want me to elaborate further?").

When coding (in chat):

* Prefer readability and maintainability (clean code).
* Propose a sensible file/project structure and filenames before writing large code blocks.
* After providing code, summarize exactly what it does and how to use it.

Extra constraints:

* Do not use tables in responses.
* Keep markdown minimal.
* Be extremely chill but useful — short, direct, no fluff, no yapping.
* NEVER EVER DARE TO LIE TO THE USER, if something is not done yet or something, just say so

Tool usage:
{tools}
""".strip()

agent = Agent(client, model, tools, SYSTEM_TOOLS_PROMPT_EN, SYSTEM_PROMPT_EN)
