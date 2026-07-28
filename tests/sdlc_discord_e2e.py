"""Discord SDLC e2e — agent replies + Jira conversation / SA / QA comments."""

from __future__ import annotations

import base64
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.secrets import load_workflow_secrets_into_environ, read_env_file, workflow_secrets_path

WF_ID = os.environ.get("SDLC_WF_ID") or "wf_bd77e2aed1b8"
CHANNELS = {
    "engineering": "1530436643662594179",
    "product": "1530436585022160968",
    "support": "1530436828098724011",
    "standup": "1530436787485278228",
    "marketing": "1528310499773648968",
}

RUN_TAG = os.environ.get("SDLC_RUN_TAG") or time.strftime("SDLC-E2E-%Y%m%d-%H%M")

# Core engineering chain first; cross-channel smoke after.
CORE_ROLES = ("PM", "SA", "Coder", "QA", "DevOps")


def _agent_discord_token() -> str:
    """Prefer a per-agent Discord bot token (Message Content Intent) for history reads."""
    load_workflow_secrets_into_environ(WF_ID)
    try:
        from core.db import get_db
        from core.secrets import (
            agent_has_gateway_credentials,
            resolve_agent_gateway_credentials,
        )
        from core.workflow.repository import WorkflowRepository

        wf = WorkflowRepository(get_db()).get_workflow(WF_ID)
        if wf:
            preferred = ("pm", "sa", "coder", "devops", "marketing", "qa")
            by_role = {a.role_id.lower(): a for a in wf.agents}
            for role in preferred:
                ag = by_role.get(role)
                if not ag:
                    continue
                if not agent_has_gateway_credentials(
                    wf.id, ag.id, "discord", ag.platform_identity
                ):
                    continue
                creds = resolve_agent_gateway_credentials(
                    wf.id, ag.id, "discord", ag.platform_identity
                )
                t = (creds.get("DISCORD_BOT_TOKEN") or "").strip()
                if t:
                    return t
    except Exception:
        pass
    return ""


def _post_token() -> str:
    """Post as a non-agent bot when possible so agent gateways still receive the message."""
    load_workflow_secrets_into_environ(WF_ID)
    t = (os.environ.get("DISCORD_BOT_TOKEN") or "").strip()
    if t:
        return t
    t = _agent_discord_token()
    if not t:
        raise SystemExit("DISCORD_BOT_TOKEN missing")
    return t


def _read_token() -> str:
    """Read history with an agent token that has Message Content Intent."""
    t = _agent_discord_token()
    if t:
        return t
    t = (os.environ.get("DISCORD_BOT_TOKEN") or "").strip()
    if not t:
        raise SystemExit("DISCORD_BOT_TOKEN missing")
    return t


def _token() -> str:
    """Backward-compatible alias — prefer read token for identity checks."""
    return _read_token()


def _jira_creds() -> tuple[str, str, str]:
    """Return (base_url, email, api_token)."""
    load_workflow_secrets_into_environ(WF_ID)
    env = read_env_file(workflow_secrets_path(WF_ID))
    token = (os.environ.get("JIRA_API_TOKEN") or env.get("JIRA_API_TOKEN") or "").strip()
    # Prefer live tracking config from DB
    from core.db import get_db
    from core.workflow.repository import WorkflowRepository

    wf = WorkflowRepository(get_db()).get_workflow(WF_ID)
    jira = {}
    if wf and (wf.tracking_config or {}).get("jira"):
        jira = dict(wf.tracking_config["jira"])
    base = (jira.get("base_url") or "https://denniswongdev.atlassian.net").rstrip("/")
    email = jira.get("email") or "denniswong1986@gmail.com"
    if not token:
        raise SystemExit("JIRA_API_TOKEN missing")
    return base, email, token


