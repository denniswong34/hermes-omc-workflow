"""
Agent Router — Core Orchestration Logic
=========================================
Routes user messages to the correct Hermes agent (PM, SA, Coder, QA,
DevOps, Marketing), handles cross-agent forwarding (@mentions), and manages
the SDLC ticket lifecycle via a pluggable TicketTracker.
"""

from __future__ import annotations

import asyncio
import logging
import re
import subprocess
from typing import Optional

from adapters.base import ChannelAdapter, Message
from core.sdlc_tracker import SDLCTracker
from core.task_manager import TaskManager
from core.tickets.base import TicketTracker


class AgentRouter:
    """Orchestrates Hermes agent calls and cross-channel forwarding."""

    # Channels allowed to create new tickets when content implies new work
    TICKET_CREATE_CHANNELS = {"#pm", "#sa"}

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
        ticket_tracker: Optional[TicketTracker] = None,
        ticket_provider: str = "none",
        forward_max_depth: int = 5,
    ):
        self.adapter = adapter
        self.channel_prompts = channel_prompts
        self.agent_routes = agent_routes
        self.channel_names = channel_names
        self.channel_by_name = channel_by_name
        self.free_channels = free_channels
        self.sdlc = sdlc
        self.task_mgr = task_mgr
        self.ticket_tracker = ticket_tracker
        self.ticket_provider = ticket_provider
        self.forward_max_depth = forward_max_depth

        self._processed_ids: set[str] = set()
        self._processed_max = 300

    async def handle_message(self, msg: Message, forward_depth: int = 0):
        if msg.id in self._processed_ids:
            return
        self._processed_ids.add(msg.id)
        if len(self._processed_ids) > self._processed_max:
            self._processed_ids.clear()

        channel_name = msg.channel_name or self.channel_names.get(
            msg.channel_id, f"ch:{msg.channel_id}"
        )

        if msg.is_bot and not msg.content.startswith("**[↪"):
            return

        has_prompt = msg.channel_id in self.channel_prompts
        is_free = msg.channel_id in self.free_channels
        if not (has_prompt or is_free or msg.is_bot):
            return

        content = msg.content
        if msg.content.startswith("**[↪"):
            lines = msg.content.split("\n", 1)
            content = lines[1].strip() if len(lines) > 1 else ""
            logging.info(f"↪ [{channel_name}] Forward received: {content[:80]}")
            # Re-enter as a new agent turn for the target channel
            if forward_depth == 0:
                # Depth is encoded in prefix: (depth:N)
                m = re.search(r"\(depth:(\d+)\)", msg.content.split("\n", 1)[0])
                forward_depth = int(m.group(1)) if m else 1
        else:
            logging.info(f"→ [{channel_name}] {msg.author_name}: {content[:120]}")

        if not content:
            return

        ack_id = await self.adapter.send_message(msg.channel_id, "🔄 **Processing...**")
        if not ack_id:
            logging.error(f"Failed to send ack in {channel_name}")
            return

        system_prompt = self.channel_prompts.get(msg.channel_id, "")
        routing_guide = self._build_routing_guide(msg.channel_id)
        quoted_context = await self._fetch_reply_context(msg)
        full_prompt = (
            f"[SYSTEM PROMPT]\n{system_prompt}{routing_guide}{quoted_context}"
            f"\n\n[MESSAGE]\n{content}"
        )

        ticket_url, external_id, task_id = await self._resolve_ticket(
            content, msg.channel_id
        )
        if ticket_url or task_id:
            full_prompt += (
                f"\n\n[TICKET REFERENCE]\n"
                f"Task: {task_id or 'n/a'}\n"
                f"Ticket URL: {ticket_url or 'n/a'}\n"
                f"Include the TASK id in handoffs and status updates.\n"
            )

        response = await self._call_hermes(full_prompt, msg.channel_id)
        if not response:
            await self.adapter.edit_message(
                msg.channel_id, ack_id, "⚠️ Empty response. Try again?"
            )
            return

        forwards = self._parse_forwards(response, msg.channel_id)
        for target_id, fwd_msg in forwards:
            await self._forward(
                msg.channel_id, target_id, fwd_msg, msg.id, forward_depth
            )

        display = self._strip_forwards(response, msg.channel_id)
        if not display or len(display) <= 5:
            if forwards:
                display = "✅ Message forwarded to agents ✅"
            else:
                await self.adapter.edit_message(msg.channel_id, ack_id, "✅ Done")
                return

        # Resolve external_id from TASK mention in response if missing
        if self.task_mgr and not external_id:
            ref = self.task_mgr.guess_task_reference(display) or self.task_mgr.guess_task_reference(
                content
            )
            if ref and self.task_mgr.task_exists(ref):
                info = self.task_mgr.get_task(ref) or {}
                external_id = info.get("external_id")
                ticket_url = ticket_url or info.get("url", "")
                task_id = task_id or ref

        if self.sdlc and external_id:
            status = self.sdlc.detect_status(display)
            if status and self.sdlc.allowed_for_channel(channel_name, status):
                await self.sdlc.update_status(external_id, status)
            elif status:
                logging.info(
                    f"SDLC: ignored status '{status.display}' from {channel_name} "
                    f"(not in authority set)"
                )

        if task_id and task_id not in display:
            display = f"**{task_id}**\n{display}"
        if ticket_url:
            display += f"\n\n🔗 **Ticket:** {ticket_url}"
        if forwards:
            target_names = ", ".join(
                self.channel_names.get(str(t), "?") for t, _ in forwards
            )
            display += f"\n\n_↪ Forwarded to {target_names}_"

        await self.adapter.edit_message(msg.channel_id, ack_id, display[:1900])
        logging.info(f"✓ [{channel_name}] Response: {display[:80]}")

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
            f"- Always include TASK-NNN and an SDLC status keyword when changing stage.\n"
            f"- The bridge will forward your message automatically."
        )

    async def _fetch_reply_context(self, msg: Message) -> str:
        if not msg.reply_to_id:
            return ""
        return ""

    async def _resolve_ticket(
        self, content: str, channel_id: str
    ) -> tuple[str, Optional[str], str]:
        """
        Create or reference a ticket.
        Returns (ticket_url, external_id, task_id).
        """
        if self.task_mgr is None:
            return ("", None, "")

        channel_name = self.channel_names.get(channel_id, "")
        existing_task = self.task_mgr.guess_task_reference(content)

        if existing_task and self.task_mgr.task_exists(existing_task):
            info = self.task_mgr.get_task(existing_task) or {}
            return (
                info.get("url", ""),
                info.get("external_id"),
                existing_task,
            )

        can_create = channel_name in self.TICKET_CREATE_CHANNELS
        is_new_task = bool(
            re.search(
                r"(create|new|assign)\s+(a\s+)?(task|issue|ticket)",
                content,
                re.IGNORECASE,
            )
        )
        # PM/SA: create when explicit new-task language OR no existing TASK ref
        should_create = can_create and (
            is_new_task or (not existing_task and channel_name == "#pm")
        )
        if not should_create:
            return ("", None, existing_task or "")

        task_id = self.task_mgr.next_task_id()
        first_line = content.split("\n")[0][:80]
        issue_name = f"{task_id}: {first_line}"

        url = ""
        external_id = None
        key = ""

        if self.ticket_tracker is not None:
            ref = await self.ticket_tracker.create_issue(
                name=issue_name,
                description=content[:2000],
            )
            if ref:
                external_id = ref.external_id
                url = ref.url
                key = ref.key

        if not external_id:
            # Local-only id so mapping still works with NullTracker
            from uuid import uuid4

            external_id = str(uuid4())

        self.task_mgr.set_task(
            task_id,
            external_id=external_id,
            url=url,
            key=key,
            name=issue_name,
            provider=self.ticket_provider,
        )
        logging.info(f"🎫 Created {task_id} → {url or external_id}")
        return (url, external_id, task_id)

    async def _call_hermes(self, prompt: str, channel_id: str) -> Optional[str]:
        session_name = f"omc-{channel_id}"
        try:
            proc = await asyncio.create_subprocess_exec(
                "hermes",
                "-z",
                prompt,
                "--resume",
                session_name,
                "--safe-mode",
                "--yolo",
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
            elif any(
                s.startswith(c)
                for c in (
                    "╭", "╰", "│", "─", "⚠", "✦", "●", "┃", "┣", "┗",
                    "┏", "┓", "┛", "┳", "┻", "┫", "━",
                )
            ):
                continue
            elif re.match(r"^[\d:.,\s\-]+$", s):
                continue
            else:
                clean.append(s)
        result = "\n".join(clean).strip()
        if not result or len(result) < 5:
            meaningful = [
                l
                for l in lines
                if len(l.strip()) > 10 and not l.strip().startswith("Hermes")
            ]
            result = meaningful[-1].strip() if meaningful else response[:1900]
        return result

    def _parse_forwards(
        self, response: str, source_channel_id: str
    ) -> list[tuple[str, str]]:
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

    async def _forward(
        self,
        from_id: str,
        to_id: str,
        content: str,
        source_msg_id: str,
        depth: int,
    ):
        if depth >= self.forward_max_depth:
            logging.warning(f"Forward depth limit ({self.forward_max_depth})")
            return
        next_depth = depth + 1
        prefixed = (
            f"**[↪ {self.channel_names.get(from_id, '?')} → "
            f"{self.channel_names.get(to_id, '?')}]** (depth:{next_depth})\n{content}"
        )[:1900]
        msg_id = await self.adapter.send_message(to_id, prefixed)
        # Invoke target agent directly (do not rely on transport echoing bot messages).
        # If the adapter also delivers the same message id, dedup skips the duplicate.
        synthetic = Message(
            id=str(msg_id or f"fwd-{source_msg_id}-{to_id}-{next_depth}"),
            channel_id=to_id,
            author_id="bridge",
            author_name="omc-bridge",
            content=prefixed,
            is_bot=True,
            channel_name=self.channel_names.get(to_id),
        )
        await self.handle_message(synthetic, forward_depth=next_depth)
