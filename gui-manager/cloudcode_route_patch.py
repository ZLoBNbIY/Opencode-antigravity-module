from pathlib import Path


def patch_auth_plugin_transport(plugin_cache: Path | None = None) -> bool:
    """Route Cloud Code through Hub while preserving the plugin's other VLESS routes."""
    import re

    roots = [Path(plugin_cache)] if plugin_cache else [
        Path.home() / ".cache" / "opencode" / "npm",
        Path.home() / ".cache" / "opencode" / "packages",
    ]
    candidates = []
    for root in roots:
        if not root.exists():
            continue
        candidates.extend(root.glob("**/@cortexkit/opencode-antigravity-auth/dist/server.js"))
        candidates.extend(root.glob("**/@cortexkit/opencode-antigravity-auth/dist/index.js"))
    if plugin_cache is None:
        local_plugin = Path(__file__).resolve().parent.parent / "plugin" / "dist"
        for name in ("server.js", "index.js"):
            cand = local_plugin / name
            if cand.exists() and cand not in candidates:
                candidates.append(cand)

    if not candidates:
        return False
    patched = False
    new_gate = (
        "const gateHost = url.hostname === 'daily-cloudcode-pa.googleapis.com' || "
        "url.hostname === 'cloudcode-pa.googleapis.com' || "
        "url.hostname === 'cloudaicompanion.googleapis.com' || "
        "url.hostname === 'generativelanguage.googleapis.com' || "
        "url.hostname === 'oauth2.googleapis.com' || "
        "url.hostname === 'aiplatform.googleapis.com' || "
        "url.hostname.endsWith('.googleapis.com') || "
        "url.hostname.endsWith('.google.com') || "
        "url.hostname.endsWith('.google');"
    )
    old_gate_exact = "const gateHost = url.hostname === 'daily-cloudcode-pa.googleapis.com' || url.hostname === 'cloudcode-pa.googleapis.com';"

    for path in candidates:
        try:
            source = path.read_text(encoding="utf-8")
            changed = False

            # 1. Route Cloud Code & all Gemini hosts to 10880
            marker = "const hubRoutePort = 10880;"
            if marker not in source:
                pattern = re.compile(
                    r"const vlessPort = Number\(parsed\.vless_http_port\) > 0 \? Number\(parsed\.vless_http_port\) : 10879;\s*"
                    r"return new URL\(`http://127\.0\.0\.1:\$\{vlessPort\}`\);"
                )
                replacement = (
                    "const hubRoutePort = 10880;\n"
                    f"        {new_gate}\n"
                    "        const vlessPort = Number(parsed.vless_http_port) > 0 ? Number(parsed.vless_http_port) : 10879;\n"
                    "        return new URL(`http://127.0.0.1:${gateHost ? hubRoutePort : vlessPort}`);"
                )
                source, count = pattern.subn(replacement, source, count=1)
                if count:
                    changed = True
            elif old_gate_exact in source:
                source = source.replace(old_gate_exact, new_gate, 1)
                changed = True

            # 2. Do not hang in retry loop on fatal 404 (model not found)
            if "response.status === 404" in source and "/* no retry on 404 */" not in source:
                for old_retry, new_retry in (
                    (
                        "const shouldRetryEndpoint = geoBlockedLocation || response.status === 403 || response.status === 404 || response.status >= 500;",
                        "const shouldRetryEndpoint = geoBlockedLocation || response.status === 403 || response.status >= 500; /* no retry on 404 */",
                    ),
                    (
                        "const shouldRetryEndpoint = response.status === 403 || response.status === 404 || response.status >= 500;",
                        "const shouldRetryEndpoint = response.status === 403 || response.status >= 500; /* no retry on 404 */",
                    ),
                ):
                    if old_retry in source:
                        source = source.replace(old_retry, new_retry, 1)
                        changed = True
                        break

            if changed:
                backup = path.with_suffix(path.suffix + ".hub-route.bak")
                if not backup.exists():
                    backup.write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
                path.write_text(source, encoding="utf-8")
                patched = True
        except OSError:
            continue
    return patched or any("const hubRoutePort = 10880;" in p.read_text(encoding="utf-8")
                          for p in candidates if p.exists())


