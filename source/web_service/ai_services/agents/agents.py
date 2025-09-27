from __future__ import annotations
import json
import time
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
    Orchestrates tool-calling loops for workspace actions and chat responses.
    """

    class TaskTracker:
        def __init__(self):
            self.plan: List[str] = []
            self.history: List[str] = []

        def add_plan(self, content: str) -> None:
            if not content:
                return
            snippet = content.strip()
            lines = [l.strip() for l in snippet.splitlines() if l.strip()]
            self.plan = lines[:3]

        def record(
            self, action: str, args: Dict[str, Any], result: Dict[str, Any]
        ) -> None:
            preview_keys = ["path", "command", "pattern", "url"]
            arg_preview = {k: args.get(k) for k in preview_keys if k in args}
            # Risk level when available (from result or injected in args)
            risk_level = result.get("risk_level") if isinstance(result, dict) else None
            if not risk_level:
                risk_level = args.get("_risk_level")
            res_keys = []
            if "finished" in result:
                res_keys.append("finished")
            if "path" in result:
                res_keys.append("path")
            if "title" in result:
                res_keys.append("title")
            if "entries" in result:
                res_keys.append(f"entries[{len(result.get('entries', []))}]")
            if "response" in result:
                res_keys.append("response")
            if risk_level:
                res_keys.append(f"risk={risk_level}")
            summary = f"{action} args={json.dumps(arg_preview, ensure_ascii=False)} result_keys={res_keys}"
            if len(summary) > 500:
                summary = summary[:500] + "..."
            self.history.append(summary)
            if len(self.history) > 15:
                self.history = self.history[-15:]

        def summarize(self) -> str:
            parts = []
            if self.plan:
                parts.append("Plan: " + " | ".join(self.plan))
            parts.extend(self.history)
            return "\n".join(parts).strip()

    def classify_risk_for_command(self, cmd: str) -> str:
        if not cmd:
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
        if any(m in cmd for m in high_markers):
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
        if any(m in cmd for m in medium_markers):
            return "MEDIUM"
        return "LOW"

    def _condense_tool_event(
        self, name: str, args: Dict[str, Any], result: Dict[str, Any]
    ) -> None:
        if hasattr(self, "tracker") and self.tracker:
            self.tracker.record(name, args, result)

    def _maybe_update_token_usage_from_response(self, resp: Any) -> None:
        try:
            usage = getattr(resp, "usage", None)
            if usage is None and isinstance(resp, dict):
                usage = resp.get("usage")
            if usage:
                pt = getattr(usage, "prompt_tokens", None) or usage.get(
                    "prompt_tokens", 0
                )
                ct = getattr(usage, "completion_tokens", None) or usage.get(
                    "completion_tokens", 0
                )
                tt = getattr(usage, "total_tokens", None) or usage.get(
                    "total_tokens", (pt or 0) + (ct or 0)
                )
                self.token_usage["prompt_tokens"] += int(pt or 0)
                self.token_usage["completion_tokens"] += int(ct or 0)
                self.token_usage["total_tokens"] += int(tt or 0)
        except Exception:
            pass

    def __init__(self, client, model: str):
        self.client = client
        self.model = model
        self.tracker = self.TaskTracker()
        self.token_usage = {
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
        }

    @staticmethod
    def bootstrap_messages() -> List[Dict[str, Any]]:
        return [
            {
                "role": "system",
                "content": SYSTEM_PROMPT_EN.replace(
                    "{time}", datetime.now().isoformat()
                ),
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
    def get_response(self, new_messages: List[Dict[str, Any]]) -> Any:
        resp = None
        delays = [0.5, 1.0, 2.0, 4.0, 8.0]
        last_err = None
        for attempt, delay in enumerate(delays, start=1):
            try:
                resp = self.client.chat.completions.create(
                    messages=new_messages,
                    model=self.model,
                    tools=TOOLS_SPEC,
                    tool_choice="auto",
                    stream=False,
                    parallel_tool_calls=False,
                )
                self._maybe_update_token_usage_from_response(resp)
                return resp
            except Exception as e:
                last_err = e
                print(
                    f"[AGENTES] Error getting response: (Try {attempt}/{len(delays)}): {e}"
                )
                time.sleep(delay)
        if not resp:
            return None

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
            "content": SYSTEM_TOOLS_PROMPT_EN.replace(
                "{time}", datetime.now().isoformat()
            ),
        }
        # Initialize task tracker and encourage planning/batching
        self.tracker = self.TaskTracker()
        new_messages.insert(
            1,
            {
                "role": "assistant",
                "content": "Before taking actions, briefly outline a 1–3 step plan, then proceed to call tools. Group shell commands when safe, keep edits minimal, and prefer targeted searches.",
            },
        )

        dedup_policy = DedupPolicy()

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

                # Capture any initial plan proposed by the model (if any)
                if getattr(msg, "content", None):
                    self.tracker.add_plan(str(msg.content))
                for tc in tool_calls:
                    fn = tc.function
                    name = fn.name
                    try:
                        args = json.loads(fn.arguments or "{}")
                    except Exception:
                        args = {}

                    yield False, name

                    # Risk gating for high-risk shell commands
                    if name == "exec_command":
                        cmd = args.get("command", "")
                        risk = self.classify_risk_for_command(cmd)
                        if risk == "HIGH":
                            new_messages.append(
                                {
                                    "role": "assistant",
                                    "content": f"High-risk command detected. Explain why it is necessary and ask for explicit confirmation before proceeding.\nCommand: {cmd}",
                                }
                            )
                            continue

                    result = await self.exec_and_select_tool(
                        dedup_policy, name, container, **args
                    )

                    if "error" not in result:
                        if name == "exec_command":
                            args = dict(args)
                            args["_risk_level"] = self.classify_risk_for_command(
                                args.get("command", "")
                            )
                        self.tracker.record(name, args, result)

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

        summary = self.tracker.summarize()
        if summary:
            usage = self.token_usage

            prompt = usage.get("prompt_tokens", 0)
            completion = usage.get("completion_tokens", 0)
            total = usage.get("total_tokens", 0)

            print(
                f"Token usage: prompt: {prompt}, completion: {completion}, total: {total}"
            )

            messages.insert(
                -1,
                {
                    "role": "assistant",
                    "content": f"Condensed tool actions:\n{summary}\n\nToken usage (approx)",
                },
            )
        yield True, messages
