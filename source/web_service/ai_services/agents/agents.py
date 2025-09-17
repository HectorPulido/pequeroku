from __future__ import annotations
import json
from typing import List, Dict, Any

from vm_manager.models import Container

from .schemas import SYSTEM_PROMPT_EN, TOOLS_SPEC
from .tools import (
    ToolError,
    read_workspace,
    create_file,
    read_file,
    create_full_project,
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
        return [{"role": "system", "content": SYSTEM_PROMPT_EN}]

    def exec_and_select_tool(self, name, container: "Container", **args):
        print("==" * 20)
        print(f"[Agent] Calling {name}, on {container} with {args}")

        result = {}
        try:
            if name == "read_workspace":
                result = read_workspace(container, **args)
            elif name == "create_file":
                result = create_file(container, **args)
            elif name == "read_file":
                result = read_file(container, **args)
            elif name == "create_full_project":
                result = create_full_project(container, **args)
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

    def run_tool_loop(
        self,
        messages: List[Dict[str, Any]],
        container: "Container",
        max_rounds: int = 8,
    ) -> List[Dict[str, Any]]:
        """Run function-calling until the model stops requesting tools.

        Returns the updated messages; caller can then do a final streaming
        completion to produce the assistant's natural language answer.
        """

        new_messages = messages.copy()

        info = ""

        rounds = 0
        while True:
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
                    break
                except Exception as e:
                    print(e)
            if not resp:
                return messages

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

                    result = self.exec_and_select_tool(name, container, **args)

                    if not "error" in result:
                        info += f"{name}({fn.arguments}): {json.dumps(result, ensure_ascii=False)}\n"

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
            print(finish_reason)
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
        return messages