def restore_auth_plugin_transport(plugin_cache: Path | None = None) -> None:
    """Restore patched plugin files before a plugin upgrade or Hub removal."""
    roots = [Path(plugin_cache)] if plugin_cache else [
        Path.home() / ".cache" / "opencode" / "npm",
        Path.home() / ".cache" / "opencode" / "packages",
    ]
    for root in roots:
        if not root.exists():
            continue
        for backup in list(root.glob("**/server.js.hub-route.bak")) + list(root.glob("**/index.js.hub-route.bak")):
            target = backup.with_name(backup.name.replace(".hub-route.bak", ""))
            try:
                target.write_text(backup.read_text(encoding="utf-8"), encoding="utf-8")
                backup.unlink()
            except OSError:
                pass


PROMPT_FIX_MARKER = "function sanitizeAntigravitySystemInstruction("
PROMPT_FIX_CALL = "sanitizeAntigravitySystemInstruction(requestPayload);"
PROMPT_FIX_ANCHOR = "function sanitizeRequestPayloadForAntigravity(payload) {"
PROMPT_FIX_BACKUP_SUFFIX = ".hub-prompt.bak"
GEMINI4_FIX_MARKER = 'getDynamicWireModel("antigravity-gemini-4-hydrogen") || "gemini-4-hydrogen-sonar"'
PROMPT_FIX_BLOCK = r'''var ANTIGRAVITY_BLOCKED_SYSTEM_INSTRUCTION_PATTERNS = [
  [/tools\.opencode\.session_move/gi, 'tools.opencode["session_move"]']
];
function sanitizeAntigravitySystemInstruction(payload) {
  if (!payload || typeof payload !== "object") return;
  const instruction = payload.systemInstruction;
  if (!instruction) return;
  const sanitizeText = (text) => {
    let next = text;
    for (const [pattern, replacement] of ANTIGRAVITY_BLOCKED_SYSTEM_INSTRUCTION_PATTERNS) {
      next = next.replace(pattern, replacement);
    }
    return next;
  };
  if (typeof instruction === "string") {
    payload.systemInstruction = sanitizeText(instruction);
    return;
  }
  if (typeof instruction !== "object") return;
  const parts = Array.isArray(instruction.parts) ? instruction.parts : [];
  for (const part of parts) {
    if (!part || typeof part !== "object") continue;
    if (typeof part.text === "string") {
      part.text = sanitizeText(part.text);
    }
  }
}
'''
PROMPT_FIX_CALL_ANCHOR = '''        if ("system_instruction" in requestPayload) {
          requestPayload.systemInstruction = requestPayload.system_instruction;
          delete requestPayload.system_instruction;
        }'''


def _prompt_fix_candidates(plugin_cache: Path | None = None) -> list[Path]:
    """Find installed Antigravity bundles that OpenCode loads at startup."""
    if plugin_cache:
        roots = [Path(plugin_cache)]
    else:
        roots = [
            Path.home() / ".cache" / "opencode" / "npm",
            Path.home() / ".cache" / "opencode" / "packages",
        ]
    candidates: list[Path] = []
    for root in roots:
        if not root.exists():
            continue
        for name in ("server.js", "index.js"):
            candidates.extend(root.glob(f"**/@cortexkit/opencode-antigravity-auth/dist/{name}"))
    seen: set[str] = set()
    unique: list[Path] = []
    for path in candidates:
        key = str(path.resolve())
        if key in seen:
            continue
        seen.add(key)
        unique.append(path)
    return unique


def _read_text_exact(path: Path) -> str:
    with open(path, "r", encoding="utf-8", newline="") as handle:
        return handle.read()


def _write_text_exact(path: Path, text: str) -> None:
    with open(path, "w", encoding="utf-8", newline="") as handle:
        handle.write(text)


def _local_plugin_dist_dir() -> Path | None:
    candidate = Path(__file__).resolve().parent.parent / "plugin" / "dist"
    return candidate if (candidate / "server.js").exists() else None


def sync_local_plugin_bundles(plugin_cache: Path | None = None) -> dict:
    """Copy the verified local plugin bundle over installed OpenCode caches.

    This is the same strategy as ``scripts/patch_plugin.mjs``: after an
    OpenCode/plugin update the installed bundle may be replaced by a stock
    one, so restore the module's verified bundle first.
    """
    local = _local_plugin_dist_dir()
    if local is None:
        return {"ok": False, "copied": [], "message": "Локальный бандл плагина не найден."}
    target_dirs = {path.parent for path in _prompt_fix_candidates(plugin_cache)}
    copied: list[str] = []
    for target in target_dirs:
        for name in ("cli.js", "server.js", "index.js"):
            source = local / name
            destination = target / name
            if not source.exists() or not destination.exists():
                continue
            try:
                if source.read_bytes() == destination.read_bytes():
                    continue
                destination.write_bytes(source.read_bytes())
                copied.append(str(destination))
            except OSError:
                continue
    return {
        "ok": bool(copied),
        "copied": copied,
        "message": f"Синхронизировано файлов бандла: {len(copied)}."
        if copied else "Бандл плагина уже совпадает с локальным.",
    }


