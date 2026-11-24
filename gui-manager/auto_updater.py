"""
Auto-Updater & GitHub Synchronizer for Antigravity Hub
Checks upstream V2 and updates clean checkouts without running downloaded scripts.
"""

import os
import json
import re
import subprocess
import urllib.request
from pathlib import Path

REPO_OWNER = "ZLoBNbIY"
REPO_NAME = "Opencode-antigravity-module"
BRANCH = "V2"
GITHUB_COMMITS_API = f"https://api.github.com/repos/{REPO_OWNER}/{REPO_NAME}/commits/{BRANCH}"
UPSTREAM_URL = f"https://github.com/{REPO_OWNER}/{REPO_NAME}.git"
UPSTREAM_REF = f"refs/heads/{BRANCH}"
SHA_RE = re.compile(r"[0-9a-f]{40}")

def get_local_commit_sha(repo_dir: Path) -> str:
    """Return the local checkout's HEAD, or the archive version if provided."""
    try:
        root = _git_output(repo_dir, "rev-parse", "--show-toplevel", timeout=5)
        if root and Path(root).resolve() == repo_dir.resolve():
            sha = _git_output(repo_dir, "rev-parse", "--verify", "HEAD", timeout=5)
            if SHA_RE.fullmatch(sha):
                return sha
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
        return _run_git(repo_dir, "merge-base", "--is-ancestor", ancestor_sha, "HEAD", timeout=5).returncode == 0
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
    if not SHA_RE.fullmatch(local_sha):
        return {
            "has_update": False,
            "local_sha": local_sha[:7] if local_sha else "unknown",
            "remote_sha": "",
            "message": "",
            "date": "",
            "author": "",
            "error": "Не удалось определить локальную версию.",
        }

    headers = {
        "User-Agent": "Antigravity-Hub-Updater/2.0",
        "Accept": "application/vnd.github.v3+json",
    }

    # Hub self-updates must NEVER go through the VLESS tunnel or custom proxies:
    # updating the Hub through its own tunnel breaks when the tunnel is down and
    # creates a dependency loop. ProxyHandler({}) disables autodetection of
    # HTTP(S)_PROXY environment variables, forcing a direct connection.
    openers = [("direct", urllib.request.build_opener(urllib.request.ProxyHandler({})))]

    last_err = None
    for label, opener in openers:
        try:
            req = urllib.request.Request(GITHUB_COMMITS_API, headers=headers)
            with opener.open(req, timeout=timeout) as resp:
                data = json.loads(resp.read(1024 * 1024).decode("utf-8"))
                if not isinstance(data, dict):
                    raise ValueError("Некорректный формат ответа GitHub API")
                remote_sha = data.get("sha", "")
                if not isinstance(remote_sha, str) or not SHA_RE.fullmatch(remote_sha):
                    return {"has_update": False, "error": "Не удалось определить remote sha"}
                commit_info = data.get("commit")
                if not isinstance(commit_info, dict):
                    commit_info = {}
                raw_msg = commit_info.get("message")
                msg = raw_msg.split("\n")[0] if isinstance(raw_msg, str) else ""
                author_info = commit_info.get("author")
                if not isinstance(author_info, dict):
                    author_info = {}
                date_str = author_info.get("date") if isinstance(author_info.get("date"), str) else ""
                author = author_info.get("name") if isinstance(author_info.get("name"), str) else "Author"

                has_update = _has_newer_remote_commit(repo_dir, local_sha, remote_sha)

                return {
                    "has_update": has_update,
                    "local_sha": local_sha[:7] if local_sha else "unknown",
                    "remote_sha": remote_sha[:7],
                    "remote_commit": remote_sha,
                    "message": msg,
                    "date": date_str,
                    "author": author,
                    "error": None,
                }
        except Exception as e:
            last_err = e
            continue

    # If GitHub REST API is throttled (403 rate limit), fall back to git ls-remote directly
    fallback_err = None
    try:
        remote_sha = _upstream_sha(repo_dir)
        has_update = _has_newer_remote_commit(repo_dir, local_sha, remote_sha)
        return {
            "has_update": has_update,
            "local_sha": local_sha[:7] if local_sha else "unknown",
            "remote_sha": remote_sha[:7],
            "remote_commit": remote_sha,
            "message": "Обновление ветки V2",
            "date": "",
            "author": "GitHub",
            "error": None,
        }
    except Exception as e:
        fallback_err = e

    if fallback_err is not None and last_err is not None:
        error_text = f"{fallback_err} (API: {last_err})"
    elif fallback_err is not None:
        error_text = str(fallback_err)
    elif last_err is not None:
        error_text = str(last_err)
    else:
        error_text = "Неизвестная ошибка проверки обновлений"

    return {
        "has_update": False,
        "local_sha": local_sha[:7] if local_sha else "unknown",
        "remote_sha": "",
        "message": "",
        "date": "",
        "author": "",
        "error": error_text,
    }

