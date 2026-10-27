"""
Auto-Updater & GitHub Synchronizer for Antigravity Hub
Checks origin/V2 for fresh updates and applies them seamlessly.
"""

import os
import sys
import json
import subprocess
import shutil
import urllib.request
import urllib.error
import ssl
from pathlib import Path

REPO_OWNER = "ZLoBNbIY"
REPO_NAME = "Opencode-antigravity-module"
BRANCH = "V2"
GITHUB_COMMITS_API = f"https://api.github.com/repos/{REPO_OWNER}/{REPO_NAME}/commits/{BRANCH}"

def get_local_commit_sha(repo_dir: Path) -> str:
    """Returns local HEAD SHA if git is available."""
    try:
        flags = subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0
        proc = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(repo_dir),
            capture_output=True,
            text=True,
            creationflags=flags,
            timeout=5,
        )
        if proc.returncode == 0 and proc.stdout.strip():
            return proc.stdout.strip()
    except Exception:
        pass

    # Check local version file fallback
    v_file = repo_dir / ".version"
    if v_file.exists():
        try:
            return v_file.read_text(encoding="utf-8").strip()
        except Exception:
            pass

    return ""

def _git_commit_contains(repo_dir: Path, ancestor_sha: str) -> bool:
    """Return whether local HEAD already contains the advertised commit."""
    try:
        flags = subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0
        result = subprocess.run(
            ["git", "merge-base", "--is-ancestor", ancestor_sha, "HEAD"],
            cwd=str(repo_dir),
            capture_output=True,
            creationflags=flags,
            timeout=5,
        )
        return result.returncode == 0
    except Exception:
        return False


def _has_newer_remote_commit(repo_dir: Path, local_sha: str, remote_sha: str) -> bool:
    """Avoid reporting an update when local work is ahead of the remote commit."""
    if not local_sha or not remote_sha or local_sha == remote_sha:
        return False
    if _git_commit_contains(repo_dir, remote_sha):
        return False
    return True


def check_for_updates(repo_dir: Path, timeout=12) -> dict:
    """
    Checks GitHub API for the latest commit on branch V2.
    Returns:
        {
            "has_update": bool,
            "local_sha": str,
            "remote_sha": str,
            "message": str,
            "date": str,
            "author": str,
            "error": str | None
        }
    """
    local_sha = get_local_commit_sha(repo_dir)

    headers = {
        "User-Agent": "Antigravity-Hub-Updater/2.0",
        "Accept": "application/vnd.github.v3+json",
    }
    ctx = ssl.create_default_context()

    # Build openers to try: direct bypass first, or VLESS if active
    openers = [("direct", urllib.request.build_opener(urllib.request.ProxyHandler({})))]

    try:
        cfg_file = Path.home() / ".config" / "opencode" / "antigravity.json"
        if cfg_file.exists():
            cfg = json.loads(cfg_file.read_text(encoding="utf-8"))
            if cfg.get("vless_enabled") and cfg.get("vless_url"):
                from vless_manager import DEFAULT_HTTP_PORT
                vless_url = f"http://127.0.0.1:{DEFAULT_HTTP_PORT}"
                vless_handler = urllib.request.ProxyHandler({"http": vless_url, "https": vless_url})
                openers.insert(0, ("vless", urllib.request.build_opener(vless_handler)))
            elif cfg.get("proxy") and cfg.get("proxy") != "http://127.0.0.1:51180":
                p_handler = urllib.request.ProxyHandler({"http": cfg.get("proxy"), "https": cfg.get("proxy")})
                openers.insert(0, ("custom_proxy", urllib.request.build_opener(p_handler)))
    except Exception:
        pass

    last_err = None
    for label, opener in openers:
        try:
            req = urllib.request.Request(GITHUB_COMMITS_API, headers=headers)
            with opener.open(req, timeout=timeout) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                remote_sha = data.get("sha", "")
                commit_info = data.get("commit", {})
                msg = commit_info.get("message", "").split("\n")[0]
                date_str = commit_info.get("author", {}).get("date", "")
                author = commit_info.get("author", {}).get("name", "Author")

                if not remote_sha:
                    return {"has_update": False, "error": "Не удалось определить remote sha"}

                has_update = _has_newer_remote_commit(repo_dir, local_sha, remote_sha)

                return {
                    "has_update": has_update,
                    "local_sha": local_sha[:7] if local_sha else "unknown",
                    "remote_sha": remote_sha[:7],
                    "message": msg,
                    "date": date_str,
                    "author": author,
                    "error": None,
                }
        except Exception as e:
            last_err = e
            continue

    return {
        "has_update": False,
        "local_sha": local_sha[:7] if local_sha else "unknown",
        "remote_sha": "",
        "message": "",
        "date": "",
        "author": "",
        "error": str(last_err) if last_err else "Неизвестная ошибка проверки обновлений",
    }

