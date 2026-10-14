"""
Health Checker for Antigravity Google & OpenAI Accounts
Performs non-destructive, lightweight ping tests to verify credentials and model latency.
"""

import time
import json
import urllib.request
import urllib.error
import ssl

def test_google_account_health(account: dict, timeout=10) -> dict:
    """
    Tests a Google Antigravity account using its access token.
    Pings cloudcode-pa.googleapis.com to check auth validity and model readiness.
    """
    access_token = account.get("accessToken") or account.get("access")
    email = account.get("email", "unknown")
    project_id = account.get("projectId") or "aicode-consumers"

    if not access_token:
        return {
            "ok": False,
            "status": "error",
            "message": "Access token отсутствует (требуется рефреш)",
            "latency_ms": 0,
            "models_available": False,
        }

    url = "https://cloudcode-pa.googleapis.com/v1internal:fetchAvailableModels"
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
        "User-Agent": "antigravity/cli/1.1.24 (aidev_client; os_type=windows; arch=amd64; cl=974782877; auth_method=consumer)",
        "X-Goog-Api-Client": "google-cloud-sdk vscode_cloudshelleditor/0.1",
        "Client-Metadata": '{"ideType":"ANTIGRAVITY","platform":"WINDOWS","pluginType":"GEMINI"}',
    }
    body = json.dumps({"project": project_id}).encode("utf-8")

    ctx = ssl.create_default_context()
    start_t = time.perf_counter()

    try:
        req = urllib.request.Request(url, data=body, headers=headers, method="POST")
        with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
            elapsed_ms = round((time.perf_counter() - start_t) * 1000)
            data = json.loads(resp.read().decode("utf-8"))
            models = data.get("models", {})
            has_claude = any("claude" in k.lower() for k in models.keys())
            has_gemini = any("gemini" in k.lower() for k in models.keys())

            return {
                "ok": True,
                "status": "active",
                "message": f"Токен валиден, пинг {elapsed_ms} мс",
                "latency_ms": elapsed_ms,
                "has_claude": has_claude,
                "has_gemini": has_gemini,
                "models_count": len(models),
            }
    except urllib.error.HTTPError as e:
        elapsed_ms = round((time.perf_counter() - start_t) * 1000)
        err_msg = e.reason
        try:
            err_body = json.loads(e.read().decode("utf-8"))
            err_msg = err_body.get("error", {}).get("message", err_msg)
        except Exception:
            pass

        if e.code == 401:
            return {
                "ok": False,
                "status": "expired",
                "message": f"Токен истёк (401), требуется обновление ({elapsed_ms} мс)",
                "latency_ms": elapsed_ms,
            }
        elif e.code == 429:
            return {
                "ok": False,
                "status": "rate_limited",
                "message": f"Лимит запросов исчерпан (429 Rate Limit, {elapsed_ms} мс)",
                "latency_ms": elapsed_ms,
            }
        else:
            return {
                "ok": False,
                "status": f"http_{e.code}",
                "message": f"Ошибка {e.code}: {err_msg} ({elapsed_ms} мс)",
                "latency_ms": elapsed_ms,
            }
    except Exception as e:
        elapsed_ms = round((time.perf_counter() - start_t) * 1000)
        return {
            "ok": False,
            "status": "network_error",
            "message": f"Ошибка сети: {str(e)[:100]}",
            "latency_ms": elapsed_ms,
        }


def test_openai_account_health(account: dict, timeout=10) -> dict:
    """
    Tests an OpenAI / ChatGPT account using its access token and backend API.
    Pings the ChatGPT wham/usage endpoint through proxy to verify credentials,
    plan type, model readiness, and latency.
    """
    access_token = account.get("accessToken") or account.get("access")
    account_id = account.get("accountId", "")
    email = account.get("email", "unknown")

    if not access_token:
        return {
            "ok": False,
            "status": "error",
            "message": "Access token отсутствует (требуется вход)",
            "latency_ms": 0,
        }

    try:
        import openai_manager
        # Proactively refresh token if close to expiry
        now_ms = int(time.time() * 1000)
        if account.get("expires", 0) - now_ms < 120000:
            openai_manager.refresh_openai_token(account)
            access_token = account.get("access", access_token)
            account_id = account.get("accountId", account_id)
        opener = openai_manager._get_http_opener(timeout=timeout)
    except Exception:
        opener = urllib.request.build_opener()

    url = "https://chatgpt.com/backend-api/wham/usage"
    headers = {
        "Authorization": f"Bearer {access_token}",
        "chatgpt-account-id": account_id,
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Accept": "application/json",
    }

    start_t = time.perf_counter()

    try:
        req = urllib.request.Request(url, headers=headers, method="GET")
        with opener.open(req, timeout=timeout) as resp:
            elapsed_ms = round((time.perf_counter() - start_t) * 1000)
            data = json.loads(resp.read().decode("utf-8"))
            plan_type = (data.get("plan_type") or account.get("plan_type") or "plus").upper()
            rate_limit = data.get("rate_limit", {})
            allowed = rate_limit.get("allowed", True)
            limit_reached = rate_limit.get("limit_reached", False)

            if limit_reached or not allowed:
                return {
                    "ok": True,
                    "status": "rate_limited",
                    "message": f"Связь активна ({elapsed_ms} мс), но квота исчерпана",
                    "latency_ms": elapsed_ms,
                    "plan_type": plan_type,
                }

            return {
                "ok": True,
                "status": "active",
                "message": f"Токен валиден, связь отличная (пинг {elapsed_ms} мс)",
                "latency_ms": elapsed_ms,
                "plan_type": plan_type,
                "models_available": True,
            }
    except urllib.error.HTTPError as e:
        elapsed_ms = round((time.perf_counter() - start_t) * 1000)
        if e.code == 401:
            return {
                "ok": False,
                "status": "expired",
                "message": f"Сессия истекла (401), требуется рефреш ({elapsed_ms} мс)",
                "latency_ms": elapsed_ms,
            }
        elif e.code == 429:
            return {
                "ok": False,
                "status": "rate_limited",
                "message": f"Квота исчерпана (429 Rate Limit, {elapsed_ms} мс)",
                "latency_ms": elapsed_ms,
            }
        else:
            return {
                "ok": False,
                "status": f"http_{e.code}",
                "message": f"Ошибка {e.code} ({elapsed_ms} мс)",
                "latency_ms": elapsed_ms,
            }
    except Exception as e:
        elapsed_ms = round((time.perf_counter() - start_t) * 1000)
        return {
            "ok": False,
            "status": "network_error",
            "message": f"Ошибка сети: {str(e)[:100]}",
            "latency_ms": elapsed_ms,
        }