def _direct_git_env() -> dict:
    """Do not inherit repository, Git configuration, or proxy overrides."""
    env = {
        key: value for key, value in os.environ.items()
        if not key.upper().startswith("GIT_")
        and key.upper() not in {"HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "FTP_PROXY"}
    }
    env["GIT_TERMINAL_PROMPT"] = "0"
    env["GIT_NO_LAZY_FETCH"] = "1"
    return env


def _run_git(repo_dir: Path, *args, timeout=15):
    return subprocess.run(
        [
            "git", "--no-replace-objects",
            "-c", "core.hooksPath=/dev/null",
            "-c", "core.fsmonitor=false",
            "-c", "core.filemode=false",
            "-c", "submodule.recurse=false",
            "-c", "merge.autostash=false",
            "-c", "http.sslVerify=true",
            "-c", "http.proxy=",
            "-c", f"http.{UPSTREAM_URL}.sslVerify=true",
            "-c", f"http.{UPSTREAM_URL}.proxy=",
            "-c", "http.followRedirects=false",
            "-c", f"http.{UPSTREAM_URL}.followRedirects=false",
            "-c", "credential.helper=",
            "-c", "fetch.fsckObjects=true",
            "-c", "protocol.allow=never",
            "-c", "protocol.https.allow=always",
            *args,
        ],
        cwd=str(repo_dir),
        capture_output=True,
        text=True,
        errors="replace",
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        timeout=timeout,
        env=_direct_git_env(),
    )


def _git_output(repo_dir: Path, *args, timeout=15) -> str:
    result = _run_git(repo_dir, *args, timeout=timeout)
    if result.returncode:
        detail = (result.stderr or result.stdout).strip()
        raise RuntimeError(f"git {args[0]} (код {result.returncode}): {detail}")
    return result.stdout.strip()


def _upstream_sha(repo_dir: Path) -> str:
    # Refuse URL rewrites rather than silently updating from a different server.
    if _git_output(repo_dir, "ls-remote", "--get-url", UPSTREAM_URL) != UPSTREAM_URL:
        raise RuntimeError("Настройка Git перенаправляет адрес обновления; обновление отменено.")
    result = _git_output(repo_dir, "ls-remote", "--exit-code", UPSTREAM_URL, UPSTREAM_REF, timeout=20)
    sha, separator, ref = result.partition("\t")
    if not separator or ref != UPSTREAM_REF or not SHA_RE.fullmatch(sha):
        raise RuntimeError("GitHub не вернул однозначный идентификатор ветки V2.")
    return sha


def _clean_v2_head(repo_dir: Path) -> str:
    root = _git_output(repo_dir, "rev-parse", "--show-toplevel")
    if not root or Path(root).resolve() != repo_dir.resolve():
        raise RuntimeError("Каталог Hub не является корнем Git-репозитория.")
    if _git_output(repo_dir, "symbolic-ref", "--quiet", "HEAD") != UPSTREAM_REF:
        raise RuntimeError("Автообновление доступно только на локальной ветке V2.")
    for operation in ("MERGE_HEAD", "CHERRY_PICK_HEAD", "REVERT_HEAD", "REBASE_HEAD",
                      "rebase-merge", "rebase-apply", "sequencer", "BISECT_START"):
        location = _git_output(repo_dir, "rev-parse", "--git-path", operation)
        if not location or (repo_dir / location).exists():
            raise RuntimeError("Завершите текущую операцию Git перед автообновлением.")
    status_result = _run_git(repo_dir, "status", "--porcelain", "--untracked-files=all", "--ignore-submodules=none")
    if status_result.returncode:
        detail = (status_result.stderr or status_result.stdout).strip()
        raise RuntimeError(f"git status (код {status_result.returncode}): {detail}")
    dirty_entries = [line.strip() for line in status_result.stdout.splitlines() if line.strip()]
    if dirty_entries:
        preview = ", ".join(dirty_entries[:5])
        if len(dirty_entries) > 5:
            preview += f" и ещё {len(dirty_entries) - 5}"
        raise RuntimeError(
            f"Есть локальные изменения или неотслеживаемые файлы ({preview}). Автообновление отменено."
        )
    sha = _git_output(repo_dir, "rev-parse", "--verify", "HEAD")
    if not SHA_RE.fullmatch(sha):
        raise RuntimeError("Не удалось определить локальный коммит.")
    return sha


def _is_ancestor(repo_dir: Path, ancestor: str, descendant: str) -> bool:
    result = _run_git(repo_dir, "merge-base", "--is-ancestor", ancestor, descendant)
    if result.returncode not in (0, 1):
        raise RuntimeError(f"Не удалось проверить историю Git: {result.stderr.strip()}")
    return result.returncode == 0


def apply_update_git(repo_dir: Path, *, expected_commit: str | None = None) -> tuple[bool, str]:
    """Fast-forward a clean V2 checkout to the exact GitHub-advertised commit."""
    merge_started = False
    try:
        before = _clean_v2_head(repo_dir)
        target = _upstream_sha(repo_dir)
        if expected_commit is not None and expected_commit != target:
            return False, "Удалённый коммит изменился после проверки. Проверьте обновление ещё раз."
        if before == target:
            return True, "Ветка V2 уже содержит последнее обновление. Файлы не менялись."

        # Fetch just the advertised object, without changing tracking refs or
        # relying on shared FETCH_HEAD. No tags or submodules are updated.
        _git_output(repo_dir, "fetch", "--no-tags", "--no-recurse-submodules",
                    "--no-write-fetch-head", "--no-auto-maintenance", "--refmap=", UPSTREAM_URL, target, timeout=60)
        if _is_ancestor(repo_dir, target, before):
            return True, "Локальная ветка V2 уже содержит этот коммит. Файлы не менялись."
        if not _is_ancestor(repo_dir, before, target):
            return False, "История локальной ветки V2 разошлась с GitHub. Требуется ручное обновление."
        if _clean_v2_head(repo_dir) != before:
            return False, "Локальный коммит изменился во время загрузки. Повторите обновление."

        merge_started = True
        _git_output(repo_dir, "merge", "--ff-only", "--no-autostash", "--no-overwrite-ignore", target, timeout=60)
        if _git_output(repo_dir, "rev-parse", "--verify", "HEAD") != target:
            raise RuntimeError("Не удалось подтвердить обновлённый коммит.")
        return True, (
            f"Ветка V2 обновлена до {target[:7]}. Подпись коммита не проверялась; "
            "проверьте изменения перед перезапуском. Скрипты установки и патчи не запускались."
        )
    except Exception as e:
        if merge_started:
            return False, f"Не удалось подтвердить завершение обновления: {e}. Проверьте git status и HEAD; откат не выполнялся."
        return False, f"Обновление остановлено до изменения рабочей копии: {e}"
