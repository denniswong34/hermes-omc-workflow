"""Per-platform chatbot gateway setup guides (docs + in-app help)."""

from __future__ import annotations

from typing import Any

GATEWAY_GUIDES: dict[str, dict[str, Any]] = {
    "discord": {
        "title": "Discord bot gateway",
        "summary": "Create one Discord application/bot per agent, enable Message Content Intent, invite to your guild.",
        "steps": [
            "Open the Discord Developer Portal → New Application (one app per agent, e.g. OMC PM).",
            "Bot → Add Bot → Reset/Copy Bot Token → paste into Agent → Gateways → Discord.",
            "Privileged Gateway Intents: enable Message Content Intent (Server Members optional; Presence off).",
            "OAuth2 → URL Generator: scopes bot (+ applications.commands optional).",
            "Bot permissions: View Channels, Send Messages, Read Message History, Embed Links, Attach Files, Add Reactions.",
            "Invite the bot to the guild that hosts OMC topic channels.",
            "In OMC: map topic channel external IDs, enable Discord on the agent, Test connection.",
            "For DMs: users open a DM with the bot; OMC uses the DM intent on this bot.",
        ],
        "links": [
            {
                "label": "Discord Developer Portal",
                "url": "https://discord.com/developers/applications",
            }
        ],
        "tips": [
            "Prefer one bot app per agent so display names match roles.",
            "Never commit tokens; rotate after exposure and re-test.",
        ],
    },
    "telegram": {
        "title": "Telegram bot gateway",
        "summary": "Create a bot with BotFather and paste the HTTP API token into the agent gateway.",
        "steps": [
            "In Telegram open @BotFather → /newbot → choose display name + username (e.g. omc_pm_bot).",
            "Copy the HTTP API token → Agent → Gateways → Telegram → Bot token.",
            "Optional: /setjoingrouproups; /setprivacy — Disable Privacy Mode only if the bot must read all group messages without mentions.",
            "Add the bot to the OMC topic group; send a message; capture chat.id as channel external_id.",
            "For DMs: user starts the bot with /start.",
            "In OMC: enable Telegram on the agent and Test connection (getMe).",
        ],
        "links": [
            {"label": "BotFather", "url": "https://t.me/BotFather"},
        ],
        "tips": [
            "Do not share one Telegram token across two agents.",
            "After rotating a token, restart/reload the bridge.",
        ],
    },
    "slack": {
        "title": "Slack bot gateway",
        "summary": "Create a Slack app with Socket Mode; store both xoxb bot token and xapp app token per agent.",
        "steps": [
            "api.slack.com/apps → Create New App → From scratch (one app per agent recommended).",
            "Socket Mode: Enable → generate App-Level Token (xapp-…) with connections:write → Agent Gateway App token.",
            "OAuth & Permissions → Bot Token Scopes: chat:write, channels:history, groups:history, im:history, mpim:history, app_mentions:read, im:write, users:read.",
            "Install to workspace → copy Bot User OAuth Token (xoxb-…) → Agent Gateway Bot token.",
            "Event Subscriptions (Socket Mode): message.channels, message.groups, message.im, app_mention.",
            "Invite the bot to topic channels (/invite @BotName).",
            "In OMC: enable Slack on the agent and Test connection (auth.test).",
        ],
        "links": [
            {"label": "Slack API Apps", "url": "https://api.slack.com/apps"},
        ],
        "tips": [
            "Both SLACK_BOT_TOKEN and SLACK_APP_TOKEN are required for Socket Mode.",
        ],
    },
    "zulip": {
        "title": "Zulip bot gateway",
        "summary": "Create a Zulip bot and store site URL, bot email, and API key on the agent.",
        "steps": [
            "Zulip org → Personal settings → Bots (or org bots) → Add a new bot (generic bot recommended).",
            "Note bot email, API key, and site URL (e.g. https://chat.example.com).",
            "Paste into Agent → Gateways → Zulip: Site URL, Bot email, API key.",
            "Subscribe the bot to streams used as OMC topics.",
            "DMs: private messages to the bot email route to that agent.",
            "In OMC: enable Zulip on the agent and Test connection (get_profile).",
        ],
        "links": [],
        "tips": [
            "Align Zulip stream/topic external ids with the existing Zulip adapter conventions.",
        ],
    },
}


def gateway_guides_payload() -> dict[str, Any]:
    return {
        "platforms": list(GATEWAY_GUIDES.keys()),
        "guides": GATEWAY_GUIDES,
        "checklist": [
            "Prefer one bot app per agent so display names match roles (PM, SA, Coder…).",
            "Never commit tokens; store only via Agentic OS gateway fields (write-only).",
            "After rotating a token, re-run Test connection and restart/reload the bridge.",
            "Avoid two agents sharing one token (identity collision on outbound send_as).",
        ],
    }


def render_gateway_setup_markdown() -> str:
    """Generate docs/GATEWAY_SETUP.md content from the shared guides."""
    lines = [
        "# Chatbot gateway setup",
        "",
        "Configure **per-agent** Discord / Telegram / Slack / Zulip bots in Agentic OS → Workflow → Agents → Gateways.",
        "Workflow Chat apps remain the legacy shared-bot fallback when an agent has no gateway token.",
        "",
        "## Operational checklist",
        "",
    ]
    for tip in gateway_guides_payload()["checklist"]:
        lines.append(f"- {tip}")
    lines.append("")
    for platform, guide in GATEWAY_GUIDES.items():
        lines.append(f"## {guide['title']}")
        lines.append("")
        lines.append(guide["summary"])
        lines.append("")
        for i, step in enumerate(guide["steps"], 1):
            lines.append(f"{i}. {step}")
        lines.append("")
        if guide.get("links"):
            lines.append("Links:")
            for link in guide["links"]:
                lines.append(f"- [{link['label']}]({link['url']})")
            lines.append("")
        if guide.get("tips"):
            lines.append("Tips:")
            for tip in guide["tips"]:
                lines.append(f"- {tip}")
            lines.append("")
    return "\n".join(lines).rstrip() + "\n"
