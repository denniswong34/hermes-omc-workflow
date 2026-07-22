# Hermes OMC Workflow Bridge

**One Man Company (OMC) SDLC automation** — Multi-channel adapter for the Hermes Agent workflow (PM → SA → Coder → QA → Done).

## Architecture

```
┌─────────────┐
│  User       │  (Discord / Zulip / Slack / Telegram)
└──────┬──────┘
       │  message
       ▼
┌────────────────────────────────────────────────┐
│  ChannelAdapter (plug-in)                      │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐      │
│  │ Discord  │ │  Zulip   │ │  Slack   │  ...  │
│  └──────────┘ └──────────┘ └──────────┘      │
└──────────────────────┬─────────────────────────┘
       │  Message (normalised)
       ▼
┌────────────────────────────────────────────────┐
│  AgentRouter                                    │
│  • Route to correct agent (PM/SA/Coder/QA)     │
│  • Cross-channel @mentions                     │
│  • SDLC state detection                        │
│  • Plane.so ticket sync                        │
└──────┬──────┬──────┬──────┬────────────────────┘
       │      │      │      │
       ▼      ▼      ▼      ▼
     PM     SA    Coder   QA    (Hermes agents)
```

## Quick Start

```bash
# Install dependencies
pip install -r requirements.txt

# Run with Discord (default)
python3 bridge.py

# Or specify adapter
OMC_ADAPTER=discord python3 bridge.py
```

## Adapter Pattern

Adding a new channel requires implementing `ChannelAdapter`:

```python
from adapters.base import ChannelAdapter

class TelegramAdapter(ChannelAdapter):
    async def start(self): ...
    async def stop(self): ...
    async def send_message(self, channel_id, content): ...
    async def edit_message(self, channel_id, message_id, content): ...
    async def send_typing(self, channel_id): ...
    def on_message(self, handler): ...
```

Then register it in `bridge.py` and set `OMC_ADAPTER=telegram`.

## Roadmap

- [x] Discord adapter (production)
- [ ] Zulip adapter
- [ ] Slack adapter
- [ ] Telegram adapter

## Config

Configuration is loaded from `~/.hermes/config.yaml` (Hermes default) or
a custom path via `OMC_CONFIG` env var. Set the active adapter with:

```bash
export OMC_ADAPTER=zulip   # Switch to Zulip
```
