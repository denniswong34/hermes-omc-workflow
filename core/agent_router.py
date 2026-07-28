"""
Agent Router — Topic rooms + in-channel @Agent handoffs
=======================================================
Messages live in SaaS topic channels (product, engineering, …).
Agents are invoked only when @mentioned. Handoffs stay in the same channel.
"""

from __future__ import annotations

import asyncio
import logging
import re
from typing import Optional
from uuid import uuid4

from adapters.base import ChannelAdapter, Message
from core.chat_messages import (
    DEFAULT_MESSAGE_FORMAT,
    format_error,
    format_handoff,
    format_processing,
    format_reply,
    is_bot_own_message,
    normalize_message_format,
    strip_display_prefix,
)
from core.coding import CodingRegistry
from core.memory.obsidian import ObsidianMemoryStore
from core.sdlc_tracker import SDLCTracker
from core.task_manager import TaskManager
from core.tickets.base import TicketTracker
from core.tickets.draft import draft_ticket, format_agent_comment
from core.tickets.status import SdlcStatus, detect_status

logger = logging.getLogger(__name__)

# Soft / premature handoffs that must not start a real agent turn.
# Example bug: PM emits @SA + @Coder:"wait for SA"; nested SA→Coder finishes,
# then the standby @Coder turn runs and posts "still waiting for the spec".
_STANDBY_HANDOFF_RE = re.compile(
    r"(?i)\b("
    r"wait(?:ing)?\s+(?:on|for)|"
    r"stand\s*by|"
    r"holding(?:\s+pattern)?|"
    r"do not start|"
    r"don'?t start|"
    r"before starting|"
    r"nothing in progress|"
    r"park(?:ed)?|"
    r"hold off|"
    r"once\s+@?[A-Za-z][A-Za-z0-9_-]*\s+(?:finishes|is done|lands)|"
    r"after\s+@?[A-Za-z][A-Za-z0-9_-]*\s+(?:finishes|is done)"
    r")\b"
)

# Roles allowed to fan out multiple actionable handoffs in one reply
# (e.g. SA → Coder + QA). Everyone else is linear: first actionable only.
_MULTI_HANDOFF_ROLES = frozenset({"sa", "qa"})


