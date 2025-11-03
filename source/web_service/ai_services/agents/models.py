from __future__ import annotations
import json
from dataclasses import dataclass
from typing import Any, Callable, Literal, TypedDict, overload


@dataclass
class AgentParameter:
    name: str
    description: str | None = None
    type: str = "string"

    @staticmethod
    def render_parameters(parameters: list[AgentParameter]) -> str:
        return "\n    ".join(
            [
                f"{parameter.name}: {parameter.type} -> {parameter.description}"
                for parameter in parameters
            ]
        )

    def generate_parameter_dict(self) -> tuple[str, dict[str, Any]]:
        obj = {
            "type": self.type,
        }

        if self.description is not None:
            obj["description"] = self.description

        return self.name, obj


@dataclass
class AgentTool:
    name: str
    description: str
    parameters: list[AgentParameter]
    agent_call: Callable[..., Any]
    type: str = "function"

    @staticmethod
    def render_agents(tools: list[AgentTool]) -> str:
        response = ""

        for tool in tools:
            response += f"tool {tool.name}> \nParamters:\n{AgentParameter.render_parameters(tool.parameters)}"
            response += "\n---\n"

        return response

    def generate_tool_dict(self) -> dict[str, Any]:
        parameter_names: list[str] = []
        parameter_objects: dict[str, Any] = {}
        for param in self.parameters:
            parameter_name, parameter_object = param.generate_parameter_dict()
            parameter_names.append(parameter_name)
            parameter_objects[parameter_name] = parameter_object

        return {
            "type": self.type,
            "function": {
                "strict": True,
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "additionalProperties": False,
                    "type": "object",
                    "properties": parameter_objects,
                    "required": parameter_names,
                },
            },
        }


class FunctionCallDict(TypedDict):
    name: str
    arguments: str


class ToolCallDict(TypedDict):
    id: str
    type: Literal["function"]
    function: FunctionCallDict


class AssistantMessage(TypedDict):
    role: Literal["assistant"]
    content: str


class UserMessage(TypedDict):
    role: Literal["user"]
    content: str


class SystemMessage(TypedDict):
    role: Literal["system"]
    content: str


class ToolCallingAssistantMessage(TypedDict):
    role: Literal["assistant"]
    content: str
    tool_calls: list[ToolCallDict]


class ToolResponseMessage(TypedDict):
    role: Literal["tool"]
    tool_call_id: str
    name: str
    content: str


OpenAIChatMessage = (
    AssistantMessage
    | UserMessage
    | SystemMessage
    | ToolCallingAssistantMessage
    | ToolResponseMessage
)


class OpenAIMessage:
    @staticmethod
    @overload
    def get_message(role: Literal["assistant"], content: str) -> AssistantMessage: ...

    @staticmethod
    @overload
    def get_message(role: Literal["user"], content: str) -> UserMessage: ...

    @staticmethod
    @overload
    def get_message(role: Literal["system"], content: str) -> SystemMessage: ...

    @staticmethod
    def get_message(
        role: Literal["assistant", "user", "system"], content: str
    ) -> AssistantMessage | UserMessage | SystemMessage:
        if role == "assistant":
            return {"role": "assistant", "content": content}
        elif role == "user":
            return {"role": "user", "content": content}
        else:
            return {"role": "system", "content": content}

    @staticmethod
    def get_assistant_message(content: str) -> AssistantMessage:
        return OpenAIMessage.get_message("assistant", content)

    @staticmethod
    def get_user_message(content: str) -> UserMessage:
        return OpenAIMessage.get_message("user", content)

    @staticmethod
    def get_system_message(content: str) -> SystemMessage:
        return OpenAIMessage.get_message("system", content)

    @staticmethod
    def get_tool_calling_message(
        tool_call_id: str, tool_name: str, tool_arguments: dict[str, Any]
    ) -> ToolCallingAssistantMessage:
        return {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {
                    "id": tool_call_id,
                    "type": "function",
                    "function": {
                        "name": tool_name,
                        "arguments": json.dumps(tool_arguments, ensure_ascii=False),
                    },
                }
            ],
        }

    @staticmethod
    def get_tool_response_message(
        tool_call_id: str, tool_name: str, result: dict[str, Any]
    ) -> ToolResponseMessage:
        return {
            "role": "tool",
            "tool_call_id": tool_call_id,
            "name": tool_name,
            "content": json.dumps(result, ensure_ascii=False),
        }


class DedupPolicy:
    def __init__(self):
        self.logs: dict[str, dict[str, object]] = {}


ToolResult = dict[str, object] | dict[str, dict[str, str]]


@dataclass
class TokenUsage:
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0

    def add_usage(self, token_usage: TokenUsage) -> TokenUsage:
        return TokenUsage(
            prompt_tokens=self.prompt_tokens + token_usage.prompt_tokens,
            completion_tokens=self.completion_tokens + token_usage.completion_tokens,
            total_tokens=self.total_tokens + token_usage.total_tokens,
        )
