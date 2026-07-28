# Chatbot gateway setup

Configure **per-agent** Discord / Telegram / Slack / Zulip bots in Agentic OS → Workflow → Agents → Gateways.
Workflow Chat apps remain the legacy shared-bot fallback when an agent has no gateway token.

## Operational checklist

- Prefer one bot app per agent so display names match roles (PM, SA, Coder…).
- Never commit tokens; store only via Agentic OS gateway fields (write-only).
- After rotating a token, re-run Test connection and restart/reload the bridge.
- Avoid two agents sharing one token (identity collision on outbound send_as).

## Discord bot gateway

Create one Discord application/bot per agent, enable Message Content Intent, invite to your guild.

1. Open the Discord Developer Portal → New Application (one app per agent, e.g. OMC PM).
2. Bot → Add Bot → Reset/Copy Bot Token → paste into Agent → Gateways → Discord.
3. Privileged Gateway Intents: enable Message Content Intent (Server Members optional; Presence off).
4. OAuth2 → URL Generator: scopes bot (+ applications.commands optional).
5. Bot permissions: View Channels, Send Messages, Read Message History, Embed Links, Attach Files, Add Reactions.
6. Invite the bot to the guild that hosts OMC topic channels.
7. In OMC: map topic channel external IDs, enable Discord on the agent, Test connection.
8. For DMs: users open a DM with the bot; OMC uses the DM intent on this bot.

Links:
- [Discord Developer Portal](https://discord.com/developers/applications)

Tips:
- Prefer one bot app per agent so display names match roles.
- Never commit tokens; rotate after exposure and re-test.

## Telegram bot gateway

Create a bot with BotFather and paste the HTTP API token into the agent gateway.

1. In Telegram open @BotFather → /newbot → choose display name + username (e.g. omc_pm_bot).
2. Copy the HTTP API token → Agent → Gateways → Telegram → Bot token.
3. Optional: /setjoingrouproups; /setprivacy — Disable Privacy Mode only if the bot must read all group messages without mentions.
4. Add the bot to the OMC topic group; send a message; capture chat.id as channel external_id.
5. For DMs: user starts the bot with /start.
6. In OMC: enable Telegram on the agent and Test connection (getMe).

Links:
- [BotFather](https://t.me/BotFather)

Tips:
- Do not share one Telegram token across two agents.
- After rotating a token, restart/reload the bridge.

## Slack bot gateway

Create a Slack app with Socket Mode; store both xoxb bot token and xapp app token per agent.

1. api.slack.com/apps → Create New App → From scratch (one app per agent recommended).
2. Socket Mode: Enable → generate App-Level Token (xapp-…) with connections:write → Agent Gateway App token.
3. OAuth & Permissions → Bot Token Scopes: chat:write, channels:history, groups:history, im:history, mpim:history, app_mentions:read, im:write, users:read.
4. Install to workspace → copy Bot User OAuth Token (xoxb-…) → Agent Gateway Bot token.
5. Event Subscriptions (Socket Mode): message.channels, message.groups, message.im, app_mention.
6. Invite the bot to topic channels (/invite @BotName).
7. In OMC: enable Slack on the agent and Test connection (auth.test).

Links:
- [Slack API Apps](https://api.slack.com/apps)

Tips:
- Both SLACK_BOT_TOKEN and SLACK_APP_TOKEN are required for Socket Mode.

## Zulip bot gateway

Create a Zulip bot and store site URL, bot email, and API key on the agent.

1. Zulip org → Personal settings → Bots (or org bots) → Add a new bot (generic bot recommended).
2. Note bot email, API key, and site URL (e.g. https://chat.example.com).
3. Paste into Agent → Gateways → Zulip: Site URL, Bot email, API key.
4. Subscribe the bot to streams used as OMC topics.
5. DMs: private messages to the bot email route to that agent.
6. In OMC: enable Zulip on the agent and Test connection (get_profile).

Tips:
- Align Zulip stream/topic external ids with the existing Zulip adapter conventions.