def is_standby_handoff(text: str) -> bool:
    """True when the handoff is a wait/standby note, not actionable work."""
    return bool(_STANDBY_HANDOFF_RE.search(text or ""))


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
        memory: Optional[ObsidianMemoryStore] = None,
        forward_max_depth: int = 5,
        message_format: str = DEFAULT_MESSAGE_FORMAT,
        message_format_by_channel: Optional[dict[str, str]] = None,
        *,
        workflow_id: str = "",
        agent_meta: Optional[dict[str, dict]] = None,
        adapters_by_role: Optional[dict[str, ChannelAdapter]] = None,
        runtime=None,
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
        self.memory = memory
        self.forward_max_depth = forward_max_depth
        self.message_format = normalize_message_format(message_format)
        self.message_format_by_channel = {
            str(k): normalize_message_format(v)
            for k, v in (message_format_by_channel or {}).items()
        }
        self.workflow_id = workflow_id
        # role_id → {id, hermes_profile, llm_model, ...}
        self.agent_meta = {
            str(k).lower(): v for k, v in (agent_meta or {}).items()
        }
        self.adapters_by_role = {
            str(k).lower(): v for k, v in (adapters_by_role or {}).items()
        }
        self.runtime = runtime

        self._processed_ids: set[str] = set()
        self._processed_max = 300
        self._msg_lock = asyncio.Lock()
        # Per (channel, role): serialize turns + drop superseded work.
        self._role_gates: dict[str, asyncio.Lock] = {}
        self._role_epoch: dict[str, int] = {}

    def _format_for_channel(self, channel_id: str) -> str:
        return self.message_format_by_channel.get(
            channel_id, self.message_format
        )

    def _adapter_for(self, role: str) -> ChannelAdapter:
        return self.adapters_by_role.get((role or "").lower()) or self.adapter

    async def _adapter_for_send(
        self, role: str, channel_id: str, content: str
    ) -> tuple[ChannelAdapter, Optional[str]]:
        """
        Send with the role bot; if that fails (e.g. bot not in guild/channel),
        fall back to the default adapter so the turn can still complete.
        Returns (adapter_used, message_id).
        """
        primary = self._adapter_for(role)
        msg_id = await primary.send_message(channel_id, content)
        if msg_id:
            return primary, msg_id
        fallback = self.adapter
        if fallback is primary:
            return primary, None
        logger.warning(
            "Send via @%s adapter failed — falling back to default adapter",
            role,
        )
        msg_id = await fallback.send_message(channel_id, content)
        return fallback, msg_id

    def _agent_record(self, role: str) -> dict:
        return self.agent_meta.get((role or "").lower()) or {}

    @staticmethod
    def _role_gate_key(channel_id: str, role: str) -> str:
        return f"{channel_id}:{(role or '').lower()}"

    def _bump_role_epoch(self, channel_id: str, role: str) -> tuple[str, int]:
        key = self._role_gate_key(channel_id, role)
        self._role_epoch[key] = self._role_epoch.get(key, 0) + 1
        return key, self._role_epoch[key]

    def _role_gate(self, key: str) -> asyncio.Lock:
        gate = self._role_gates.get(key)
        if gate is None:
            gate = asyncio.Lock()
            self._role_gates[key] = gate
        return gate

    def _select_handoffs(
        self, speaker: str, handoffs: list[tuple[str, str]]
    ) -> list[tuple[str, str]]:
        """
        Drop standby/wait handoffs. Linear roles keep only the first
        actionable target so nested downstream work is not overwritten by a
        later soft ping from the same reply (PM @SA then @Coder wait).
        """
        actionable = [
            (role, msg)
            for role, msg in handoffs
            if not is_standby_handoff(msg)
        ]
        skipped = len(handoffs) - len(actionable)
        if skipped:
            logger.info(
                "Skipped %s standby handoff(s) from @%s",
                skipped,
                speaker,
            )
        if not actionable:
            return []
        if (speaker or "").lower() in _MULTI_HANDOFF_ROLES:
            return actionable
        if len(actionable) > 1:
            logger.info(
                "Linear handoff from @%s: keeping @%s, deferring %s",
                speaker,
                actionable[0][0],
                [r for r, _ in actionable[1:]],
            )
        return actionable[:1]

    # ── Entry ────────────────────────────────────────────────────────

    async def handle_message(self, msg: Message, forward_depth: int = 0):
        async with self._msg_lock:
            if msg.id in self._processed_ids:
                return
            self._processed_ids.add(msg.id)
            if len(self._processed_ids) > self._processed_max:
                self._processed_ids.clear()

        topic_key = self.topic_by_channel_id.get(msg.channel_id)
        target_role = (getattr(msg, "target_role", None) or "").lower()
        is_dm = bool(getattr(msg, "is_dm", False))
        bot_mentioned = bool(getattr(msg, "bot_mentioned", False))

        # DM / bot-owned synthetic topic when channel is not a mapped topic
        if not topic_key:
            if is_dm and target_role:
                topic_key = f"dm:{msg.channel_id}"
                topic = {
                    "channel_id": msg.channel_id,
                    "agents": [target_role],
                    "ticket_create_roles": [],
                }
            else:
                return
        else:
            topic = self.topics[topic_key]

        topic_label = f"#{topic_key}"

        # Our own posts are already handled (direct handoff enqueue + edited replies)
        raw = msg.content or ""
        if msg.is_bot and is_bot_own_message(raw):
            return

        content = self._strip_display_prefix(raw)

        mentions = self._parse_mentions(content, topic["agents"])
        # Bot mention / DM without text @role → route to that agent's role
        if not mentions and target_role and (
            is_dm or bot_mentioned
        ):
            if target_role in topic["agents"] or is_dm:
                mentions = [(target_role, content)]
                if target_role not in topic["agents"]:
                    topic = {**topic, "agents": list(topic["agents"]) + [target_role]}
        if not mentions:
            return  # Explicit @mention required

        speaker_role = self._speaker_role_from_message(msg)
        primary_role, _ = mentions[0]

        if primary_role not in topic["agents"] and not is_dm:
            return

        # Agent speakers may only ping roles in their agent_routes
        if speaker_role not in ("human", "bot", ""):
            allowed = set(self.agent_routes.get(speaker_role, []))
            if primary_role not in allowed:
                logger.info(
                    f"Blocked @{primary_role}: @{speaker_role} cannot route there"
                )
                return

        # Soft @mentions like "wait for SA" must not start a Hermes turn.
        if is_standby_handoff(content):
            logger.info(
                "Ignoring standby mention @%s ← %s: %s",
                primary_role,
                msg.author_name,
                content[:120],
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
        gate_key, my_epoch = self._bump_role_epoch(channel_id, role)
        gate = self._role_gate(gate_key)

        async with gate:
            # A newer @mention for this role arrived while we waited — drop us.
            if self._role_epoch.get(gate_key) != my_epoch:
                logger.info(
                    "Skipping superseded @%s turn in #%s (epoch %s < %s)",
                    role,
                    topic_key,
                    my_epoch,
                    self._role_epoch.get(gate_key),
                )
                return
            await self._run_agent_turn_locked(
                msg=msg,
                topic=topic,
                topic_key=topic_key,
                role=role,
                content=content,
                depth=depth,
                gate_key=gate_key,
                my_epoch=my_epoch,
            )

    async def _run_agent_turn_locked(
        self,
        *,
        msg: Message,
        topic: dict,
        topic_key: str,
        role: str,
        content: str,
        depth: int,
        gate_key: str,
        my_epoch: int,
    ):
        channel_id = msg.channel_id
        fmt = self._format_for_channel(channel_id)
        adapter, ack_id = await self._adapter_for_send(
            role, channel_id, format_processing(role, fmt)
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
            content,
            role,
            topic,
            topic_key=topic_key,
            author=msg.author_name or "",
        )
        if ticket_url or task_id:
            full_prompt += (
                f"\n\n[TICKET REFERENCE]\n"
                f"Task: {task_id or 'n/a'}\n"
                f"Ticket URL: {ticket_url or 'n/a'}\n"
                f"Include the TASK id in handoffs and status updates.\n"
            )

        # Shared Obsidian memory (cross-backend)
        if self.memory and task_id:
            try:
                if not self.memory.get_task(task_id):
                    draft = draft_ticket(
                        content,
                        topic=topic_key,
                        role=role,
                        author=msg.author_name or "",
                    )
                    self.memory.upsert_task(
                        task_id,
                        title=draft.title,
                        topic=topic_key,
                        assignee=role,
                        ticket_url=ticket_url or "",
                        goal=draft.description[:800],
                    )
                mem = self.memory.build_context_prompt(task_id)
                if mem:
                    full_prompt += f"\n\n[MEMORY]\n{mem}\n"
            except Exception as e:
                logger.warning(f"Memory inject failed: {e}")

        try:
            response = await self._invoke_role(
                role=role,
                prompt=full_prompt,
                topic_key=topic_key,
            )
        except Exception as e:
            logger.error(f"[{topic_key}/@{role}] invoke error: {e}")
            await adapter.edit_message(
                channel_id, ack_id, format_error(role, str(e), fmt)
            )
            return

        if not response:
            await adapter.edit_message(
                channel_id,
                ack_id,
                format_error(role, "Empty response.", fmt),
            )
            return

        # Newer @mention for this role is waiting on the gate — drop our reply.
        if self._role_epoch.get(gate_key) != my_epoch:
            logger.info(
                "Dropping superseded @%s reply in #%s (epoch %s < %s)",
                role,
                topic_key,
                my_epoch,
                self._role_epoch.get(gate_key),
            )
            await adapter.edit_message(
                channel_id,
                ack_id,
                format_reply(
                    role,
                    "⏭ Superseded by a newer @mention — see the latest handoff.",
                    fmt=fmt,
                    topic=topic_key,
                ),
            )
            return

        parsed_handoffs = self._parse_handoffs(response, role, topic["agents"])
        handoffs = self._select_handoffs(role, parsed_handoffs)
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

        status = None
        if self.sdlc and external_id:
            status = self.sdlc.detect_status(display)
            if status and self.sdlc.allowed_for_role(role, status):
                synced = await self.sdlc.update_status(external_id, status)
                if not synced:
                    logger.warning(
                        f"SDLC: status sync failed for {external_id} → {status.display}"
                    )
            elif status:
                logger.info(
                    f"SDLC: ignored '{status.display}' from @{role} (not in authority)"
                )
                status = None

        # Mirror each agent turn onto the external ticket as a comment
        if self.ticket_tracker and external_id:
            try:
                comment = format_agent_comment(
                    role=role,
                    topic=topic_key,
                    body=display,
                    status=status.display if status else None,
                    task_id=task_id or "",
                )
                ok = await self.ticket_tracker.add_comment(external_id, comment)
                if not ok:
                    logger.warning(f"Ticket comment failed for {external_id}")
            except Exception as e:
                logger.warning(f"Ticket comment error: {e}")

        # Persist shared memory after the turn
        if self.memory and task_id:
            try:
                backend_key = (
                    self.coding.resolve_backend_key(role)
                    if self.coding.is_coding_mention(role)
                    else ""
                )
                st = status.display if status else ""
                if not st:
                    detected = detect_status(display)
                    st = detected.display if detected else ""
                self.memory.upsert_task(
                    task_id,
                    status=st,
                    topic=topic_key,
                    assignee=role,
                    backend=backend_key,
                    ticket_url=ticket_url or "",
                )
                self.memory.append_agent_note(
                    task_id, role, backend_key, display[:1200]
                )
                for target_role, handoff_msg in handoffs:
                    self.memory.append_handoff(
                        task_id, role, target_role, handoff_msg
                    )
            except Exception as e:
                logger.warning(f"Memory persist failed: {e}")

        display = format_reply(
            role,
            display,
            fmt=fmt,
            topic=topic_key,
            task_id=task_id or "",
            ticket_url=ticket_url or "",
            status=status.display if status else "",
            handoffs=[r for r, _ in handoffs],
        )
        await adapter.edit_message(channel_id, ack_id, display)
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
        if is_standby_handoff(handoff_msg):
            logger.info(
                "Skipping standby handoff @%s → @%s: %s",
                from_role,
                to_role,
                (handoff_msg or "")[:120],
            )
            return

        # Ensure the mention is present for natural chat + parser
        body = handoff_msg.strip()
        if not re.match(rf"^@{to_role}\b", body, re.IGNORECASE):
            body = f"@{to_role}: {body}"

        fmt = self._format_for_channel(channel_id)
        posted = format_handoff(
            from_role, to_role, body, depth=depth, fmt=fmt
        )
        # Handoff posts as the *target* agent's bot when configured
        _ad, msg_id = await self._adapter_for_send(to_role, channel_id, posted)

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
        meta = self._agent_record(role)
        profile = (meta.get("hermes_profile") or "").strip()
        model = (meta.get("llm_model") or "").strip()
        session = profile or f"omc-{self.workflow_id or topic_key}-{role}"
        if topic_key and not profile:
            session = f"omc-{topic_key}-{role}"

        if self.coding.is_coding_mention(role):
            backend = self.coding.get_backend(role)
            return await backend.run(
                prompt,
                workspace=self.coding.workspace,
                session_key=session,
                profile=profile,
                model=model,
            )

        # Prefer per-agent reasoning engine when runtime is available
        if self.runtime is not None:
            try:
                engine = self.runtime.engine_for_agent(role)
                return await engine.run(
                    prompt,
                    workspace="",
                    session_key=session,
                    profile=profile,
                    model=model,
                )
            except Exception as e:
                logger.warning("engine_for_agent failed for %s: %s — falling back", role, e)

        hermes = self.coding.get_hermes()
        return await hermes.run(
            prompt,
            workspace="",
            session_key=session,
            profile=profile,
            model=model,
        )

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
            f"- Hand off only when the target has actionable work NOW.\n"
            f"- Never @mention a downstream agent with wait/standby instructions "
            f"(e.g. '@coder: wait for SA') — that causes stale concurrent turns.\n"
        )

    # ── Tickets ──────────────────────────────────────────────────────

    async def _resolve_ticket(
        self,
        content: str,
        role: str,
        topic: dict,
        *,
        topic_key: str = "",
        author: str = "",
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
        draft = draft_ticket(
            content,
            topic=topic_key or str(topic.get("name") or ""),
            role=role,
            author=author,
        )
        issue_name = draft.title
        local_name = f"{task_id}: {draft.title}"

        url = ""
        external_id = None
        key = ""
        if self.ticket_tracker is not None:
            ref = await self.ticket_tracker.create_issue(
                name=issue_name,
                description=draft.description,
                status=SdlcStatus.TODO,
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
            name=local_name,
            provider=self.ticket_provider,
        )
        logging.info(f"🎫 Created {task_id} → {url or external_id} ({draft.kind})")
        return (url, external_id, task_id)

    # ── Helpers ──────────────────────────────────────────────────────

    @staticmethod
    def _strip_display_prefix(content: str) -> str:
        return strip_display_prefix(content)

    @staticmethod
    def _is_agent_handoff_post(content: str) -> bool:
        head = "\n".join((content or "").split("\n", 4)[:4])
        first = head.split("\n", 1)[0].strip() if head else ""
        if re.match(r"\*\*\[@[A-Za-z].*→.*\]\*\*", first) or re.match(
            r"\*\*\[↪", first
        ):
            return True
        if "→" not in head and "HANDOFF" not in head and "handoff" not in head.lower():
            return False
        return (
            first.startswith("╔")
            or first.startswith("━━")
            or first.startswith("🔁")
            or first.startswith("===")
            or "HANDOFF" in head
            or "handoff" in head.lower()
        )

    @staticmethod
    def _speaker_role_from_message(msg: Message) -> str:
        if msg.author_id.startswith("agent:"):
            return msg.author_id.split(":", 1)[1].lower()
        if msg.author_name.startswith("@") and msg.is_bot:
            return msg.author_name.lstrip("@").lower()
        # Parse **[@PM → @SA]** or new handoff headers containing FROM → TO
        first = (msg.content or "").split("\n", 1)[0]
        m = re.match(r"\*\*\[@([A-Za-z][A-Za-z0-9_-]*)\s*→", first)
        if m:
            return m.group(1).lower()
        m2 = re.search(
            r"(?:AGENT|HANDOFF|🔁\s*\*\*)\s*([A-Za-z][A-Za-z0-9_-]*)\s*→",
            first,
            re.IGNORECASE,
        )
        if m2:
            return m2.group(1).lower()
        m3 = re.search(
            r"║\s*([A-Za-z][A-Za-z0-9_-]*)\s*→",
            first,
        )
        if m3:
            return m3.group(1).lower()
        if msg.is_bot:
            return "bot"
        return "human"