def patch_prompt_sanitizer(plugin_cache: Path | None = None) -> dict:
    """Apply the Cloud Code 429 fix to installed OpenCode plugin bundles.

    Google returns 429 RESOURCE_EXHAUSTED when the system instruction contains
    ``tools.opencode.session_move`` (OpenCode's Code Mode catalog does). The
    patch rewrites only that reference, keeping the same JS tool path.
    """
    candidates = _prompt_fix_candidates(plugin_cache)
    changed: list[str] = []
    already: list[str] = []
    missing: list[str] = []
    if not candidates:
        return {
            "ok": False,
            "changed": [],
            "already": [],
            "missing": [],
            "message": "Плагин Antigravity не найден в кэше OpenCode.",
        }

    for path in candidates:
        try:
            source = _read_text_exact(path)
            if PROMPT_FIX_MARKER in source and PROMPT_FIX_CALL in source:
                already.append(str(path))
                continue
            eol = "\r\n" if "\r\n" in source else "\n"
            patched = source
            if PROMPT_FIX_MARKER not in patched:
                if PROMPT_FIX_ANCHOR not in patched:
                    missing.append(str(path))
                    continue
                block = PROMPT_FIX_BLOCK.replace("\n", eol)
                patched = patched.replace(PROMPT_FIX_ANCHOR, block + eol + PROMPT_FIX_ANCHOR, 1)
            if PROMPT_FIX_CALL not in patched:
                call_anchor = PROMPT_FIX_CALL_ANCHOR.replace("\n", eol)
                if call_anchor not in patched:
                    missing.append(str(path))
                    continue
                patched = patched.replace(
                    call_anchor,
                    call_anchor + eol + "        " + PROMPT_FIX_CALL,
                    1,
                )
            if patched == source:
                already.append(str(path))
                continue
            backup = path.with_suffix(path.suffix + PROMPT_FIX_BACKUP_SUFFIX)
            if not backup.exists():
                _write_text_exact(backup, source)
            _write_text_exact(path, patched)
            changed.append(str(path))
        except OSError:
            missing.append(str(path))

    if changed:
        message = f"Фикс 429 применён: {len(changed)} файл(ов). Перезапустите OpenCode."
        if missing:
            message += f" Не удалось обновить: {len(missing)}."
    elif already:
        message = "Фикс 429 уже применён во всех найденных копиях плагина."
        if missing:
            message += " Часть копий не найдена или изменилась."
    else:
        message = "Не удалось применить фикс: изменилась структура плагина. Запустите scripts/patch_plugin.mjs."
    return {
        "ok": bool(changed or already),
        "changed": changed,
        "already": already,
        "missing": missing,
        "message": message,
    }


def get_prompt_sanitizer_status(plugin_cache: Path | None = None) -> dict:
    """Report whether the 429 fix is present in every installed plugin copy."""
    candidates = _prompt_fix_candidates(plugin_cache)
    if not candidates:
        return {
            "state": "missing",
            "found": 0,
            "patched": 0,
            "pending": 0,
            "message": "Установленная копия плагина Antigravity не найдена.",
        }
    patched = 0
    for path in candidates:
        try:
            source = _read_text_exact(path)
        except OSError:
            continue
        if (
            PROMPT_FIX_MARKER in source
            and PROMPT_FIX_CALL in source
            and GEMINI4_FIX_MARKER in source
        ):
            patched += 1
    pending = len(candidates) - patched
    if pending == 0:
        return {
            "state": "patched",
            "found": len(candidates),
            "patched": patched,
            "pending": 0,
            "message": "Фикс плагина активен во всех найденных копиях.",
        }
    return {
        "state": "pending",
        "found": len(candidates),
        "patched": patched,
        "pending": pending,
        "message": f"Фикс плагина не применён: {pending} из {len(candidates)} копий.",
    }


def main():
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "restore":
        restore_auth_plugin_transport()
    else:
        print("patched" if patch_auth_plugin_transport() else "no auth plugin found or patch failed")


if __name__ == "__main__":
    main()