def apply_update_git(repo_dir: Path) -> tuple[bool, str]:
    """Pull updates while preserving local edits, then re-apply bundled patches."""
    flags = subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0

    def git(*args, timeout=30):
        return subprocess.run(
            ["git", *args],
            cwd=str(repo_dir),
            capture_output=True,
            text=True,
            creationflags=flags,
            timeout=timeout,
        )

    def restore_stash():
        return git("stash", "pop", "--index", timeout=30)

    try:
        status = git("status", "--porcelain", timeout=10)
        if status.returncode != 0:
            return False, f"Не удалось проверить локальные изменения: {status.stderr or status.stdout}"

        stashed = bool(status.stdout.strip())
        if stashed:
            stash = git("stash", "push", "--include-untracked", "-m", "antigravity-hub-auto-update")
            if stash.returncode != 0:
                return False, f"Не удалось временно сохранить локальные изменения: {stash.stderr or stash.stdout}"
            # Git may report success even when there was nothing to stash.
            stashed = "No local changes to save" not in (stash.stdout + stash.stderr)

        proc = git("pull", "--rebase", "origin", BRANCH, timeout=60)
        if proc.returncode != 0:
            detail = proc.stderr or proc.stdout
            if stashed:
                restored = restore_stash()
                if restored.returncode != 0:
                    return False, (
                        f"Не удалось загрузить обновление: {detail}\n"
                        "Локальные изменения сохранены в git stash, но не восстановлены автоматически. "
                        f"Восстановите их командой `git stash pop`.\n{restored.stderr or restored.stdout}"
                    )
            return False, f"Не удалось загрузить обновление: {detail}"

        if stashed:
            restored = restore_stash()
            if restored.returncode != 0:
                return False, (
                    "Обновление загружено, но локальные изменения конфликтуют с новой версией. "
                    "Они сохранены в git stash и не потеряны; разрешите конфликт или выполните `git stash pop`.\n"
                    f"{restored.stderr or restored.stdout}"
                )

        # Re-run python fix desktop models
        fix_py = repo_dir / "scripts" / "fix_desktop_models.py"
        if fix_py.exists():
            subprocess.run(
                [sys.executable, str(fix_py)],
                cwd=str(repo_dir),
                capture_output=True,
                creationflags=flags,
                timeout=10,
            )

        # Re-apply generated compatibility patches after the repository update.
        patch_script = repo_dir / "scripts" / "patch_plugin.mjs"
        if patch_script.exists():
            node = shutil.which("node")
            if node:
                patch = subprocess.run(
                    [node, str(patch_script)],
                    cwd=str(repo_dir),
                    capture_output=True,
                    text=True,
                    creationflags=flags,
                    timeout=60,
                )
                if patch.returncode != 0:
                    return False, f"Обновление загружено, но не удалось применить патчи плагина: {patch.stderr or patch.stdout}"

        return True, "Обновление успешно загружено и применено!"
    except Exception as e:
        return False, f"Ошибка обновления: {str(e)}"
