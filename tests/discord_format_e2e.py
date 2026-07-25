"""Post to Discord and assert agent reply matches selected message_format."""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.chat_messages import normalize_message_format
from core.db import get_db
from core.secrets import load_workflow_secrets_into_environ
from core.workflow.repository import WorkflowRepository

WF = "wf_bd77e2aed1b8"
ENG = "1530436643662594179"
STANDUP = "1530436787485278228"


def _api(method: str, path: str, token: str, body: dict | None = None):
    data = None
    headers = {
        "Authorization": f"Bot {token}",
        "User-Agent": "hermes-omc-format-e2e",
        "Accept": "application/json",
    }
    if body is not None:
        data = json.dumps(body).encode()
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(
        f"https://discord.com/api/v10{path}",
        data=data,
        headers=headers,
        method=method,
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            return resp.status, json.loads(raw) if raw else {}
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", errors="replace")
        try:
            parsed = json.loads(raw) if raw else {}
        except Exception:
            parsed = {"error": raw[:300]}
        return e.code, parsed


def _markers(fmt: str) -> tuple[str, ...]:
    fmt = normalize_message_format(fmt)
    if fmt == "block":
        return ("━━━━━━━━", "AGENT  ")
    if fmt == "quote":
        return ("🗣️",)
    if fmt == "sections":
        return ("==============================", "RESPONSE ·")
    return ("╔══", "║  ")


def set_format(fmt: str) -> str:
    repo = WorkflowRepository(get_db())
    wf = repo.get_workflow(WF)
    assert wf and wf.chats
    chat = wf.chats[0]
    cfg = {**(chat.config or {}), "message_format": fmt}
    repo.update_chat(WF, chat.id, {"config": cfg})
    return normalize_message_format(
        (repo.get_workflow(WF).chats[0].config or {}).get("message_format")
    )


def wait_bot_reply(token: str, channel_id: str, after: str, timeout: float = 180) -> str:
    deadline = time.time() + timeout
    last = ""
    while time.time() < deadline:
        status, data = _api(
            "GET",
            f"/channels/{channel_id}/messages?after={after}&limit=20",
            token,
        )
        if status == 200 and isinstance(data, list):
            for m in reversed(data):
                author = m.get("author") or {}
                if not author.get("bot"):
                    continue
                content = m.get("content") or ""
                if "working…" in content or "working..." in content:
                    last = content
                    continue
                if content.strip():
                    return content
        time.sleep(3)
    return last


def run_case(token: str, fmt: str, channel_id: str, prompt: str) -> bool:
    print(f"\n=== format={fmt} ===")
    stored = set_format(fmt)
    print("stored", stored)
    # Bridge must be restarted by caller after set_format for first case;
    # subsequent cases in same process assume restart between formats.
    status, posted = _api(
        "POST",
        f"/channels/{channel_id}/messages",
        token,
        {"content": prompt},
    )
    if status not in (200, 201):
        print("FAIL post", status, posted)
        return False
    mid = posted["id"]
    print("posted", mid)
    reply = wait_bot_reply(token, channel_id, mid)
    safe = reply.encode("ascii", "replace").decode()
    print("reply[:400]=\n", safe[:400])
    needed = _markers(fmt)
    ok = all(m in reply for m in needed)
    # Ensure not stuck on processing-only
    if "working…" in reply and len(reply) < 120:
        ok = False
    print("MATCH" if ok else "MISMATCH", "expected markers", needed)
    return ok


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    load_workflow_secrets_into_environ(WF)
    token = (os.environ.get("DISCORD_BOT_TOKEN") or "").strip()
    if not token:
        raise SystemExit("DISCORD_BOT_TOKEN missing")

    # Prefer standup for a short reply; fall back engineering @PM
    fmt = (os.environ.get("SDLC_FORMAT") or "block").strip().lower()
    channel = STANDUP if fmt else ENG
    prompt = (
        "@Standup One-line digest: format preview test."
        if channel == STANDUP
        else "@PM One-line ack for message-format preview test."
    )
    # Allow override
    if os.environ.get("SDLC_CHANNEL") == "engineering":
        channel = ENG
        prompt = "@PM One-line ack for message-format preview test."

    ok = run_case(token, fmt, channel, prompt)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
