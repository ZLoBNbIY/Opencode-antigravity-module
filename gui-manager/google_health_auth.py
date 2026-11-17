"""Receive a fresh Google health-check token through a captured CLI pipe."""

import json
import math
import time


def refresh_google_health_account(account, run_cmd, node_exe, cli_js):
    """Do not reread disk: standalone quota refresh does not persist access tokens."""
    try:
        email = account["email"]
        if not isinstance(email, str) or not email.strip() or email.startswith("-") or any(c in email for c in "\r\n\x00"):
            raise ValueError("invalid email")
        result = run_cmd([node_exe, cli_js, "health-token", "--email", email], timeout=30)
        if result.returncode != 0:
            raise ValueError("refresh failed")
        token = json.loads(result.stdout)
        access = token.get("accessToken")
        expires = token.get("expires")
        if (token.get("email") != email or not isinstance(access, str) or not access.strip()
                or isinstance(expires, bool) or not isinstance(expires, (int, float))
                or not math.isfinite(expires) or not expires > time.time() * 1000):
            raise ValueError("invalid token response")
        # Update both aliases so an old accessToken cannot shadow a new access.
        return {**account, "accessToken": access, "access": access, "expires": expires,
                "projectId": token.get("projectId") or account.get("projectId")}
    except Exception:
        # CLI output can contain credentials; never propagate it to dialogs/logs.
        raise ValueError("Google token refresh failed") from None
