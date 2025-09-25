from __future__ import annotations
import json
from datetime import datetime
from typing import List, Dict, Any
from asgiref.sync import sync_to_async

from vm_manager.models import Container

from .schemas import SYSTEM_PROMPT_EN, TOOLS_SPEC, SYSTEM_TOOLS_PROMPT_EN
from .tools import (
    ToolError,
    DedupPolicy,
    read_workspace,
    create_file,
    read_file,
    create_full_project,
    exec_command,
    search,
    search_on_internet,
    read_from_internet,
)


class DevAgent:
    """
    Agent that orchestrates tool-calling loops.
    """

    def __init__(self, client, model: str):
        self.client = client
        self.model = model

    @staticmethod
    def bootstrap_messages() -> List[Dict[str, Any]]:
        return [
            {
                "role": "system",
                "content": SYSTEM_PROMPT_EN.replace("{time}", datetime.now()),
            }
        ]

    @sync_to_async
    def exec_and_select_tool(
        self, dedup_policy: DedupPolicy, name: str, container: "Container", **args
    ):
        print("==" * 20)
        print(f"[Agent] Calling {name}, on {container} with {args}")

        result = {}
        try:
            if name == "read_workspace":
                result = read_workspace(dedup_policy, container, **args)
            elif name == "create_file":
                result = create_file(dedup_policy, container, **args)
            elif name == "read_file":
                result = read_file(dedup_policy, container, **args)
            elif name == "create_full_project":
                result = create_full_project(dedup_policy, container, **args)
            elif name == "exec_command":
                result = exec_command(dedup_policy, container, **args)
            elif name == "search":
                result = search(dedup_policy, container, **args)
            elif name == "search_on_internet":
                result = search_on_internet(dedup_policy, container, **args)
            elif name == "read_from_internet":
                result = read_from_internet(dedup_policy, container, **args)
            else:
                result = {"error": f"Unknown tool: {name}"}
        except ToolError as te:
            result = {"error": str(te)}
        except Exception as e:
            print(e)
            result = {
                "error": f"Internal tool failure in {name}: {e.__class__.__name__}: {e}"
            }

        print("==" * 20)
        print(f"[Agent] Response {name}, on {container}: {result}")
        return result

    @sync_to_async
    def get_response(self, new_messages):
        resp = None
        for _ in range(5):
            try:
                resp = self.client.chat.completions.create(
                    messages=new_messages,
                    model=self.model,
                    tools=TOOLS_SPEC,
                    tool_choice="auto",
                    stream=False,
                    parallel_tool_calls=False,
                )
                return resp
            except Exception as e:
                print("[AGENTS] Error getting response: ", e)
        if not resp:
            return None

    @sync_to_async
    async def run_tool_loop(
        self,
        messages: List[Dict[str, Any]],
        container: "Container",
        max_rounds: int = 8,
    ):
        """Run function-calling until the model stops requesting tools.

        Returns the updated messages; caller can then do a final streaming
        completion to produce the assistant's natural language answer.
        """

        new_messages = messages.copy()
        new_messages[0] = {
            "role": "system",
            "content": SYSTEM_TOOLS_PROMPT_EN.replace("{time}", datetime.now()),
        }

        dedup_policy = DedupPolicy()

        info = ""
        rounds = 0

        while True:
            resp = None

            resp = await self.get_response(new_messages)
            if not resp:
                break

            choice = resp.choices[0]
            tool_calls = getattr(choice.message, "tool_calls", None)
            finish_reason = choice.finish_reason

            msg = choice.message
            tool_calls = getattr(msg, "tool_calls", None)

            if tool_calls:
                rounds += 1
                if rounds > max_rounds:
                    new_messages.append(
                        {
                            "role": "assistant",
                            "content": "Stopped due to too many tool calls in a single turn.",
                        }
                    )
                    break

                for tc in tool_calls:
                    fn = tc.function
                    name = fn.name
                    try:
                        args = json.loads(fn.arguments or "{}")
                    except Exception:
                        args = {}

                    yield False, name

                    result = await self.exec_and_select_tool(
                        dedup_policy, name, container, **args
                    )

                    if not "error" in result:
                        info += f"{name}({fn.arguments}): {json.dumps(result, ensure_ascii=False)}\n"

                    if "dedup" in result:
                        continue

                    new_messages.append(
                        {
                            "role": "assistant",
                            "content": "",
                            "tool_calls": [
                                {
                                    "id": tc.id,
                                    "type": "function",
                                    "function": {
                                        "name": name,
                                        "arguments": json.dumps(
                                            args, ensure_ascii=False
                                        ),
                                    },
                                }
                            ],
                        }
                    )

                    new_messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": tc.id,
                            "name": name,
                            "content": json.dumps(result, ensure_ascii=False),
                        }
                    )
                # Continue; model now sees the tool outputs
                continue

            # No tool calls => stop and let caller stream the final answer
            print(f"[AGENT] STOP_REASON: {finish_reason}")
            if finish_reason in ("stop", "length", None):
                break

        if len(info.strip()) > 0:
            messages.insert(
                -1,
                {
                    "role": "assistant",
                    "content": f"Here some info that can help you with the user request: {info}",
                },
            )
        yield True, messages
