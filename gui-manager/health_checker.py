"""
Health Checker for Antigravity Google & OpenAI Accounts
Performs non-destructive, lightweight ping tests to verify credentials and model latency.
"""

import time
import json
import urllib.request
import urllib.error
import ssl

def test_google_account_health(account: dict, timeout=10, refresh_account=None) -> dict:
    """Refresh stale credentials and retry one rejected token, without a loop."""
    refreshed = False

    def refresh():
        nonlocal account, refreshed
        refreshed = True
        try:
            updated = refresh_account(account)
            if not updated or not (updated.get("accessToken") or updated.get("access")):
                raise ValueError("missing access token")
            account = updated
            return None
        except Exception:
            return {
                "ok": False, "status": "refresh_failed", "latency_ms": 0,
                "message": "Не удалось обновить токен Google. Проверьте сеть; если ошибка повторяется, войдите в аккаунт заново.",
            }

    expires = account.get("expires", 0)
    stale = not (account.get("accessToken") or account.get("access"))
    if isinstance(expires, (int, float)) and expires > 0:
        stale = stale or expires <= time.time() * 1000 + 60000
    if stale and refresh_account:
        failure = refresh()
        if failure:
            return failure
    result = _test_google_account_health_once(account, timeout)
    if result.get("status") == "expired" and refresh_account and not refreshed:
        failure = refresh()
        if failure:
            return failure
        result = _test_google_account_health_once(account, timeout)
    if refreshed and result.get("status") == "expired":
        result["message"] = "Google отклонил обновлённый токен (401). Требуется повторный вход в аккаунт."
    return result


def _test_google_account_health_once(account: dict, timeout=10) -> dict:
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
        proxy_url = _effective_proxy_from_config("google")
        opener = urllib.request.build_opener(
            urllib.request.ProxyHandler({"http": proxy_url, "https": proxy_url})
        )
        with opener.open(req, timeout=timeout) as resp:
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
    except Exception as exc:
        return {
            "ok": False,
            "status": "route_error",
            "message": f"Не удалось подготовить маршрут OpenAI: {type(exc).__name__}",
            "latency_ms": 0,
        }

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


ANTIGRAVITY_MODEL_INTERNAL_MAP = {
    "antigravity-gemini-4-argon": ("Gemini 4 Argon", "gemini-4-argon-medium"),
    "gemini-4-argon": ("Gemini 4 Argon", "gemini-4-argon-medium"),
    "antigravity-gemini-3.8-flash": ("Gemini 3.8 Flash", "gemini-3.8-flash-high"),
    "antigravity-claude-opus-5-5": ("Claude Opus 5.5", "claude-opus-5-5"),
    "antigravity-claude-opus-5-5-thinking": ("Claude Opus 5.5 Thinking", "claude-opus-5-5"),
    "antigravity-claude-sonnet-5-5": ("Claude Sonnet 5.5", "claude-sonnet-5-5"),
    "antigravity-claude-sonnet-5-5-thinking": ("Claude Sonnet 5.5 Thinking", "claude-sonnet-5-5"),
    "antigravity-claude-opus-4-6": ("Claude Opus 4.6", "claude-opus-4-6-thinking"),
    "antigravity-claude-opus-4-6-thinking": ("Claude Opus 4.6 Thinking", "claude-opus-4-6-thinking"),
    "antigravity-claude-sonnet-4-6": ("Claude Sonnet 4.6", "claude-sonnet-4-6"),
    "antigravity-claude-sonnet-4-6-thinking": ("Claude Sonnet 4.6 Thinking", "claude-sonnet-4-6"),
    "antigravity-gpt-oss-120b-medium": ("GPT-OSS 120B", "gpt-oss-120b-medium"),
}


def _effective_proxy_from_config(provider: str = "google") -> str:
    """Return the local dispatcher so Hub API calls use provider routes."""
    import provider_proxy
    return provider_proxy.proxy_url_for_hub_requests()


