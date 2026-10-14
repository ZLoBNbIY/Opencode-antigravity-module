"""Small, comment-preserving JSONC edits for the optional DeepSeek integration."""

import json
import re
from pathlib import Path


def jsonc_text(text: str, *, mask_trailing_commas=True) -> str:
    """Mask comments/trailing commas without changing source offsets."""
    chars = list(text)
    i = 0
    quoted = False
    while i < len(chars):
        if quoted:
            if chars[i] == "\\":
                i += 2
                continue
            if chars[i] == '"':
                quoted = False
        elif chars[i] == '"':
            quoted = True
        elif text[i:i + 2] in ("//", "/*"):
            block = text[i:i + 2] == "/*"
            end = text.find("*/", i + 2) if block else text.find("\n", i + 2)
            if end < 0:
                if block:
                    raise ValueError("Незакрытый комментарий в конфигурации OpenCode")
                end = len(chars)
            elif block:
                end += 2
            for j in range(i, end):
                if chars[j] not in "\r\n":
                    chars[j] = " "
            i = end
            continue
        i += 1
    # Only commas outside strings can be trailing commas.
    masked = "".join(chars)
    if not mask_trailing_commas:
        return masked
    for match in re.finditer(r'"(?:\\.|[^"\\])*"|,(?=\s*[}\]])', masked):
        if match.group() == ",":
            chars[match.start()] = " "
    return "".join(chars)


def parse_config(text: str) -> dict:
    def unique(pairs):
        obj = {}
        for key, value in pairs:
            if key in obj:
                raise ValueError(f"Повторяющееся поле конфигурации: {key}")
            obj[key] = value
        return obj

    data = json.loads(jsonc_text(text), object_pairs_hook=unique)
    if not isinstance(data, dict):
        raise ValueError("Конфигурация OpenCode должна быть JSON-объектом")
    return data


def set_property(text: str, path: tuple[str, ...], value) -> str:
    """Replace only the requested value; preserve all other source text."""
    clean = jsonc_text(text)
    decoder = json.JSONDecoder()

    def skip(i):
        while i < len(clean) and (clean[i].isspace() or clean[i] == ","):
            i += 1
        return i

    def edit(start, keys):
        start = skip(start)
        if clean[start] != "{":
            raise ValueError(f"Поле {keys[0]} находится не в JSON-объекте")
        i = skip(start + 1)
        last_end = None
        while clean[i] != "}":
            key, end = decoder.raw_decode(clean, i)
            colon = skip(end)
            if clean[colon] != ":":
                raise ValueError("Некорректная конфигурация OpenCode")
            value_start = skip(colon + 1)
            current, value_end = decoder.raw_decode(clean, value_start)
            if key == keys[0]:
                if len(keys) > 1:
                    return edit(value_start, keys[1:])
                if current == value:
                    return text
                rendered = json.dumps(value, indent=2, ensure_ascii=False)
                return text[:value_start] + rendered + text[value_end:]
            last_end = value_end
            i = skip(value_end)
        nested = value
        for key in reversed(keys[1:]):
            nested = {key: nested}
        rendered = json.dumps(keys[0], ensure_ascii=False) + ": " + json.dumps(nested, indent=2, ensure_ascii=False)
        # A trailing comma may already exist in the original JSONC.
        tail = jsonc_text(text[last_end:i], mask_trailing_commas=False) if last_end is not None else ""
        comma = "" if last_end is None or "," in tail else ","
        # Insert a separator immediately after the last value, before any // comment.
        if comma:
            text_with_comma = text[:last_end] + "," + text[last_end:]
            return text_with_comma[:i + 1] + "\n  " + rendered + "\n" + text_with_comma[i + 1:]
        return text[:i] + "\n  " + rendered + "\n" + text[i:]

    parse_config(text)
    result = edit(0, path)
    parse_config(result)
    return result


def config_path(directory: Path) -> Path:
    json_path = directory / "opencode.json"
    jsonc_path = directory / "opencode.jsonc"
    if json_path.exists() and jsonc_path.exists():
        raise ValueError("Найдены opencode.json и opencode.jsonc одновременно. Оставьте один активный конфиг перед подключением DeepSeek.")
    return jsonc_path if jsonc_path.exists() else json_path
