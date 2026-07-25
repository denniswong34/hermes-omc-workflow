"""MCP tool proxy — normalize MCP for engines without native support."""

from __future__ import annotations

import json
import logging
from typing import Any

logger = logging.getLogger(__name__)


def inject_mcp_tool_hints(prompt: str, mcp_configs: list[dict[str, Any]]) -> str:
    """
    Inject available MCP server descriptions into the prompt.
    Full stdio MCP bridging is optional; v1 provides discovery + call contract.
    """
    if not mcp_configs:
        return prompt
    lines = ["[MCP TOOLS AVAILABLE — request with [MCP_CALL server=<id> tool=<name> args=<json>]]"]
    for cfg in mcp_configs:
        name = cfg.get("name") or cfg.get("catalog_id") or cfg.get("id")
        desc = cfg.get("description") or ""
        cmd = cfg.get("command") or []
        lines.append(f"- {name}: {desc} (transport={cfg.get('transport', 'stdio')}, cmd={cmd})")
    block = "\n".join(lines)
    return f"{block}\n\n{prompt}"


def parse_mcp_calls(text: str) -> list[dict[str, Any]]:
    """Extract [MCP_CALL ...] markers from agent output (best-effort)."""
    import re

    pattern = re.compile(
        r"\[MCP_CALL\s+server=(?P<server>[^\s]+)\s+tool=(?P<tool>[^\s]+)\s+args=(?P<args>\{.*?\})\]",
        re.DOTALL,
    )
    out = []
    for m in pattern.finditer(text or ""):
        try:
            args = json.loads(m.group("args"))
        except Exception:
            args = {}
        out.append(
            {
                "server": m.group("server"),
                "tool": m.group("tool"),
                "args": args,
            }
        )
    return out


async def invoke_mcp_stub(call: dict[str, Any], server_cfg: dict[str, Any]) -> str:
    """
    Placeholder invocation — logs intent. Real stdio MCP client can replace this.
    """
    logger.info(
        "MCP stub invoke server=%s tool=%s args=%s cmd=%s",
        call.get("server"),
        call.get("tool"),
        call.get("args"),
        server_cfg.get("command"),
    )
    return (
        f"[MCP] Server '{call.get('server')}' tool '{call.get('tool')}' "
        f"queued (proxy stub). Configure engine-native MCP for live calls."
    )
