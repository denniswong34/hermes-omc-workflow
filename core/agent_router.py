"""
Agent Router — Core Orchestration Logic
=========================================
Routes user messages to the correct Hermes agent (PM, SA, Coder, QA,
Marketing), handles cross-agent forwarding (@mentions), and manages
the SDLC state machine.

This module is CHANNEL-AGNOSTIC — it works with Discord, Zulip, Slack,
or any transport that implements ChannelAdapter.
"""

import asyncio
import logging
import os
import re
import subprocess
from pathlib import Path
from typing import Optional

from adapters.base import ChannelAdapter, Message
from core.sdlc_tracker import SDLCTracker
from core.task_manager import TaskManager


class AgentRouter:
    """Orchestrates Hermes agent calls and cross-channel forwarding."""

    def __init__(
        self,
        adapter: ChannelAdapter,
        channel_prompts: dict[str, str],
        agent_routes: dict[str, list[str]],
        channel_names: dict[str, str],
        channel_by_name: dict[str, str],
        free_channels: set[str],
        sdlc: Optional[SDLCTracker] = None,
        task_mgr: Optional[TaskManager] = None,
        forward_max_depth: int = 5,
    ):
        self.adapter = adapter
        self.channel_prompts = channel_prompts
        self.agent_routes = agent_routes
        self.channel_names = channel_names         # id → name
        self.channel_by_name = channel_by_name     # name → id
        self.free_channels = free_channels
        self.sdlc = sdlc
        self.task_mgr = task_mgr
        self.forward_max_depth = forward_max_depth

        # Dedup
        self._processed_ids: set[str] = set()
        self._processed_max = 300
        self._forward_log: dict[str, set[str]] = {}

    # ── Public entry point ───────────────────────────────────────────

    async def handle_message(self, msg: Message, forward_depth: int = 0):
        """Process an incoming message from any channel."""

        # ── Dedup ──
        if msg.id in self._processed_ids:
            return
        self._processed_ids.add(msg.id)
        if len(self._processed_ids) > self._processed_max:
            self._processed_ids.clear()

        channel_name = msg.channel_name or self.channel_names.get(msg.channel_id, f"ch:{msg.channel_id}")

        # Skip bot's own non-forward messages
        if msg.is_bot and not msg.content.startswith("**[↪"):
            return

        # Check if we should respond
        has_prompt = msg.channel_id in self.channel_prompts
        is_free = msg.channel_id in self.free_channels
        if not (has_prompt or is_free or msg.is_bot):
            return  # Not a channel we handle

        # Extract real content (strip forward prefix)
        content = msg.content
        if msg.content.startswith("**[↪"):
            lines = msg.content.split("\n", 1)
            content = lines[1].strip() if len(lines) > 1 else ""
            logging.info(f"↪ [{channel_name}] Forward received: {content[:80]}")
        else:
            logging.info(f"→ [{channel_name}] {msg.author_name}: {content[:120]}")

        if not content:
            return

        # ── Send ack ──
        ack_id = await self.adapter.send_message(msg.channel_id, "🔄 **Processing...**")
        if not ack_id:
            logging.error(f"Failed to send ack in {channel_name}")
            return

        # ── Build prompt ──
        system_prompt = self.channel_prompts.get(msg.channel_id, "")
        routing_guide = self._build_routing_guide(msg.channel_id)
        quoted_context = await self._fetch_reply_context(msg)
        full_prompt = f"[SYSTEM PROMPT]\n{system_prompt}{routing_guide}{quoted_context}\n\n[MESSAGE]\n{content}"

        # ── Plane SDLC: create/reference ticket ──
        ticket_url, plane_issue_id = await self._resolve_ticket(content, msg.channel_id, full_prompt)
        if ticket_url:
            full_prompt += f"\n\n[TICKET REFERENCE]\nTicket URL: {ticket_url}\n"

        # ── Call Hermes agent ──
        response = await self._call_hermes(full_prompt, msg.channel_id)
        if not response:
            await self.adapter.edit_message(msg.channel_id, ack_id, "⚠️ Empty response. Try again?")
            return

        # ── Parse cross-channel forwards ──
        forwards = self._parse_forwards(response, msg.channel_id)
        for target_id, fwd_msg in forwards:
            await self._forward(msg.channel_id, target_id, fwd_msg, msg.id, forward_depth)

        # ── Prepare display (strip @mentions) ──
        display = self._strip_forwards(response, msg.channel_id)
        if not display or len(display) <= 5:
            if forwards:
                display = f"✅ Message forwarded to agents ✅"
            else:
                await self.adapter.edit_message(msg.channel_id, ack_id, "✅ Done")
                return

        # ── SDLC: update status from response text ──
        if self.sdlc and plane_issue_id:
            status_text = self.sdlc.detect_status(display)
            if status_text:
                await self.sdlc.update_status(plane_issue_id, status_text)

        # ── Append ticket URL + forward note ──
        if ticket_url:
            display += f"\n\n🔗 **Ticket:** {ticket_url}"
        if forwards:
            target_names = ", ".join(
                self.channel_names.get(str(t), "?") for t, _ in forwards
            )
            display += f"\n\n_↪ Forwarded to {target_names}_"

        await self.adapter.edit_message(msg.channel_id, ack_id, display[:1900])
        logging.info(f"✓ [{channel_name}] Response: {display[:80]}")

    # ── Internal helpers ─────────────────────────────────────────────

    def _build_routing_guide(self, channel_id: str) -> str:
        ch_name = self.channel_names.get(channel_id, "#pm")
        targets = self.agent_routes.get(ch_name, [])
        if not targets:
            return ""
        targets_str = ", ".join(targets)
        return (
            f"\n\nCROSS-CHANNEL RULES:\n"
            f"- To talk to another agent, START a line with @channel_name: message\n"
            f"- You can talk to: {targets_str}\n"
            f"- Example: @sa: Please produce a spec for TASK-001\n"
            f"- The bridge will forward your message automatically."
        )

    async def _fetch_reply_context(self, msg: Message) -> str:
        if not msg.reply_to_id:
            return ""
        # Could extend: call adapter to fetch referenced message
        return ""

    async def _resolve_ticket(self, content: str, channel_id: str, prompt: str) -> tuple:
        """Create or reference a Plane.so ticket. Returns (ticket_url, issue_id)."""
        if self.task_mgr is None:
            return ("", None)
        # Simplified logic — delegates to task_mgr
        return ("", None)

    async def _call_hermes(self, prompt: str, channel_id: str) -> Optional[str]:
        """Spawn hermes -z subprocess and return its stdout."""
        session_name = f"omc-{channel_id}"
        try:
            proc = await asyncio.create_subprocess_exec(
                "hermes", "-z", prompt,
                "--resume", session_name,
                "--safe-mode", "--yolo",
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=600)
            response = stdout.decode().strip() if stdout else ""
            return self._clean_response(response)
        except asyncio.TimeoutError:
            logging.error(f"[{channel_id}] Hermes agent timed out")
            return None
        except Exception as e:
            logging.error(f"[{channel_id}] Hermes agent error: {e}")
            return None

    def _clean_response(self, response: str) -> str:
        lines = response.split("\n")
        clean = []
        for l in lines:
            s = l.strip()
            if not s:
                clean.append("")
            elif any(s.startswith(c) for c in ("╭", "╰", "│", "─", "⚠", "✦", "●", "┃", "┣", "┗", "┏", "┓", "┛", "┳", "┻", "┫", "━")):
                continue
            elif re.match(r"^[\d:.,\s\-]+$", s):
                continue
            else:
                clean.append(s)
        result = "\n".join(clean).strip()
        if not result or len(result) < 5:
            meaningful = [l for l in lines if len(l.strip()) > 10 and not l.strip().startswith("Hermes")]
            result = meaningful[-1].strip() if meaningful else response[:1900]
        return result

    def _parse_forwards(self, response: str, source_channel_id: str) -> list[tuple[str, str]]:
        source_name = self.channel_names.get(str(source_channel_id))
        if not source_name:
            return []
        allowed = self.agent_routes.get(source_name, [])
        results = []
        for line in response.split("\n"):
            line = line.strip()
            for target in allowed:
                pattern = rf"^@{target[1:]}:?\s*(.*)"
                m = re.match(pattern, line, re.IGNORECASE)
                if m and m.group(1).strip():
                    target_id = self.channel_by_name.get(target)
                    if target_id and target_id != source_channel_id:
                        results.append((target_id, m.group(1).strip()))
                        break
        return results

    def _strip_forwards(self, response: str, channel_id: str) -> str:
        ch_name = self.channel_names.get(str(channel_id), "")
        allowed = self.agent_routes.get(ch_name, [])
        lines = []
        for line in response.split("\n"):
            is_fwd = False
            for target in allowed:
                if re.match(rf"^@{target[1:]}:?\s", line.strip(), re.IGNORECASE):
                    is_fwd = True
                    break
            if not is_fwd:
                lines.append(line)
        return "\n".join(lines).strip()

    async def _forward(self, from_id: str, to_id: str, content: str, source_msg_id: str, depth: int):
        if depth >= self.forward_max_depth:
            logging.warning(f"Forward depth limit ({self.forward_max_depth})")
            return
        prefixed = f"**[↪ {self.channel_names.get(from_id, '?')} → {self.channel_names.get(to_id, '?')}]** (depth:{depth+1})\n{content}"
        await self.adapter.send_message(to_id, prefixed[:1900])
