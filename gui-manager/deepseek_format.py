"""Strict, non-executing OpenAI adapter for ordinary web-chat responses."""
import json
import re
import time
import uuid
from deepseek_browser import WebError


def text_content(value):
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if not isinstance(value, list):
        raise WebError("site-changed")
    parts = []
    for part in value:
        if not isinstance(part, dict) or part.get("type") != "text" or not isinstance(part.get("text"), str):
            raise ValueError("DeepSeek Web в этой версии принимает только текст, без изображений.")
        parts.append(part["text"])
    return "\n".join(parts)


def tool_specs(tools):
    specs = []
    for tool in tools or []:
        function = tool.get("function") if isinstance(tool, dict) else None
        if not isinstance(function, dict) or not isinstance(function.get("name"), str):
            raise ValueError("Некорректная схема инструмента")
        specs.append({"name": function["name"], "description": function.get("description", ""), "parameters": function.get("parameters") or {"type": "object", "properties": {}}})
    return specs


def messages_to_prompt(payload):
    messages = payload.get("messages")
    if not isinstance(messages, list) or not messages:
        raise ValueError("messages должен содержать сообщения")
    lines = []
    for message in messages:
        if not isinstance(message, dict) or message.get("role") not in ("system", "developer", "user", "assistant", "tool", "function"):
            raise ValueError("Некорректное сообщение")
        # The web-chat UI renders the whole adapter prompt as a visible user
        # message. Never expose OpenCode's hidden system/developer instructions
        # there; only user-visible conversation and tool results are forwarded.
        if message["role"] in ("system", "developer"):
            continue
        text = text_content(message.get("content"))
        if message.get("tool_calls"):
            text += "\nPrevious tool calls: " + json.dumps(message["tool_calls"], ensure_ascii=False)
        label = message["role"].capitalize()
        if message.get("tool_call_id"):
            label += " " + str(message["tool_call_id"])
        lines.append(label + ": " + text)
    specs = tool_specs(payload.get("tools"))
    choice = payload.get("tool_choice", "auto")
    if specs and choice != "none":
        instructions = (
            "Available tools (JSON Schema):\n" + json.dumps(specs, ensure_ascii=False) + "\n\n"
            "This web chat has no native function-calling channel. To perform an action, reply ONLY with a fenced tool_calls JSON array:\n"
            '```tool_calls\n[{"name":"exact supplied tool name","arguments":{}}]\n```\n'
            "Use only supplied names and matching argument objects. Never claim an action succeeded without its tool result. "
            "When no action is needed, reply normally without that block."
        )
        if choice == "required":
            instructions += " You must call a supplied tool now."
        elif isinstance(choice, dict):
            function = choice.get("function")
            name = function.get("name") if isinstance(function, dict) else None
            if name not in {item["name"] for item in specs}:
                raise ValueError("Неизвестный tool_choice")
            instructions += " Call this tool now: " + name
        lines.append(instructions)
    elif choice == "none":
        lines.append("Do not call tools. Reply in plain text.")
    if not any(message.get("role") in ("user", "tool", "function") for message in messages if isinstance(message, dict)):
        raise ValueError("Нет сообщения пользователя для отправки в веб-чат")
    lines.append("Assistant:")
    result = "\n\n".join(lines)
    if len(result.encode("utf-8")) > 1024 * 1024:
        raise ValueError("Слишком большой текст для веб-чата; сократите контекст.")
    return result


def parse_tool_calls(text, tools, choice="auto"):
    if not tools or choice == "none":
        return text, None
    allowed = {item["name"] for item in tool_specs(tools)}
    matches = list(re.finditer(r"```tool_calls\s*\n?(.*?)```", text, re.S))
    candidates = [(match.group(1), match.span()) for match in reversed(matches)]
    candidates.append((text.strip(), (0, len(text))))
    for candidate, span in candidates:
        try:
            data = json.loads(candidate)
        except ValueError:
            continue
        if isinstance(data, dict):
            data = data.get("tool_calls")
        if not isinstance(data, list) or not data:
            continue
        calls = []
        for item in data:
            if not isinstance(item, dict) or item.get("name") not in allowed or not isinstance(item.get("arguments"), dict):
                calls = []
                break  # No partial execution of an invalid/mixed batch.
            calls.append({"id": "call_" + uuid.uuid4().hex, "type": "function", "function": {"name": item["name"], "arguments": json.dumps(item["arguments"], ensure_ascii=False)}})
        if calls:
            return (text[:span[0]] + text[span[1]:]).strip(), calls
    return text, None


def completion_response(payload, prompt, text):
    content, calls = parse_tool_calls(text, payload.get("tools"), payload.get("tool_choice", "auto"))
    message = {"role": "assistant", "content": content or None}
    if calls:
        message["tool_calls"] = calls
    return {"id": "chatcmpl-" + uuid.uuid4().hex, "object": "chat.completion", "created": int(time.time()), "model": payload["model"],
            "choices": [{"index": 0, "message": message, "finish_reason": "tool_calls" if calls else "stop"}],
            "usage": {"prompt_tokens": len(prompt) // 4, "completion_tokens": len(text) // 4, "total_tokens": (len(prompt) + len(text)) // 4}}


def sse_frames(result):
    choice = result["choices"][0]
    base = {key: result[key] for key in ("id", "created", "model")}
    base["object"] = "chat.completion.chunk"
    def frame(delta, finish=None):
        return "data: " + json.dumps({**base, "choices": [{"index": 0, "delta": delta, "finish_reason": finish}]}, ensure_ascii=False) + "\n\n"
    yield frame({"role": "assistant"})
    if choice["message"].get("content"):
        yield frame({"content": choice["message"]["content"]})
    for index, call in enumerate(choice["message"].get("tool_calls", [])):
        yield frame({"tool_calls": [{"index": index, **call}]})
    yield frame({}, choice["finish_reason"])
    yield "data: [DONE]\n\n"
