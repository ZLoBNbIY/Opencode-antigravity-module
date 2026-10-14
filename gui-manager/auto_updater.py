"""
Auto-Updater & GitHub Synchronizer for Antigravity Hub
Checks the platform's release branch for fresh updates and applies them seamlessly.
"""

import os
import sys
import json
import subprocess
import urllib.request
import urllib.error
import ssl
from pathlib import Path

REPO_OWNER = "ZLoBNbIY"
REPO_NAME = "Opencode-antigravity-module"
BRANCH = "linux" if sys.platform.startswith("linux") else "V2"
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

def check_for_updates(repo_dir: Path, timeout=6) -> dict:
    """
    Checks GitHub API for the latest commit on the platform's release branch.
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

    try:
        req = urllib.request.Request(GITHUB_COMMITS_API, headers=headers)
        with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            remote_sha = data.get("sha", "")
            commit_info = data.get("commit", {})
            msg = commit_info.get("message", "").split("\n")[0]
            date_str = commit_info.get("author", {}).get("date", "")
            author = commit_info.get("author", {}).get("name", "Author")

            if not remote_sha:
                return {"has_update": False, "error": "Не удалось определить remote sha"}

            has_update = bool(local_sha and remote_sha and not local_sha.startswith(remote_sha[:7]))

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
        return {
            "has_update": False,
            "local_sha": local_sha[:7] if local_sha else "unknown",
            "remote_sha": "",
            "message": "",
            "date": "",
            "author": "",
            "error": str(e),
        }

def apply_update_git(repo_dir: Path) -> tuple[bool, str]:
    """Applies update via git pull and re-applies patches."""
    flags = subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0
    try:
        proc = subprocess.run(
            ["git", "pull", "origin", BRANCH],
            cwd=str(repo_dir),
            capture_output=True,
            text=True,
            creationflags=flags,
            timeout=30,
        )
        if proc.returncode != 0:
            return False, f"Git pull failed: {proc.stderr or proc.stdout}"

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

        return True, "Обновление успешно загружено и применено!"
    except Exception as e:
        return False, f"Ошибка обновления: {str(e)}"
