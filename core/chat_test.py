"""Probe chat platform credentials (Discord / Slack / Telegram / Zulip)."""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from base64 import b64encode
from typing import Any


def _http_json(
    url: str,
    *,
    method: str = "GET",
    headers: dict[str, str] | None = None,
    body: dict[str, Any] | None = None,
    form: dict[str, str] | None = None,
    timeout: float = 12,
) -> tuple[int, Any]:
    data = None
    hdrs = {
        "User-Agent": "hermes-omc-workflow/chat-test",
        "Accept": "application/json",
    }
    hdrs.update(headers or {})
    if form is not None:
        data = urllib.parse.urlencode(form).encode("utf-8")
        hdrs.setdefault("Content-Type", "application/x-www-form-urlencoded")
    elif body is not None:
        data = json.dumps(body).encode("utf-8")
        hdrs.setdefault("Content-Type", "application/json")
    req = urllib.request.Request(url, data=data, headers=hdrs, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            try:
                parsed = json.loads(raw) if raw else {}
            except Exception:
                parsed = {"raw": raw[:500]}
            return resp.status, parsed
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", errors="replace")
        try:
            parsed = json.loads(raw) if raw else {"error": str(e)}
        except Exception:
            # Cloudflare / HTML error pages (e.g. "error code: 1010")
            snippet = raw.strip().splitlines()[0][:200] if raw.strip() else str(e)
            parsed = {"error": snippet or str(e)}
        return e.code, parsed
    except Exception as e:
        return 0, {"error": str(e)}



def _normalize_discord_token(token: str) -> str:
    t = (token or "").strip()
    if t.lower().startswith("bot "):
        return t[4:].strip()
    return t


def test_discord(token: str) -> dict[str, Any]:
    token = _normalize_discord_token(token)
    if not token:
        return {"ok": False, "platform": "discord", "message": "Bot token is required"}
    status, data = _http_json(
        "https://discord.com/api/v10/users/@me",
        headers={"Authorization": f"Bot {token}"},
    )
    if status == 200 and isinstance(data, dict) and data.get("id"):
        name = data.get("username") or data.get("global_name") or data.get("id")
        return {
            "ok": True,
            "platform": "discord",
            "message": f"Connected as bot @{name}",
            "details": {"id": data.get("id"), "username": name},
        }
    msg = (data or {}).get("message") or (data or {}).get("error") or f"HTTP {status}"
    if "1010" in str(msg):
        msg = "Could not reach Discord API (network/TLS blocked). Check token and network."
    return {"ok": False, "platform": "discord", "message": str(msg)}


def test_slack(bot_token: str, app_token: str = "") -> dict[str, Any]:
    bot_token = (bot_token or "").strip()
    app_token = (app_token or "").strip()
    if not bot_token:
        return {"ok": False, "platform": "slack", "message": "Bot token is required"}
    status, data = _http_json(
        "https://slack.com/api/auth.test",
        method="POST",
        headers={"Authorization": f"Bearer {bot_token}"},
        form={},
    )
    if status == 200 and isinstance(data, dict) and data.get("ok"):
        details: dict[str, Any] = {
            "user": data.get("user"),
            "team": data.get("team"),
            "bot_id": data.get("bot_id"),
        }
        msg = f"Connected as {data.get('user')} on {data.get('team')}"
        if app_token:
            if not app_token.startswith("xapp-"):
                return {
                    "ok": False,
                    "platform": "slack",
                    "message": "Bot OK, but app token should start with xapp-",
                    "details": details,
                }
            details["app_token"] = "present"
            msg += " (app token present)"
        return {"ok": True, "platform": "slack", "message": msg, "details": details}
    err = (data or {}).get("error") or f"HTTP {status}"
    return {"ok": False, "platform": "slack", "message": str(err)}


def test_telegram(token: str) -> dict[str, Any]:
    token = (token or "").strip()
    if not token:
        return {"ok": False, "platform": "telegram", "message": "Bot token is required"}
    status, data = _http_json(f"https://api.telegram.org/bot{token}/getMe")
    if status == 200 and isinstance(data, dict) and data.get("ok"):
        result = data.get("result") or {}
        uname = result.get("username") or result.get("first_name") or result.get("id")
        return {
            "ok": True,
            "platform": "telegram",
            "message": f"Connected as @{uname}",
            "details": result,
        }
    desc = (data or {}).get("description") or (data or {}).get("error") or f"HTTP {status}"
    return {"ok": False, "platform": "telegram", "message": str(desc)}


def test_zulip(site: str, email: str, api_key: str) -> dict[str, Any]:
    site = (site or "").rstrip("/")
    email = (email or "").strip()
    api_key = (api_key or "").strip()
    if not site or not email or not api_key:
        return {
            "ok": False,
            "platform": "zulip",
            "message": "Site URL, bot email, and API key are required",
        }
    if not site.startswith("http"):
        site = "https://" + site
    auth = b64encode(f"{email}:{api_key}".encode()).decode()
    status, data = _http_json(
        f"{site}/api/v1/users/me",
        headers={"Authorization": f"Basic {auth}"},
    )
    if status == 200 and isinstance(data, dict):
        if data.get("result") == "error":
            return {
                "ok": False,
                "platform": "zulip",
                "message": data.get("msg") or "Zulip API error",
            }
        name = data.get("full_name") or data.get("email") or email
        return {
            "ok": True,
            "platform": "zulip",
            "message": f"Connected as {name}",
            "details": {"email": data.get("email") or email, "user_id": data.get("user_id")},
        }
    msg = (data or {}).get("msg") or (data or {}).get("error") or f"HTTP {status}"
    msg = str(msg)
    if msg.lstrip().lower().startswith("<!doctype") or msg.lstrip().lower().startswith("<html"):
        msg = f"Zulip site returned HTML (HTTP {status}) — check Site URL"
    return {"ok": False, "platform": "zulip", "message": msg[:300]}


def test_chat_connection(platform: str, credentials: dict[str, str]) -> dict[str, Any]:
    p = (platform or "").strip().lower()
    creds = {k: (v or "").strip() for k, v in (credentials or {}).items()}
    if p == "discord":
        return test_discord(creds.get("DISCORD_BOT_TOKEN", ""))
    if p == "slack":
        return test_slack(
            creds.get("SLACK_BOT_TOKEN", ""),
            creds.get("SLACK_APP_TOKEN", ""),
        )
    if p == "telegram":
        return test_telegram(creds.get("TELEGRAM_BOT_TOKEN", ""))
    if p == "zulip":
        return test_zulip(
            creds.get("ZULIP_SITE", ""),
            creds.get("ZULIP_EMAIL", ""),
            creds.get("ZULIP_API_KEY", ""),
        )
    return {"ok": False, "platform": p or "unknown", "message": f"Unsupported platform: {p}"}