def test_antigravity_model(account: dict, model_id: str, timeout=6, proxy_url=None) -> dict:
    """
    Tests a specific Antigravity model using a lightweight generation probe.
    Returns: {ok: bool, status: str, latency_ms: int, badge: str, color: str, display_name: str}
    """
    clean_id = model_id.strip()
    if clean_id.startswith("google/"):
        clean_id = clean_id[7:]

    mapping = ANTIGRAVITY_MODEL_INTERNAL_MAP.get(clean_id)
    if mapping:
        display_name, internal_name = mapping
    else:
        display_name = clean_id.replace("antigravity-", "").replace("-", " ").title()
        internal_name = clean_id.replace("antigravity-", "")

    access_token = account.get("accessToken") or account.get("access")
    if proxy_url is None:
        proxy_url = _effective_proxy_from_config()
    if not access_token:
        return {
            "ok": False,
            "status": "no_auth",
            "latency_ms": 0,
            "badge": "🔴 Нет токена",
            "color": "#ef4444",
            "display_name": display_name,
        }

    body = {
        "project": account.get("projectId") or "rising-fact-p41fc",
        "model": internal_name,
        "userAgent": "antigravity",
        "requestType": "agent",
        "request": {
            "contents": [{"role": "user", "parts": [{"text": "1"}]}],
            "generationConfig": {"maxOutputTokens": 2}
        }
    }

    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
        "User-Agent": "antigravity/cli/1.1.24 (aidev_client; os_type=windows; arch=amd64; cl=974782877; auth_method=consumer)",
    }

    handlers = []
    if proxy_url:
        handlers.append(urllib.request.ProxyHandler({"http": proxy_url, "https": proxy_url}))
    opener = urllib.request.build_opener(*handlers)

    endpoints = [
        "https://daily-cloudcode-pa.googleapis.com",
        "https://cloudcode-pa.googleapis.com",
    ]
    last_res = None

    for ep in endpoints:
        url = f"{ep}/v1internal:streamGenerateContent?alt=sse"
        req = urllib.request.Request(url, data=json.dumps(body).encode("utf-8"), headers=headers)
        t0 = time.perf_counter()
        try:
            with opener.open(req, timeout=timeout) as resp:
                elapsed = round((time.perf_counter() - t0) * 1000)
                raw_body = resp.read().decode("utf-8", errors="ignore")

                extracted_texts = []
                has_candidates = False
                has_error = False
                error_message = ""

                for line in raw_body.splitlines():
                    line = line.strip()
                    if not line.startswith("data:"):
                        continue
                    json_str = line[5:].strip()
                    if not json_str:
                        continue
                    try:
                        chunk = json.loads(json_str)
                        if "error" in chunk:
                            has_error = True
                            error_message = chunk.get("error", {}).get("message", "API Error")
                        resp_data = chunk.get("response", chunk)
                        candidates = resp_data.get("candidates", [])
                        if candidates:
                            has_candidates = True
                            for cand in candidates:
                                parts = cand.get("content", {}).get("parts", [])
                                for part in parts:
                                    txt = part.get("text", "")
                                    if txt:
                                        extracted_texts.append(txt)
                    except Exception:
                        pass

                full_text = " ".join(extracted_texts).lower()

                # Check if region is blocked inside SSE stream body
                if "user location is not supported" in full_text or "location is not supported" in error_message.lower():
                    continue

                # Detect deprecated / disabled models returned by Google with 200 OK
                deprecation_phrases = [
                    "is no longer available",
                    "no longer available",
                    "please switch to",
                    "is not available",
                    "deprecated",
                    "discontinued",
                    "is absent from",
                    "restricted to",
                    "unsupported model",
                ]
                if any(phrase in full_text for phrase in deprecation_phrases):
                    return {
                        "ok": False,
                        "status": "deprecated",
                        "latency_ms": elapsed,
                        "badge": "🔴 Отключена Google",
                        "color": "#ef4444",
                        "display_name": display_name,
                    }

                if has_error:
                    last_res = {
                        "ok": False,
                        "status": "api_error",
                        "latency_ms": elapsed,
                        "badge": f"🔴 Ошибка API: {error_message[:24]}" if error_message else "🔴 Ошибка API",
                        "color": "#ef4444",
                        "display_name": display_name,
                    }
                    continue

                if not has_candidates and not extracted_texts:
                    last_res = {
                        "ok": False,
                        "status": "empty_response",
                        "latency_ms": elapsed,
                        "badge": "🔴 Нет ответа модели",
                        "color": "#ef4444",
                        "display_name": display_name,
                    }
                    continue

                return {
                    "ok": True,
                    "status": "active",
                    "latency_ms": elapsed,
                    "badge": f"🟢 Работает ({elapsed} мс)",
                    "color": "#16a34a",
                    "display_name": display_name,
                }
        except urllib.error.HTTPError as e:
            elapsed = round((time.perf_counter() - t0) * 1000)
            raw = e.read().decode("utf-8", errors="ignore")
            err_msg = ""
            try:
                err_msg = json.loads(raw).get("error", {}).get("message", "")
            except Exception:
                pass

            if "User location is not supported" in err_msg:
                continue

            if e.code == 429:
                last_res = {
                    "ok": False,
                    "status": "rate_limited",
                    "latency_ms": elapsed,
                    "badge": "🟡 Лимит 429 (Ранний доступ / квота)",
                    "color": "#f59e0b",
                    "display_name": display_name,
                }
                continue
            if e.code == 404:
                last_res = {
                    "ok": False,
                    "status": "not_found",
                    "latency_ms": elapsed,
                    "badge": "🔴 Не найдена (404)",
                    "color": "#ef4444",
                    "display_name": display_name,
                }
                continue
            last_res = {
                "ok": False,
                "status": f"http_{e.code}",
                "latency_ms": elapsed,
                "badge": f"🔴 Ошибка {e.code}",
                "color": "#ef4444",
                "display_name": display_name,
            }
        except Exception as e:
            elapsed = round((time.perf_counter() - t0) * 1000)
            last_res = {
                "ok": False,
                "status": "error",
                "latency_ms": elapsed,
                "badge": f"🔴 Ошибка сети ({elapsed} мс)",
                "color": "#ef4444",
                "display_name": display_name,
            }

    return last_res or {
        "ok": False,
        "status": "geo_blocked",
        "latency_ms": 0,
        "badge": "🔴 Ошибка региона Google",
        "color": "#ef4444",
        "display_name": display_name,
    }
