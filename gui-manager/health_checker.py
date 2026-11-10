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


def test_openai_model_generation(
    account: dict,
    model: str = "gpt-5.6-sol",
    timeout: int = 15,
    prompt: str = "Reply with exactly: OK",
) -> dict:
    """
    Tests an OpenAI/ChatGPT account by executing a lightweight real model generation request
    via the OpenCode Codex responses endpoint (https://chatgpt.com/backend-api/codex/responses).
    Returns a dict with {ok, status, message, latency_ms, model, response_text}.
    """
    import openai_manager

    access_token = account.get("accessToken") or account.get("access")
    account_id = account.get("accountId", "")

    if not access_token:
        return {
            "ok": False,
            "status": "error",
            "message": "Access token отсутствует (требуется вход в ChatGPT)",
            "latency_ms": 0,
        }

    now_ms = int(time.time() * 1000)
    if account.get("expires", 0) - now_ms < 120000:
        try:
            openai_manager.refresh_openai_token(account)
            access_token = account.get("access", access_token)
            account_id = account.get("accountId", account_id)
        except Exception:
            pass

    opener = openai_manager._get_http_opener(timeout=timeout)
    url = "https://chatgpt.com/backend-api/codex/responses?client_version=0.1.0"
    body = {
        "model": model,
        "input": [{"role": "user", "content": prompt}],
        "max_output_tokens": 16,
        "store": False,
        "stream": True,
    }
    headers = {
        "Authorization": f"Bearer {access_token}",
        "chatgpt-account-id": account_id,
        "originator": "opencode",
        "Content-Type": "application/json",
        "Accept": "text/event-stream",
        "User-Agent": openai_manager.OPENAI_BROWSER_UA,
    }

    t0 = time.perf_counter()
    try:
        req = urllib.request.Request(
            url,
            data=json.dumps(body).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        with opener.open(req, timeout=timeout) as resp:
            elapsed_ms = round((time.perf_counter() - t0) * 1000)
            collected_text = []
            for _ in range(60):
                line = resp.readline()
                if not line:
                    break
                line_str = line.decode("utf-8", errors="ignore").strip()
                if line_str.startswith("data:"):
                    data_str = line_str[5:].strip()
                    if data_str == "[DONE]":
                        break
                    try:
                        chunk = json.loads(data_str)
                        c_type = chunk.get("type")
                        if c_type == "response.output_text.delta":
                            delta = chunk.get("delta", "")
                            if delta:
                                collected_text.append(delta)
                        elif c_type == "response.output_text.done":
                            done_txt = chunk.get("text", "")
                            if done_txt and not collected_text:
                                collected_text.append(done_txt)
                        elif c_type == "response.completed":
                            break
                    except Exception:
                        pass

            text = "".join(collected_text).strip()
            msg = f"Генерация {model} успешна ({elapsed_ms} мс)"
            if text:
                msg += f": «{text[:60]}»"
            return {
                "ok": True,
                "status": "active",
                "message": msg,
                "latency_ms": elapsed_ms,
                "model": model,
                "response_text": text,
            }
    except urllib.error.HTTPError as e:
        elapsed_ms = round((time.perf_counter() - t0) * 1000)
        err_body = ""
        try:
            err_body = e.read().decode("utf-8", errors="ignore")
        except Exception:
            pass

        if e.code == 401:
            return {
                "ok": False,
                "status": "expired",
                "message": f"Сессия OpenAI истекла (401), требуется повторный вход ({elapsed_ms} мс)",
                "latency_ms": elapsed_ms,
            }
        elif e.code == 429:
            return {
                "ok": False,
                "status": "rate_limited",
                "message": f"Квота модели {model} исчерпана (429 Rate Limit, {elapsed_ms} мс)",
                "latency_ms": elapsed_ms,
            }
        elif e.code == 403:
            return {
                "ok": False,
                "status": "geo_blocked",
                "message": f"OpenAI отклонил запрос (403): регион заблокирован или требуется сменить маршрут VLESS/прокси ({elapsed_ms} мс)",
                "latency_ms": elapsed_ms,
            }
        else:
            return {
                "ok": False,
                "status": f"http_{e.code}",
                "message": f"Ошибка OpenAI {e.code}: {err_body[:120]} ({elapsed_ms} мс)",
                "latency_ms": elapsed_ms,
            }
    except Exception as exc:
        elapsed_ms = round((time.perf_counter() - t0) * 1000)
        return {
            "ok": False,
            "status": "network_error",
            "message": f"Ошибка сети при генерации OpenAI: {str(exc)[:100]} ({elapsed_ms} мс)",
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


def test_antigravity_model(account: dict, model_id: str, timeout=30, proxy_url=None,
                           prompt="Reply with exactly: OK") -> dict:
    """Probe generation, preserving the outcome of each endpoint attempted."""
    from google_routes import GATE_HOSTS, describe_route

    attempts = []
    try:
        proxy = _effective_proxy_from_config() if proxy_url is None else proxy_url
    except Exception:
        return {"ok": False, "status": "route_error", "badge": "Ошибка запуска прокси Hub", "attempts": []}
    result = None
    for host in GATE_HOSTS:
        result = _test_antigravity_model_once(account, model_id, timeout, proxy, (f"https://{host}",), prompt=prompt)
        attempt = {key: result[key] for key in ("ok", "status", "latency_ms", "badge", "response_text") if key in result}
        attempt["endpoint"] = host
        try:
            if proxy == "http://127.0.0.1:10880":
                attempt["route"] = describe_route(host)
            else:
                attempt["route"] = "Явный прокси" if proxy else "Системный маршрут / DNS"
        except Exception:
            attempt["route"] = "Ошибка настройки маршрута"
        attempts.append(attempt)
        if result.get("ok") or result.get("status") in ("no_auth", "expired", "output_limit"):
            break
    return {**result, "attempts": attempts}


def format_model_probe_result(result):
    """Safe, human-readable report for model tests and route diagnostics."""
    lines = [result.get("display_name", "Google"), result.get("badge", "Ошибка проверки")]
    for attempt in result.get("attempts", []):
        lines.append(f"\n{attempt['endpoint']}\nМаршрут: {attempt['route']}\n"
                     f"{attempt.get('badge', attempt['status'])} ({attempt.get('latency_ms', 0)} мс)")
        if attempt.get("response_text"):
            lines.append(f"Ответ: {attempt['response_text']}")
    return "\n".join(lines)


def _test_antigravity_model_once(account: dict, model_id: str, timeout=30, proxy_url=None, endpoints=None,
                                prompt="Reply with exactly: OK") -> dict:
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
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {"maxOutputTokens": 2048}
        }
    }

    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
        "User-Agent": "antigravity/cli/1.1.24 (aidev_client; os_type=windows; arch=amd64; cl=974782877; auth_method=consumer)",
    }

    # An explicitly direct probe must not inherit HTTP_PROXY from the Hub process.
    handlers = [urllib.request.ProxyHandler({"http": proxy_url, "https": proxy_url} if proxy_url else {})]
    opener = urllib.request.build_opener(*handlers)

    endpoints = endpoints or [
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
                finish_reasons = []
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
                        if "error" in resp_data:
                            has_error = True
                            error_message = resp_data.get("error", {}).get("message", "API Error")
                        candidates = resp_data.get("candidates", [])
                        if candidates:
                            for cand in candidates:
                                finish_reasons.append(cand.get("finishReason"))
                                parts = cand.get("content", {}).get("parts", [])
                                for part in parts:
                                    txt = part.get("text", "")
                                    if txt and not part.get("thought"):
                                        extracted_texts.append(txt)
                    except Exception:
                        pass

                full_text = " ".join(extracted_texts).lower()
                elapsed = round((time.perf_counter() - t0) * 1000)

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

                if not extracted_texts:
                    last_res = {
                        "ok": False,
                        "status": "output_limit" if "MAX_TOKENS" in finish_reasons else "empty_response",
                        "latency_ms": elapsed,
                        "badge": "🟡 Лимит токенов теста, нет текста" if "MAX_TOKENS" in finish_reasons else "🔴 Нет текста ответа модели",
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
                    "response_text": " ".join(extracted_texts)[:500],
                }
        except urllib.error.HTTPError as e:
            elapsed = round((time.perf_counter() - t0) * 1000)
            raw = e.read().decode("utf-8", errors="ignore")
            err_msg = ""
            try:
                err_msg = json.loads(raw).get("error", {}).get("message", "")
            except Exception:
                pass

            if "user location is not supported" in err_msg.lower():
                continue

            if e.code == 429:
                last_res = {
                    "ok": False,
                    "status": "rate_limited",
                    "latency_ms": elapsed,
                    "badge": "🟡 429: квота или перегрузка модели",
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
                "status": "expired" if e.code == 401 else "overloaded" if e.code == 503 else f"http_{e.code}",
                "latency_ms": elapsed,
                "badge": "🔴 Авторизация отклонена (401)" if e.code == 401 else "🟡 Модель перегружена (503)" if e.code == 503 else f"🔴 Ошибка HTTP {e.code}",
                "color": "#ef4444",
                "display_name": display_name,
            }
        except Exception as e:
            elapsed = round((time.perf_counter() - t0) * 1000)
            last_res = {
                "ok": False,
                "status": "network_error",
                "latency_ms": elapsed,
                "badge": f"🔴 Ошибка сети ({elapsed} мс)",
                "color": "#ef4444",
                "display_name": display_name,
            }

    return last_res or {
        "ok": False,
        "status": "geo_blocked",
        "latency_ms": 0,
        "badge": "🔴 Ошибка региона Google (Region not supported)",
        "color": "#ef4444",
        "display_name": display_name,
    }


def test_provider_deep_probe(provider: str, timeout: int = 15) -> dict:
    """
    Performs a deep, lightweight real API/generation probe through the provider's active route.
    Tests whether actual token generation or authenticated API queries succeed,
    catching HTTP 400 Region not supported, geoblocks, quota limits and auth failures.
    Only triggered manually to preserve quotas and tokens.
    """
    provider = {"claude": "claude-pro", "openrouter": "openrouter-free"}.get(provider, provider)
    
    if provider == "google":
        import antigravity_manager
        accs = antigravity_manager.export_google_accounts()
        if not accs:
            return {"ok": False, "status": "no_account", "message": "Нет подключенных аккаунтов Google"}
        idx = antigravity_manager.get_active_google_account_index()
        acc = accs[idx] if (0 <= idx < len(accs)) else accs[0]
        proxy = _effective_proxy_from_config("google")
        res = _test_antigravity_model_once(acc, "antigravity-gemini-3.8-flash", timeout=timeout, proxy_url=proxy, prompt="ping")
        if res.get("ok"):
            text = (res.get("response_text") or "").strip()
            msg = f"Генерация успешна ({res.get('latency_ms', 0)} мс)"
            if text:
                msg += f": «{text[:60]}»"
            return {"ok": True, "status": "active", "message": msg, "latency_ms": res.get("latency_ms")}
        status = res.get("status")
        badge = res.get("badge", "Ошибка проверки модели")
        if status == "geo_blocked" or "region" in badge.lower() or "location" in badge.lower():
            return {"ok": False, "status": "geo_blocked", "message": "Google отклонил запрос: Регион не поддерживается (HTTP 400). Смените DNS или выберите VLESS."}
        if status == "rate_limited":
            return {"ok": False, "status": "rate_limited", "message": "Связь с Google есть, но лимит запросов модели исчерпан (429 Rate Limit)"}
        return {"ok": False, "status": status, "message": f"{badge}"}

    elif provider == "openai":
        import openai_manager
        accs = openai_manager.load_openai_accounts()
        if not accs:
            return {"ok": False, "status": "no_account", "message": "Нет подключенных аккаунтов ChatGPT"}
        active = next((a for a in accs if a.get("is_active")), accs[0])
        return test_openai_model_generation(active, timeout=timeout)

    elif provider == "claude-pro":
        import claude_manager
        accs = claude_manager.claude_service.load_accounts()
        if not accs:
            return {"ok": False, "status": "no_account", "message": "Нет подключенных аккаунтов Claude Pro"}
        active = next((a for a in accs if a.get("is_active")), accs[0])
        proxy = _effective_proxy_from_config("claude-pro")
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({"http": proxy, "https": proxy} if proxy else {}))
        session_key = active.get("session_key", "")
        headers = {
            "User-Agent": claude_manager.USER_AGENT,
            "Cookie": f"sessionKey={session_key}",
            "Accept": "application/json",
        }
        try:
            t0 = time.perf_counter()
            req = urllib.request.Request("https://claude.ai/api/organizations", headers=headers)
            with opener.open(req, timeout=timeout) as resp:
                elapsed = round((time.perf_counter() - t0) * 1000)
                return {"ok": True, "status": "active", "message": f"Сессия Claude активна ({elapsed} мс)", "latency_ms": elapsed}
        except urllib.error.HTTPError as e:
            if e.code in (401, 403):
                return {"ok": False, "status": "auth_failed", "message": f"Ошибка авторизации Claude ({e.code}): сессия истекла или заблокирована"}
            return {"ok": False, "status": f"http_{e.code}", "message": f"Claude.ai вернул HTTP {e.code}: {e.reason}"}
        except Exception as e:
            return {"ok": False, "status": "network_error", "message": f"Ошибка связи с Claude: {str(e)[:100]}"}

    elif provider == "xpiki":
        import xpiki_manager
        cfg = xpiki_manager.load_xpiki_config()
        api_key = cfg.get("api_key")
        if not api_key:
            return {"ok": False, "status": "no_key", "message": "API-ключ Claude (Xpiki) не задан"}
        base_url = cfg.get("base_url") or xpiki_manager.DEFAULT_BASE_URL
        ok, msg, _ = xpiki_manager.test_xpiki_connection(api_key, base_url, timeout=timeout)
        return {"ok": ok, "status": "active" if ok else "error", "message": msg}

    elif provider == "openrouter-free":
        import openrouter_manager
        api_key = openrouter_manager.load_api_key()
        if not api_key:
            return {"ok": False, "status": "no_key", "message": "API-ключ OpenRouter не задан"}
        proxy = _effective_proxy_from_config("openrouter-free")
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({"http": proxy, "https": proxy} if proxy else {}))
        req = urllib.request.Request("https://openrouter.ai/api/v1/auth/key", headers={
            "Authorization": f"Bearer {api_key}",
            "User-Agent": "AntigravityHub-DeepProbe/1.0"
        })
        try:
            t0 = time.perf_counter()
            with opener.open(req, timeout=timeout) as resp:
                elapsed = round((time.perf_counter() - t0) * 1000)
                data = json.loads(resp.read().decode())
                label = data.get("data", {}).get("label") or "Ключ активен"
                return {"ok": True, "status": "active", "message": f"OpenRouter: {label} ({elapsed} мс)", "latency_ms": elapsed}
        except urllib.error.HTTPError as e:
            if e.code == 403:
                return {"ok": False, "status": "forbidden", "message": "HTTP 403: Доступ запрещен (региональная блокировка OpenRouter или лимит ключа)"}
            return {"ok": False, "status": f"http_{e.code}", "message": f"OpenRouter вернул HTTP {e.code}: {e.reason}"}
        except Exception as e:
            return {"ok": False, "status": "network_error", "message": f"Ошибка соединения с OpenRouter: {str(e)[:100]}"}

    return {"ok": False, "status": "unknown_provider", "message": "Неизвестный провайдер"}

