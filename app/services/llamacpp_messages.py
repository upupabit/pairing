"""Converts between pAIring's chat messages and llama-server's OpenAI-style chat API.

pAIring's messages keep one shape for every local engine: `images` as a list of base64 strings, assistant
`tool_calls` with dict `arguments`, tool results with `tool_call_id`. OpenAI wants images as content parts and
arguments as a JSON string, and streams tool calls as fragments, which ToolCallCollector joins back.
"""

import json
from typing import Any

# Leading base64 characters of each image format's magic bytes.
_IMAGE_TYPES = (("/9j/", "image/jpeg"), ("iVBOR", "image/png"), ("R0lG", "image/gif"), ("UklG", "image/webp"))


class OpenAIMessages:
    @classmethod
    def convert(cls, messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [cls._convert_one(m) for m in messages]

    @classmethod
    def _convert_one(cls, message: dict[str, Any]) -> dict[str, Any]:
        role = message["role"]
        content = message.get("content") or ""
        if role == "tool":
            return {"role": "tool", "tool_call_id": message.get("tool_call_id", ""), "content": content}
        converted: dict[str, Any] = {"role": role, "content": content}
        if message.get("images"):
            parts: list[dict[str, Any]] = [{"type": "text", "text": content}] if content else []
            parts += [{"type": "image_url", "image_url": {"url": cls._data_url(b64)}} for b64 in message["images"]]
            converted["content"] = parts
        if message.get("tool_calls"):
            converted["tool_calls"] = [cls._tool_call(call) for call in message["tool_calls"]]
        return converted

    @staticmethod
    def _data_url(b64: str) -> str:
        mime = next((m for prefix, m in _IMAGE_TYPES if b64.startswith(prefix)), "image/jpeg")
        return f"data:{mime};base64,{b64}"

    @staticmethod
    def _tool_call(call: dict[str, Any]) -> dict[str, Any]:
        function = call.get("function") or {}
        arguments = function.get("arguments")
        if not isinstance(arguments, str):
            arguments = json.dumps(arguments or {})
        return {
            "id": call.get("id", ""),
            "type": "function",
            "function": {"name": function.get("name", ""), "arguments": arguments},
        }


class ToolCallCollector:
    """Joins streamed `delta.tool_calls` fragments (keyed by `index`) into whole calls."""

    def __init__(self) -> None:
        self._calls: dict[int, dict[str, str]] = {}

    def add(self, fragments: list[dict[str, Any]]) -> None:
        for fragment in fragments:
            call = self._calls.setdefault(fragment.get("index", 0), {"id": "", "name": "", "arguments": ""})
            function = fragment.get("function") or {}
            call["id"] = fragment.get("id") or call["id"]
            call["name"] += function.get("name") or ""
            call["arguments"] += function.get("arguments") or ""

    def calls(self) -> list[dict[str, Any]]:
        """In the shape ToolCallSink holds: `function.arguments` as a dict (empty if it isn't valid JSON)."""
        result = []
        for index in sorted(self._calls):
            call = self._calls[index]
            try:
                arguments = json.loads(call["arguments"]) if call["arguments"] else {}
            except ValueError:
                arguments = {}
            entry: dict[str, Any] = {"function": {"name": call["name"], "arguments": arguments}}
            if call["id"]:
                entry["id"] = call["id"]
            result.append(entry)
        return result
