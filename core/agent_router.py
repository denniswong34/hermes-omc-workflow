"""
Agent Router — Topic rooms + in-channel @Agent handoffs
=======================================================
Messages live in SaaS topic channels (product, engineering, …).
Agents are invoked only when @mentioned. Handoffs stay in the same channel.
"""

from __future__ import annotations

import logging
import re
from typing import Optional
from uuid import uuid4

from adapters.base import ChannelAdapter, Message
from core.coding import CodingRegistry
from core.sdlc_tracker import SDLCTracker
from core.task_manager import TaskManager
from core.tickets.base import TicketTracker

logger = logging.getLogger(__name__)

# Match @pm, @PM, @sa:, @Coder Please...
MENTION_RE = re.compile(
    r"@([A-Za-z][A-Za-z0-9_-]*)\b:?\s*",
    re.IGNORECASE,
)


class AgentRouter:
    """Orchestrates in-channel multi-agent conversation and tickets."""

    def __init__(
        self,
        adapter: ChannelAdapter,
        topics: dict[str, dict],
        topic_by_channel_id: dict[str, str],
        agent_prompts: dict[str, str],
        agent_routes: dict[str, list[str]],
        channel_names: dict[str, str],
        coding: CodingRegistry,
        sdlc: Optional[SDLCTracker] = None,
        task_mgr: Optional[TaskManager] = None,
        ticket_tracker: Optional[TicketTracker] = None,
        ticket_provider: str = "none",
        forward_max_depth: int = 5,
    ):
        self.adapter = adapter
        self.topics = topics
        self.topic_by_channel_id = topic_by_channel_id
        self.agent_prompts = agent_prompts
        self.agent_routes = agent_routes
        self.channel_names = channel_names
        self.coding = coding
        self.sdlc = sdlc
        self.task_mgr = task_mgr
        self.ticket_tracker = ticket_tracker
        self.ticket_provider = ticket_provider
        self.forward_max_depth = forward_max_depth

        self._processed_ids: set[str] = set()
        self._processed_max = 300

    # ── Entry ────────────────────────────────────────────────────────

    async def handle_message(self, msg: Message, forward_depth: int = 0):
        if msg.id in self._processed_ids:
            return
        self._processed_ids.add(msg.id)
        if len(self._processed_ids) > self._processed_max:
            self._processed_ids.clear()

        topic_key = self.topic_by_channel_id.get(msg.channel_id)
        if not topic_key:
            return  # Not a configured topic channel

        topic = self.topics[topic_key]
        topic_label = f"#{topic_key}"

        # Our own posts are already handled (direct handoff enqueue + edited replies)
        raw = msg.content or ""
        if msg.is_bot and raw.lstrip().startswith("**[@"):
            return

        content = self._strip_display_prefix(raw)

        mentions = self._parse_mentions(content, topic["agents"])
        if not mentions:
            return  # Explicit @mention required

        speaker_role = self._speaker_role_from_message(msg)
        primary_role, _ = mentions[0]

        if primary_role not in topic["agents"]:
            return

        # Agent speakers may only ping roles in their agent_routes
        if speaker_role not in ("human", "bot", ""):
            allowed = set(self.agent_routes.get(speaker_role, []))
            if primary_role not in allowed:
                logger.info(
                    f"Blocked @{primary_role}: @{speaker_role} cannot route there"
                )
                return

        logging.info(
            f"→ [{topic_label}] @{primary_role} ← {msg.author_name}: {content[:120]}"
        )

        await self._run_agent_turn(
            msg=msg,
            topic=topic,
            topic_key=topic_key,
            role=primary_role,
            content=content,
            depth=forward_depth,
        )

    async def _run_agent_turn(
        self,
        *,
        msg: Message,
        topic: dict,
        topic_key: str,
        role: str,
        content: str,
        depth: int,
    ):
        channel_id = msg.channel_id
        ack_id = await self.adapter.send_message(
            channel_id, f"🔄 **[@{role.upper()}]** Processing..."
        )
        if not ack_id:
            logger.error(f"Failed to send ack in #{topic_key}")
            return

        system_prompt = self.agent_prompts.get(role, "")
        routing_guide = self._build_routing_guide(role, topic)
        full_prompt = (
            f"[SYSTEM PROMPT]\n{system_prompt}{routing_guide}\n\n"
            f"[TOPIC]\n#{topic_key}\n\n"
            f"[MESSAGE]\n{content}"
        )

        ticket_url, external_id, task_id = await self._resolve_ticket(
            content, role, topic
        )
        if ticket_url or task_id:
            full_prompt += (
                f"\n\n[TICKET REFERENCE]\n"
                f"Task: {task_id or 'n/a'}\n"
                f"Ticket URL: {ticket_url or 'n/a'}\n"
                f"Include the TASK id in handoffs and status updates.\n"
            )

        try:
            response = await self._invoke_role(
                role=role,
                prompt=full_prompt,
                topic_key=topic_key,
            )
        except Exception as e:
            logger.error(f"[{topic_key}/@{role}] invoke error: {e}")
            await self.adapter.edit_message(
                channel_id, ack_id, f"⚠️ **[@{role.upper()}]** {e}"
            )
            return

        if not response:
            await self.adapter.edit_message(
                channel_id, ack_id, f"⚠️ **[@{role.upper()}]** Empty response."
            )
            return

        handoffs = self._parse_handoffs(response, role, topic["agents"])
        display = self._strip_handoff_lines(response, role, topic["agents"])
        if not display or len(display) <= 5:
            display = "✅ Handed off to next agent." if handoffs else "✅ Done"

        if self.task_mgr and not external_id:
            ref = self.task_mgr.guess_task_reference(
                display
            ) or self.task_mgr.guess_task_reference(content)
            if ref and self.task_mgr.task_exists(ref):
                info = self.task_mgr.get_task(ref) or {}
                external_id = info.get("external_id")
                ticket_url = ticket_url or info.get("url", "")
                task_id = task_id or ref

        if self.sdlc and external_id:
            status = self.sdlc.detect_status(display)
            if status and self.sdlc.allowed_for_role(role, status):
                await self.sdlc.update_status(external_id, status)
            elif status:
                logger.info(
                    f"SDLC: ignored '{status.display}' from @{role} (not in authority)"
                )

        if task_id and task_id not in display:
            display = f"**{task_id}**\n{display}"
        if ticket_url:
            display += f"\n\n🔗 **Ticket:** {ticket_url}"
        if handoffs:
            names = ", ".join(f"@{r}" for r, _ in handoffs)
            display += f"\n\n_↪ Mentioning {names}_"

        display = f"**[@{role.upper()}]**\n{display}"[:1900]
        await self.adapter.edit_message(channel_id, ack_id, display)
        logging.info(f"✓ [#{topic_key}/@{role}] {display[:80]}")

        # Same-channel follow-up turns
        if depth >= self.forward_max_depth:
            logger.warning(f"Handoff depth limit ({self.forward_max_depth})")
            return

        for target_role, handoff_msg in handoffs:
            await self._enqueue_handoff(
                channel_id=channel_id,
                topic=topic,
                topic_key=topic_key,
                from_role=role,
                to_role=target_role,
                handoff_msg=handoff_msg,
                source_msg_id=msg.id,
                depth=depth + 1,
            )

    async def _enqueue_handoff(
        self,
        *,
        channel_id: str,
        topic: dict,
        topic_key: str,
        from_role: str,
        to_role: str,
        handoff_msg: str,
        source_msg_id: str,
        depth: int,
    ):
        """Post @to_role in-channel and run that agent turn."""
        # Ensure the mention is present for natural chat + parser
        body = handoff_msg.strip()
        if not re.match(rf"^@{to_role}\b", body, re.IGNORECASE):
            body = f"@{to_role}: {body}"

        posted = (
            f"**[@{from_role.upper()} → @{to_role.upper()}]** (depth:{depth})\n{body}"
        )[:1900]
        msg_id = await self.adapter.send_message(channel_id, posted)

        synthetic = Message(
            id=str(msg_id or f"handoff-{source_msg_id}-{to_role}-{depth}"),
            channel_id=channel_id,
            author_id=f"agent:{from_role}",
            author_name=f"@{from_role}",
            content=posted,
            is_bot=True,
            channel_name=f"#{topic_key}",
        )
        # Process as a new mention turn for to_role
        if synthetic.id in self._processed_ids:
            # Allow re-entry: remove so handle can run — actually we want
            # direct turn to avoid re-parse ambiguity
            pass
        await self._run_agent_turn(
            msg=synthetic,
            topic=topic,
            topic_key=topic_key,
            role=to_role,
            content=self._strip_display_prefix(body),
            depth=depth,
        )

    # ── Invoke ───────────────────────────────────────────────────────

    async def _invoke_role(self, *, role: str, prompt: str, topic_key: str) -> str:
        session = f"omc-{topic_key}-{role}"
        if self.coding.is_coding_mention(role):
            backend = self.coding.get_backend(role)
            return await backend.run(
                prompt,
                workspace=self.coding.workspace,
                session_key=session,
            )
        # Persona chat via Hermes
        hermes = self.coding.get_hermes()
        return await hermes.run(prompt, workspace="", session_key=session)

    # ── Mentions / handoffs ──────────────────────────────────────────

    def _parse_mentions(
        self, content: str, topic_agents: list[str]
    ) -> list[tuple[str, str]]:
        """Return [(role, remainder_hint), ...] for agents allowed in topic."""
        allowed = {a.lower() for a in topic_agents}
        found: list[tuple[str, str]] = []
        seen: set[str] = set()
        for m in MENTION_RE.finditer(content):
            role = m.group(1).lower()
            if role not in allowed or role in seen:
                continue
            seen.add(role)
            found.append((role, content[m.end() :].strip()))
        return found

    def _parse_handoffs(
        self, response: str, speaker: str, topic_agents: list[str]
    ) -> list[tuple[str, str]]:
        """Lines that start with @role: for allowed route targets in this topic."""
        allowed_routes = set(self.agent_routes.get(speaker, []))
        topic_set = {a.lower() for a in topic_agents}
        results: list[tuple[str, str]] = []
        for line in response.split("\n"):
            line = line.strip()
            m = re.match(r"^@([A-Za-z][A-Za-z0-9_-]*)\b:?\s*(.*)", line, re.IGNORECASE)
            if not m or not m.group(2).strip():
                continue
            role = m.group(1).lower()
            if role == speaker:
                continue
            if role not in topic_set or role not in allowed_routes:
                continue
            results.append((role, m.group(2).strip()))
        return results

    def _strip_handoff_lines(
        self, response: str, speaker: str, topic_agents: list[str]
    ) -> str:
        allowed_routes = set(self.agent_routes.get(speaker, []))
        topic_set = {a.lower() for a in topic_agents}
        lines = []
        for line in response.split("\n"):
            m = re.match(r"^@([A-Za-z][A-Za-z0-9_-]*)\b:?\s*", line.strip(), re.IGNORECASE)
            if m:
                role = m.group(1).lower()
                if role in topic_set and role in allowed_routes and role != speaker:
                    continue
            lines.append(line)
        return "\n".join(lines).strip()

    def _build_routing_guide(self, role: str, topic: dict) -> str:
        routes = self.agent_routes.get(role, [])
        topic_agents = set(topic.get("agents") or [])
        can_ping = [r for r in routes if r in topic_agents]
        if not can_ping:
            return (
                "\n\nIN-CHANNEL RULES:\n"
                "- Stay in this topic channel.\n"
                "- Do not @mention other agents (none available here).\n"
            )
        targets = ", ".join(f"@{r}" for r in can_ping)
        return (
            f"\n\nIN-CHANNEL RULES:\n"
            f"- You are chatting in a shared topic channel. Do NOT ask for other channels.\n"
            f"- To hand off, START a line with @role: message (same channel).\n"
            f"- You can mention: {targets}\n"
            f"- Example: @sa: Please produce a spec for TASK-001\n"
            f"- Always include TASK-NNN and an SDLC status keyword when changing stage.\n"
        )

    # ── Tickets ──────────────────────────────────────────────────────

    async def _resolve_ticket(
        self, content: str, role: str, topic: dict
    ) -> tuple[str, Optional[str], str]:
        if self.task_mgr is None:
            return ("", None, "")

        existing_task = self.task_mgr.guess_task_reference(content)
        if existing_task and self.task_mgr.task_exists(existing_task):
            info = self.task_mgr.get_task(existing_task) or {}
            return (info.get("url", ""), info.get("external_id"), existing_task)

        create_roles = {
            r.lower() for r in (topic.get("ticket_create_roles") or [])
        }
        can_create = role.lower() in create_roles
        is_new_task = bool(
            re.search(
                r"(create|new|assign)\s+(a\s+)?(task|issue|ticket)",
                content,
                re.IGNORECASE,
            )
        )
        # PM (when allowed) creates on new work without existing TASK
        should_create = can_create and (
            is_new_task or (not existing_task and role.lower() == "pm")
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

    # ── Helpers ──────────────────────────────────────────────────────

    @staticmethod
    def _strip_display_prefix(content: str) -> str:
        # **[@PM]** or **[@PM → @SA]** (depth:N)
        lines = content.split("\n", 1)
        first = lines[0].strip()
        if first.startswith("**[@") and first.endswith("**"):
            return lines[1].strip() if len(lines) > 1 else ""
        if first.startswith("**[↪"):
            return lines[1].strip() if len(lines) > 1 else ""
        return content

    @staticmethod
    def _is_agent_handoff_post(content: str) -> bool:
        first = (content or "").split("\n", 1)[0].strip()
        return bool(
            re.match(r"\*\*\[@[A-Za-z].*→.*\]\*\*", first)
            or re.match(r"\*\*\[↪", first)
        )

    @staticmethod
    def _speaker_role_from_message(msg: Message) -> str:
        if msg.author_id.startswith("agent:"):
            return msg.author_id.split(":", 1)[1].lower()
        if msg.author_name.startswith("@") and msg.is_bot:
            return msg.author_name.lstrip("@").lower()
        # Parse **[@PM → @SA]**
        first = (msg.content or "").split("\n", 1)[0]
        m = re.match(r"\*\*\[@([A-Za-z][A-Za-z0-9_-]*)\s*→", first)
        if m:
            return m.group(1).lower()
        if msg.is_bot:
            return "bot"
        return "human"