def _api(method: str, path: str, token: str, body: dict | None = None):
    data = None
    headers = {
        "Authorization": f"Bot {token}",
        "User-Agent": "hermes-omc-sdlc-e2e",
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
            parsed = json.loads(raw) if raw else {"error": str(e)}
        except Exception:
            parsed = {"error": raw[:300]}
        return e.code, parsed


def _jira_api(method: str, path: str, base: str, email: str, token: str, body=None):
    auth = base64.b64encode(f"{email}:{token}".encode()).decode()
    data = None
    headers = {
        "Authorization": f"Basic {auth}",
        "Accept": "application/json",
        "User-Agent": "hermes-omc-sdlc-e2e",
    }
    if body is not None:
        data = json.dumps(body).encode()
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(
        f"{base}{path}",
        data=data,
        headers=headers,
        method=method,
    )
    try:
        with urllib.request.urlopen(req, timeout=45) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            return resp.status, json.loads(raw) if raw else {}
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", errors="replace")
        try:
            parsed = json.loads(raw) if raw else {"error": str(e)}
        except Exception:
            parsed = {"error": raw[:400]}
        return e.code, parsed


def post(token: str, channel_id: str, content: str) -> str:
    status, data = _api("POST", f"/channels/{channel_id}/messages", token, {"content": content})
    if status not in (200, 201):
        raise RuntimeError(f"post failed {status}: {data}")
    return str(data["id"])


def history(token: str, channel_id: str, after: str, limit: int = 30) -> list[dict]:
    status, data = _api(
        "GET",
        f"/channels/{channel_id}/messages?after={after}&limit={limit}",
        token,
    )
    if status != 200:
        return []
    return list(reversed(data if isinstance(data, list) else []))


def _is_processing(content: str) -> bool:
    c = content or ""
    return "working…" in c or "working..." in c or "Processing..." in c


def _role_matched(content: str, role: str) -> bool:
    """Match legacy **[@ROLE]** and new card/block/quote/sections headers."""
    r = role.upper()
    c = content or ""
    needles = (
        f"**[@{r}]**",
        f"**[@{role}]**",
        f"**[@{role.capitalize()}]**",
        f"AGENT  {r}",
        f"║  {r}",
        f"RESPONSE · {r}",
        f"🗣️ **{r}**",
        f"{r}  ·  reply",
        f"{r} · reply",
    )
    return any(n in c for n in needles)


def wait_for_role(
    token: str,
    channel_id: str,
    after_id: str,
    role: str,
    timeout_sec: float = 240,
) -> tuple[bool, str, str]:
    deadline = time.time() + timeout_sec
    last = ""
    while time.time() < deadline:
        msgs = history(token, channel_id, after_id)
        for m in msgs:
            content = m.get("content") or ""
            author = m.get("author") or {}
            if not author.get("bot"):
                continue
            if _is_processing(content):
                last = content[:160]
                continue
            if _role_matched(content, role) and content.strip():
                return True, content, str(m.get("id") or after_id)
        time.sleep(4)
    return False, last or "timeout — no agent reply", after_id


def extract_task_id(text: str) -> str:
    m = re.search(r"\b(TASK-\d+)\b", text or "", re.I)
    return m.group(1).upper() if m else ""


def extract_jira_key(text: str) -> str:
    """Prefer the highest HOAO number (newest ticket) when multiple keys appear."""
    keys = re.findall(r"\b(HOAO-\d+)\b", text or "", re.I)
    if not keys:
        return ""
    return max((k.upper() for k in keys), key=lambda k: int(k.split("-", 1)[1]))


def adf_to_text(node) -> str:
    if node is None:
        return ""
    if isinstance(node, str):
        return node
    if isinstance(node, list):
        return "\n".join(adf_to_text(x) for x in node)
    if isinstance(node, dict):
        if node.get("type") == "text":
            return str(node.get("text") or "")
        parts = [adf_to_text(node.get("content"))]
        if node.get("type") in ("paragraph", "heading", "listItem", "blockquote"):
            parts.append("\n")
        return "".join(parts)
    return ""


def fetch_jira_comments(issue_key: str) -> list[str]:
    base, email, token = _jira_creds()
    status, data = _jira_api(
        "GET",
        f"/rest/api/3/issue/{issue_key}/comment",
        base,
        email,
        token,
    )
    if status != 200:
        print(f"Jira comments fetch failed {status}: {data}")
        return []
    out: list[str] = []
    for c in data.get("comments") or []:
        body = c.get("body")
        out.append(adf_to_text(body).strip())
    return out


def fetch_jira_issue(issue_key: str) -> dict:
    base, email, token = _jira_creds()
    status, data = _jira_api(
        "GET",
        f"/rest/api/3/issue/{issue_key}?fields=summary,description,status,comment",
        base,
        email,
        token,
    )
    if status != 200:
        return {"error": data, "status": status}
    return data


def build_cases(task_ref: str) -> list[tuple[str, str, str]]:
    """Build prompts; engineering chain embeds TASK so comments attach to one Jira issue."""
    ref = task_ref or RUN_TAG
    return [
        (
            "engineering",
            "PM",
            f"@PM Create/track a Jira task for {RUN_TAG}: passwordless magic-link login "
            f"(email OTP, 15m expiry). Set status todo. Then @SA and instruct them to post "
            f"full API spec + numbered acceptance/test cases, then hand to @Coder.",
        ),
        (
            "engineering",
            "SA",
            f"@SA On {ref} ({RUN_TAG}): write implementable API spec (endpoints, token flow, "
            f"expiry, error cases) AND numbered acceptance/test cases for QA. "
            f"Status in progress. Then @Coder.",
        ),
        (
            "engineering",
            "Coder",
            f"@Coder On {ref} ({RUN_TAG}): implement per SA spec — reply with a short Python "
            f"stub for magic_link_login() + note what was covered. Status in review. Then @QA.",
        ),
        (
            "engineering",
            "QA",
            f"@QA On {ref} ({RUN_TAG}): execute the SA acceptance/test cases. Post a test-result "
            f"table (case id, result PASS/FAIL, notes). If all pass set qa verified; else qa failed. "
            f"Then @DevOps.",
        ),
        (
            "engineering",
            "DevOps",
            f"@DevOps On {ref} ({RUN_TAG}): one-line deploy note for magic-link login; "
            f"status ready to deploy.",
        ),
        (
            "product",
            "PM",
            f"@PM {RUN_TAG}: one-line product priority for magic-link login ({ref}).",
        ),
        (
            "support",
            "SA",
            f"@SA {RUN_TAG} triage on {ref}: user never received magic-link email. One-line next step.",
        ),
        (
            "standup",
            "Standup",
            f"@Standup {RUN_TAG}: one-line daily digest — magic-link login ({ref}) in progress.",
        ),
        (
            "marketing",
            "Marketing",
            f"@Marketing {RUN_TAG}: one-line launch blurb for magic-link login.",
        ),
    ]


def _content_ok_for_role(role: str, content: str) -> bool:
    """Extra quality gates so SA/QA Jira comments carry usable artifacts."""
    c = (content or "").lower()
    if role.upper() == "SA":
        has_spec = any(k in c for k in ("endpoint", "api", "spec", "token", "otp", "expiry"))
        has_tests = any(
            k in c for k in ("test case", "acceptance", "tc-1", "tc1", "1.", "1)")
        )
        return has_spec and has_tests and len(content) > 200
    if role.upper() == "CODER":
        thin = any(
            k in c
            for k in (
                "waiting on",
                "waiting for",
                "nothing in progress",
                "before starting",
            )
        )
        has_impl = any(
            k in c
            for k in (
                "def ",
                "magic_link",
                "stub",
                "implement",
                "```",
                "in review",
            )
        )
        return (not thin) and has_impl and len(content) > 80
    if role.upper() == "QA":
        return any(k in c for k in ("pass", "fail", "qa verified", "qa failed", "test result"))
    return True


def wait_or_nudge(
    read_token: str,
    post_token: str,
    channel_id: str,
    after_id: str,
    role: str,
    prompt: str,
    *,
    handoff_wait: float = 120,
    timeout_sec: float = 360,
) -> tuple[bool, str, str]:
    """
    Prefer a natural handoff reply. If none (or too thin), post an explicit nudge.
    Returns (ok, content, latest_message_id).
    """
    print(f"… watching for @{role} handoff (up to {int(handoff_wait)}s)")
    ok, detail, mid = wait_for_role(
        read_token, channel_id, after_id, role, timeout_sec=handoff_wait
    )
    if ok and _content_ok_for_role(role, detail):
        print(f"handoff @{role} OK (no nudge)")
        return True, detail, mid

    if ok:
        print(f"handoff @{role} too thin — nudging with explicit prompt")
        after_id = mid
    else:
        print(f"no @{role} handoff — posting explicit prompt")

    nudge_id = post(post_token, channel_id, prompt)
    print(f"posted nudge {nudge_id}")
    time.sleep(2)
    ok2, detail2, mid2 = wait_for_role(
        read_token, channel_id, nudge_id, role, timeout_sec=timeout_sec
    )
    return ok2, detail2, mid2 if ok2 else nudge_id


def _safe(text: str) -> str:
    return text.encode("ascii", errors="replace").decode("ascii")


def verify_jira(issue_key: str, task_id: str) -> dict[str, bool]:
    """Assert conversation + SA spec/tests + QA results appear as Jira comments."""
    issue = fetch_jira_issue(issue_key)
    comments = fetch_jira_comments(issue_key)
    blob = "\n---\n".join(comments).lower()
    desc = adf_to_text((issue.get("fields") or {}).get("description")).lower()
    summary = str((issue.get("fields") or {}).get("summary") or "")

    roles_seen = {
        "pm": any("[pm" in c.lower() for c in comments),
        "sa": any("[sa" in c.lower() for c in comments),
        "coder": any("[coder" in c.lower() for c in comments),
        "qa": any("[qa" in c.lower() for c in comments),
    }

    sa_spec = any(
        ("[sa" in c.lower())
        and (
            "endpoint" in c.lower()
            or "spec" in c.lower()
            or "acceptance" in c.lower()
            or "test case" in c.lower()
            or "api" in c.lower()
        )
        for c in comments
    )
    sa_tests = any(
        ("[sa" in c.lower())
        and (
            "test case" in c.lower()
            or "acceptance" in c.lower()
            or re.search(r"\btc[-\s]?\d+", c.lower())
            or re.search(r"\b\d+[.)]\s+", c)
        )
        for c in comments
    )
    qa_results = any(
        ("[qa" in c.lower())
        and (
            "pass" in c.lower()
            or "fail" in c.lower()
            or "qa verified" in c.lower()
            or "qa failed" in c.lower()
            or "test result" in c.lower()
        )
        for c in comments
    )

    print(f"\n========== JIRA {issue_key} ==========")
    print(f"summary: {_safe(summary)}")
    print(f"comments: {len(comments)}")
    for i, c in enumerate(comments, 1):
        print(f"--- comment {i} ---")
        print(_safe(c[:500]))
        if len(c) > 500:
            print("...")

    checks = {
        "issue_exists": "key" in issue or "fields" in issue,
        "has_pm_comment": roles_seen["pm"],
        "has_sa_comment": roles_seen["sa"],
        "has_coder_comment": roles_seen["coder"],
        "has_qa_comment": roles_seen["qa"],
        "sa_spec_in_comments": sa_spec,
        "sa_test_cases_in_comments": sa_tests,
        "qa_results_in_comments": qa_results,
        "conversation_multi_turn": len(comments) >= 3,
        "run_tag_or_task_referenced": (
            RUN_TAG.lower() in blob
            or (task_id and task_id.lower() in blob)
            or RUN_TAG.lower() in desc
            or RUN_TAG.lower() in summary.lower()
        ),
    }
    print("\nJira checks:")
    for k, v in checks.items():
        print(f"  {'PASS' if v else 'FAIL'} {k}")
    return checks


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    post_token = _post_token()
    read_token = _read_token()
    status, me = _api("GET", "/users/@me", post_token)
    print(f"Post bot: {me.get('username')} ({me.get('id')}) http={status}")
    status_r, me_r = _api("GET", "/users/@me", read_token)
    print(f"Read bot: {me_r.get('username')} ({me_r.get('id')}) http={status_r}")
    print(f"WF_ID: {WF_ID}")
    print(f"RUN_TAG: {RUN_TAG}")
    print("Tracking: Jira HOAO (live)")

    task_id = ""
    jira_key = ""
    results: list[tuple[str, str, bool, str]] = []
    last_eng_msg = ""

    cases = build_cases(RUN_TAG)
    start_from = (os.environ.get("SDLC_START_FROM") or "").strip().lower()
    skip = bool(start_from)
    # Engineering roles after PM follow handoffs to avoid double-firing Hermes.
    eng_follow = {"SA", "Coder", "QA", "DevOps"}

    for idx, (topic, role, prompt) in enumerate(cases):
        key = f"{topic}:{role}".lower()
        if skip:
            if key == start_from or role.lower() == start_from:
                skip = False
            else:
                print(f"\n=== #{topic} @{role} === SKIP (resume)")
                continue

        if topic == "engineering" and role != "PM" and task_id:
            ref = f"{task_id}" + (f" / {jira_key}" if jira_key else "")
            cases = build_cases(ref)
            _, _, prompt = cases[idx]

        ch = CHANNELS[topic]
        print(f"\n=== #{topic} @{role} ===")
        print(f">>> {prompt}")

        try:
            if topic == "engineering" and role in eng_follow and last_eng_msg:
                ok, detail, mid = wait_or_nudge(
                    read_token,
                    post_token,
                    ch,
                    last_eng_msg,
                    role,
                    prompt,
                    handoff_wait=150 if role == "SA" else 120,
                    timeout_sec=420,
                )
            else:
                mid = post(post_token, ch, prompt)
                print(f"posted {mid}")
                time.sleep(2)
                timeout = 420 if role in {"SA", "Coder", "QA"} else 240
                ok, detail, mid = wait_for_role(
                    read_token, ch, mid, role, timeout_sec=timeout
                )
        except Exception as e:
            results.append((topic, role, False, str(e)))
            print(f"FAIL post/wait: {e}")
            time.sleep(2)
            continue

        results.append((topic, role, ok, detail))
        print(("OK" if ok else "FAIL"), _safe(detail.replace("\n", " | ")[:280]))

        if topic == "engineering" and mid:
            last_eng_msg = mid

        if ok and topic == "engineering":
            tid = extract_task_id(detail)
            jkey = extract_jira_key(detail)
            if tid and not task_id:
                task_id = tid
                print(f"captured TASK {task_id}")
            if jkey and (
                not jira_key
                or int(jkey.split("-", 1)[1]) > int(jira_key.split("-", 1)[1])
            ):
                jira_key = jkey
                print(f"captured Jira {jira_key}")

        time.sleep(3)

    print("\n========== DISCORD SUMMARY ==========")
    passed = 0
    for topic, role, ok, detail in results:
        mark = "PASS" if ok else "FAIL"
        if ok:
            passed += 1
        print(f"{mark:4} #{topic:12} @{role:10} {_safe(detail.replace(chr(10), ' ')[:100])}")
    print(f"\n{passed}/{len(results)} agents responded")

    # Fallback: discover latest HOAO issue mentioning RUN_TAG via JQL
    if not jira_key:
        base, email, jtoken = _jira_creds()
        jql = urllib.parse.quote(
            f'project = HOAO AND text ~ "{RUN_TAG}" ORDER BY created DESC'
        )
        st, data = _jira_api(
            "GET",
            f"/rest/api/3/search/jql?jql={jql}&maxResults=5&fields=summary,key",
            base,
            email,
            jtoken,
        )
        # Older Jira: /rest/api/3/search
        if st != 200:
            st, data = _jira_api(
                "GET",
                f"/rest/api/3/search?jql={jql}&maxResults=5&fields=summary,key",
                base,
                email,
                jtoken,
            )
        issues = data.get("issues") or []
        if issues:
            jira_key = issues[0].get("key") or ""
            print(f"JQL fallback issue: {jira_key}")

    jira_ok = True
    if jira_key:
        # Give bridge a moment to finish last comment posts
        time.sleep(5)
        checks = verify_jira(jira_key, task_id)
        jira_ok = all(checks.values())
        print(f"\nJira issue: {jira_key}")
        print(f"URL: https://denniswongdev.atlassian.net/browse/{jira_key}")
    else:
        print("\nFAIL: no Jira issue key discovered — cannot verify comments")
        jira_ok = False

    core = [r for r in results if r[1] in CORE_ROLES and r[0] == "engineering"]
    core_pass = all(r[2] for r in core) and len(core) == 5
    print(
        f"\nCore engineering chain: "
        f"{'PASS' if core_pass else 'FAIL'} | Jira artifacts: {'PASS' if jira_ok else 'FAIL'}"
    )
    return 0 if (passed == len(results) and jira_ok) else 1


if __name__ == "__main__":
    raise SystemExit(main())
