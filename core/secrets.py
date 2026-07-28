"""Per-workflow secrets — stored outside SQLite as env files."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

PLATFORMS = ("discord", "slack", "zulip", "telegram")

# Secret keys relevant per chat platform (+ shared ops keys)
PLATFORM_SECRET_KEYS: dict[str, list[str]] = {
    "discord": ["DISCORD_BOT_TOKEN"],
    "slack": ["SLACK_BOT_TOKEN", "SLACK_APP_TOKEN"],
    "zulip": ["ZULIP_SITE", "ZULIP_EMAIL", "ZULIP_API_KEY"],
    "telegram": ["TELEGRAM_BOT_TOKEN"],
}

# Shared Chat apps field: agent message layout (stored in chats.config_json)
MESSAGE_FORMAT_FIELD: dict[str, Any] = {
    "key": "message_format",
    "label": "Message format",
    "kind": "config",
    "input": "select",
    "default": "card",
    "options": [
        {"value": "block", "label": "Block (━━ bars)"},
        {"value": "card", "label": "Card (box header) — default"},
        {"value": "quote", "label": "Quote (speaker style)"},
        {"value": "sections", "label": "Sections (FROM/RESPONSE)"},
    ],
}

# Connection form fields per platform (shown in Chat apps section)
# kind: secret → workflow secrets file (chat-scoped); config → chats.config_json
CHAT_CONNECTION_FIELDS: dict[str, list[dict[str, Any]]] = {
    "discord": [
        {"key": "DISCORD_BOT_TOKEN", "label": "Bot token", "kind": "secret", "input": "password"},
        MESSAGE_FORMAT_FIELD,
    ],
    "slack": [
        {"key": "SLACK_BOT_TOKEN", "label": "Bot token", "kind": "secret", "input": "password"},
        {"key": "SLACK_APP_TOKEN", "label": "App token (Socket Mode)", "kind": "secret", "input": "password"},
        MESSAGE_FORMAT_FIELD,
    ],
    "telegram": [
        {"key": "TELEGRAM_BOT_TOKEN", "label": "Bot token", "kind": "secret", "input": "password"},
        MESSAGE_FORMAT_FIELD,
    ],
    "zulip": [
        {"key": "ZULIP_SITE", "label": "Site URL", "kind": "config", "input": "text"},
        {"key": "ZULIP_EMAIL", "label": "Bot email", "kind": "config", "input": "text"},
        {"key": "ZULIP_API_KEY", "label": "API key", "kind": "secret", "input": "password"},
        MESSAGE_FORMAT_FIELD,
    ],
}

# Per-agent gateway credentials (no message_format — that stays on chat connections)
AGENT_GATEWAY_FIELDS: dict[str, list[dict[str, Any]]] = {
    "discord": [
        {"key": "DISCORD_BOT_TOKEN", "label": "Bot token", "kind": "secret", "input": "password"},
    ],
    "slack": [
        {"key": "SLACK_BOT_TOKEN", "label": "Bot token", "kind": "secret", "input": "password"},
        {"key": "SLACK_APP_TOKEN", "label": "App token (Socket Mode)", "kind": "secret", "input": "password"},
    ],
    "telegram": [
        {"key": "TELEGRAM_BOT_TOKEN", "label": "Bot token", "kind": "secret", "input": "password"},
    ],
    "zulip": [
        {"key": "ZULIP_SITE", "label": "Site URL", "kind": "config", "input": "text"},
        {"key": "ZULIP_EMAIL", "label": "Bot email", "kind": "config", "input": "text"},
        {"key": "ZULIP_API_KEY", "label": "API key", "kind": "secret", "input": "password"},
    ],
}

TRACKING_PROVIDERS = ("jira", "plane")

# Connection form fields per ticket tracker (Tracking section dialog)
# kind: secret → workflow secrets file; config → workflows.tracking_config_json
TRACKING_CONNECTION_FIELDS: dict[str, list[dict[str, str]]] = {
    "jira": [
        {"key": "base_url", "label": "Base URL", "kind": "config", "input": "text"},
        {"key": "email", "label": "Email", "kind": "config", "input": "text"},
        {"key": "project_key", "label": "Project key", "kind": "config", "input": "text"},
        {
            "key": "api_token",
            "label": "API token",
            "kind": "secret",
            "input": "password",
            "secret_env": "JIRA_API_TOKEN",
        },
    ],
    "plane": [
        {"key": "base_url", "label": "Base URL", "kind": "config", "input": "text"},
        {"key": "workspace", "label": "Workspace", "kind": "config", "input": "text"},
        {"key": "project_id", "label": "Project ID", "kind": "config", "input": "text"},
        {
            "key": "api_key",
            "label": "API key",
            "kind": "secret",
            "input": "password",
            "secret_env": "PLANE_API_KEY",
        },
    ],
}

# Map dialog secret field → env key written to workflow secrets
TRACKING_SECRET_ENV: dict[str, str] = {
    "jira:api_token": "JIRA_API_TOKEN",
    "plane:api_key": "PLANE_API_KEY",
}

SHARED_SECRET_KEYS = [
    "OMC_WORKSPACE",
    "OMC_OBSIDIAN_VAULT",
    "JIRA_API_TOKEN",
    "JIRA_EMAIL",
    "JIRA_BASE_URL",
    "PLANE_API_KEY",
    "PLANE_BASE_URL",
]

SECRET_FIELD_META: dict[str, str] = {
    "DISCORD_BOT_TOKEN": "Discord bot token",
    "SLACK_BOT_TOKEN": "Slack bot token",
    "SLACK_APP_TOKEN": "Slack app token (Socket Mode)",
    "ZULIP_SITE": "Zulip site URL",
    "ZULIP_EMAIL": "Zulip bot email",
    "ZULIP_API_KEY": "Zulip API key",
    "TELEGRAM_BOT_TOKEN": "Telegram bot token",
    "OMC_WORKSPACE": "Coding workspace path",
    "OMC_OBSIDIAN_VAULT": "Obsidian vault path",
    "JIRA_API_TOKEN": "Jira API token",
    "JIRA_EMAIL": "Jira email",
    "JIRA_BASE_URL": "Jira base URL",
    "PLANE_API_KEY": "Plane API key",
    "PLANE_BASE_URL": "Plane base URL",
    "GITHUB_USERNAME": "GitHub username",
    "GITHUB_PAT": "GitHub personal access token",
}

PROJECT_SECRET_KEYS = ("GITHUB_USERNAME", "GITHUB_PAT")


def secrets_root() -> Path:
    return Path(
        os.environ.get("OMC_SECRETS_DIR", "~/.hermes/omc/secrets")
    ).expanduser()


def workflow_secrets_path(workflow_id: str) -> Path:
    root = secrets_root()
    root.mkdir(parents=True, exist_ok=True)
    return root / f"{workflow_id}.env"


def chat_secret_key(chat_id: str, field_key: str) -> str:
    """Namespace secrets per chat connection inside the workflow env file."""
    return f"CHAT_{chat_id}_{field_key}"


def agent_secret_key(agent_id: str, field_key: str) -> str:
    """Namespace secrets per agent gateway inside the workflow env file."""
    return f"AGENT_{agent_id}_{field_key}"


def gateway_fields_for_platform(platform: str) -> list[dict[str, Any]]:
    return list(AGENT_GATEWAY_FIELDS.get((platform or "").lower(), []))


def read_env_file(path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    if not path.exists():
        return out
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        out[k.strip()] = v
    return out


def write_env_file(path: Path, entries: dict[str, str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [f"{k}={v}" for k, v in sorted(entries.items()) if k]
    path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")


def get_workflow_secrets(workflow_id: str) -> dict[str, Any]:
    path = workflow_secrets_path(workflow_id)
    data = read_env_file(path)
    return {
        "workflow_id": workflow_id,
        "path": str(path),
        "keys": sorted(data.keys()),
        "note": "Values are write-only; blank on save keeps existing",
    }


def update_workflow_secrets(
    workflow_id: str, entries: dict[str, str]
) -> dict[str, Any]:
    path = workflow_secrets_path(workflow_id)
    existing = read_env_file(path)
    for k, v in entries.items():
        if not k:
            continue
        # Skip placeholder / empty to preserve
        if v is None or v == "" or str(v).startswith("(stored"):
            continue
        existing[k] = str(v)
        os.environ[k] = str(v)  # process-local for this API/bridge process
    write_env_file(path, existing)
    return get_workflow_secrets(workflow_id)


def load_workflow_secrets_into_environ(workflow_id: str) -> dict[str, str]:
    data = read_env_file(workflow_secrets_path(workflow_id))
    for k, v in data.items():
        os.environ[k] = v
    return data


def secret_fields_for_platforms(platforms: list[str]) -> list[dict[str, str]]:
    keys: list[str] = []
    seen: set[str] = set()
    for p in platforms:
        for k in PLATFORM_SECRET_KEYS.get(p, []):
            if k not in seen:
                seen.add(k)
                keys.append(k)
    for k in SHARED_SECRET_KEYS:
        if k not in seen:
            seen.add(k)
            keys.append(k)
    return [{"key": k, "label": SECRET_FIELD_META.get(k, k)} for k in keys]


def connection_fields_for_platform(platform: str) -> list[dict[str, Any]]:
    return list(CHAT_CONNECTION_FIELDS.get((platform or "").lower(), []))


def enrich_chat_connection(
    workflow_id: str, chat: dict[str, Any]
) -> dict[str, Any]:
    """Attach field schemas + stored flags for Chat apps UI."""
    platform = (chat.get("platform") or "discord").lower()
    fields = connection_fields_for_platform(platform)
    secrets = read_env_file(workflow_secrets_path(workflow_id))
    config = dict(chat.get("config") or {})
    stored_secrets: dict[str, bool] = {}
    values: dict[str, str] = {}
    for f in fields:
        key = f["key"]
        if f["kind"] == "secret":
            scoped = chat_secret_key(chat["id"], key)
            # Prefer chat-scoped; fall back to legacy global key
            has = bool(secrets.get(scoped) or secrets.get(key))
            stored_secrets[key] = has
            values[key] = ""
        else:
            values[key] = str(config.get(key) or f.get("default") or "")
    out = dict(chat)
    out["connection_fields"] = fields
    out["stored_secrets"] = stored_secrets
    out["connection_values"] = values
    out["config"] = config
    return out


def save_chat_connection(
    workflow_id: str,
    chat_id: str,
    platform: str,
    config_updates: dict[str, Any] | None,
    secret_updates: dict[str, str] | None,
) -> dict[str, str]:
    """
    Persist non-secret config (returned for DB merge) and secret fields to env file.
    Also mirrors secrets to unscoped platform keys for adapter compatibility.
    """
    fields = connection_fields_for_platform(platform)
    field_by_key = {f["key"]: f for f in fields}
    config_out: dict[str, str] = {}
    secret_entries: dict[str, str] = {}

    if config_updates:
        for k, v in config_updates.items():
            meta = field_by_key.get(k)
            if meta and meta["kind"] == "config":
                config_out[k] = str(v) if v is not None else ""

    if secret_updates:
        for k, v in secret_updates.items():
            meta = field_by_key.get(k)
            if not meta or meta["kind"] != "secret":
                continue
            if v is None or v == "" or str(v).startswith("(stored"):
                continue
            scoped = chat_secret_key(chat_id, k)
            secret_entries[scoped] = str(v)
            secret_entries[k] = str(v)  # adapter-friendly global alias

    if secret_entries:
        update_workflow_secrets(workflow_id, secret_entries)
    return config_out


def resolve_chat_secrets(workflow_id: str, chat_id: str, platform: str) -> dict[str, str]:
    """Resolve secret values for a chat (scoped first, then global)."""
    secrets = read_env_file(workflow_secrets_path(workflow_id))
    out: dict[str, str] = {}
    for f in connection_fields_for_platform(platform):
        if f["kind"] != "secret":
            continue
        key = f["key"]
        scoped = chat_secret_key(chat_id, key)
        out[key] = secrets.get(scoped) or secrets.get(key) or ""
    return out


def connection_fields_for_tracking(provider: str) -> list[dict[str, str]]:
    return list(TRACKING_CONNECTION_FIELDS.get((provider or "").lower(), []))


def tracking_secret_env(provider: str, field_key: str) -> str:
    return TRACKING_SECRET_ENV.get(f"{provider}:{field_key}") or field_key.upper()


def tracking_connection_secret_key(connection_id: str, field_key: str) -> str:
    """Scoped secret key for a tracking connection (mirrors CHAT_{id}_*)."""
    return f"TRACK_{connection_id}_{field_key}"


def enrich_tracking_connection(
    workflow_id: str,
    provider: str,
    tracking_config: dict[str, Any] | None,
    *,
    connection_id: str = "",
    is_active: bool = False,
) -> dict[str, Any]:
    """Attach field schemas + stored flags for Tracking UI."""
    provider = (provider or "none").strip().lower()
    cfg = dict(tracking_config or {})
    # Prefer nested provider block when present
    nested = dict(cfg.get(provider) or {}) if provider in TRACKING_PROVIDERS else {}
    flat = {
        k: v
        for k, v in cfg.items()
        if k not in ("provider", "jira", "plane", "label")
    }
    merged = {**flat, **nested}

    fields = connection_fields_for_tracking(provider)
    secrets = read_env_file(workflow_secrets_path(workflow_id))
    stored_secrets: dict[str, bool] = {}
    values: dict[str, str] = {}
    for f in fields:
        key = f["key"]
        if f["kind"] == "secret":
            env_key = f.get("secret_env") or tracking_secret_env(provider, key)
            scoped = (
                tracking_connection_secret_key(connection_id, key)
                if connection_id
                else ""
            )
            has = bool(
                (scoped and secrets.get(scoped))
                or secrets.get(env_key)
                or merged.get(key)
            )
            stored_secrets[key] = has
            values[key] = ""
        else:
            values[key] = str(merged.get(key) or cfg.get(key) or "")

    label = str(cfg.get("label") or "").strip()
    if not label and provider in TRACKING_PROVIDERS:
        label = f"{provider[:1].upper()}{provider[1:]} #1"

    return {
        "id": connection_id or "",
        "provider": provider,
        "label": label,
        "config": merged,
        "connection_fields": fields,
        "stored_secrets": stored_secrets,
        "connection_values": values,
        "configured": provider in TRACKING_PROVIDERS,
        "is_active": bool(is_active),
    }


def save_tracking_connection(
    workflow_id: str,
    provider: str,
    config_updates: dict[str, Any] | None,
    secret_updates: dict[str, str] | None,
    label: str | None = None,
    *,
    connection_id: str = "",
    existing_config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Persist tracking non-secret config (returned for DB) and secrets to env file.
    Returns tracking_config payload to store on the connection / workflow cache.
    """
    provider = (provider or "none").strip().lower()
    if provider not in TRACKING_PROVIDERS:
        return {}

    fields = connection_fields_for_tracking(provider)
    field_by_key = {f["key"]: f for f in fields}
    # Start from existing nested provider config so partial updates keep fields
    prior = dict((existing_config or {}).get(provider) or {})
    if not prior and existing_config:
        prior = {
            k: v
            for k, v in (existing_config or {}).items()
            if k not in ("provider", "jira", "plane", "label", "status_map")
        }
    provider_cfg: dict[str, Any] = dict(prior)
    secret_entries: dict[str, str] = {}

    if config_updates:
        for k, v in config_updates.items():
            meta = field_by_key.get(k)
            if meta and meta["kind"] == "config":
                provider_cfg[k] = str(v) if v is not None else ""
            elif k == "status_map" and isinstance(v, dict):
                provider_cfg["status_map"] = v

    if secret_updates:
        for k, v in secret_updates.items():
            meta = field_by_key.get(k)
            if not meta or meta["kind"] != "secret":
                continue
            if v is None or v == "" or str(v).startswith("(stored"):
                continue
            legacy_env = meta.get("secret_env") or tracking_secret_env(provider, k)
            if connection_id:
                secret_entries[tracking_connection_secret_key(connection_id, k)] = str(v)
            # Keep legacy unscoped key so older runtimes still resolve the active tracker
            secret_entries[legacy_env] = str(v)

    if secret_entries:
        update_workflow_secrets(workflow_id, secret_entries)

    out: dict[str, Any] = {provider: provider_cfg}
    if label is not None:
        out["label"] = str(label).strip()
    elif existing_config and existing_config.get("label"):
        out["label"] = str(existing_config.get("label") or "").strip()
    return out


def resolve_tracking_secrets(
    workflow_id: str,
    provider: str,
    *,
    connection_id: str = "",
) -> dict[str, str]:
    """Resolve secret field values for a tracking provider / connection."""
    provider = (provider or "").strip().lower()
    secrets = read_env_file(workflow_secrets_path(workflow_id))
    out: dict[str, str] = {}
    for f in connection_fields_for_tracking(provider):
        if f["kind"] != "secret":
            continue
        legacy_env = f.get("secret_env") or tracking_secret_env(provider, f["key"])
        scoped = (
            tracking_connection_secret_key(connection_id, f["key"])
            if connection_id
            else ""
        )
        out[f["key"]] = (
            (scoped and secrets.get(scoped)) or secrets.get(legacy_env) or ""
        )
    return out


def build_tracker_config(
    workflow_id: str,
    provider: str,
    tracking_config: dict[str, Any] | None,
    *,
    connection_id: str = "",
) -> dict[str, Any]:
    """Build create_tracker()-ready config with secrets injected."""
    provider = (provider or "none").strip().lower()
    cfg = dict(tracking_config or {})
    out: dict[str, Any] = {"provider": provider}
    if provider not in TRACKING_PROVIDERS:
        return out

    nested = dict(cfg.get(provider) or {})
    flat = {
        k: v
        for k, v in cfg.items()
        if k not in ("provider", "jira", "plane", "label")
    }
    merged = {**flat, **nested}
    secrets = resolve_tracking_secrets(
        workflow_id, provider, connection_id=connection_id
    )
    for k, v in secrets.items():
        if v:
            merged[k] = v
    out[provider] = merged
    return out


def _default_platform_identity() -> dict[str, Any]:
    return {
        p: {
            "enabled": False,
            "bot_user_id": "",
            "bot_username": "",
            "bot_email": "",
            "site": "",
            "config": {},
        }
        for p in PLATFORMS
    }


def normalize_platform_identity(raw: Any) -> dict[str, Any]:
    base = _default_platform_identity()
    if not isinstance(raw, dict):
        return base
    for platform in PLATFORMS:
        block = raw.get(platform)
        if not isinstance(block, dict):
            continue
        merged = dict(base[platform])
        if "enabled" in block:
            merged["enabled"] = bool(block["enabled"])
        for key in ("bot_user_id", "bot_username", "bot_email", "site"):
            if key in block and block[key] is not None:
                merged[key] = str(block[key])
        if isinstance(block.get("config"), dict):
            merged["config"] = {str(k): str(v) for k, v in block["config"].items()}
        base[platform] = merged
    return base


def enrich_agent_gateways(
    workflow_id: str,
    agent: dict[str, Any],
) -> dict[str, Any]:
    """Attach gateway field schemas + stored flags for Agent Gateway UI."""
    secrets = read_env_file(workflow_secrets_path(workflow_id))
    identity = normalize_platform_identity(agent.get("platform_identity") or {})
    platforms_out: dict[str, Any] = {}
    for platform in PLATFORMS:
        fields = gateway_fields_for_platform(platform)
        stored_secrets: dict[str, bool] = {}
        values: dict[str, str] = {}
        plat_id = identity.get(platform) or {}
        cfg = plat_id.get("config") if isinstance(plat_id.get("config"), dict) else {}
        for f in fields:
            key = f["key"]
            if f["kind"] == "secret":
                scoped = agent_secret_key(agent["id"], key)
                stored_secrets[key] = bool(secrets.get(scoped))
                values[key] = ""
            elif key == "ZULIP_SITE":
                values[key] = str(cfg.get(key) or plat_id.get("site") or "")
            elif key == "ZULIP_EMAIL":
                values[key] = str(cfg.get(key) or plat_id.get("bot_email") or "")
            else:
                values[key] = str(cfg.get(key) or "")
        platforms_out[platform] = {
            "enabled": bool(plat_id.get("enabled")),
            "bot_user_id": str(plat_id.get("bot_user_id") or ""),
            "bot_username": str(plat_id.get("bot_username") or ""),
            "bot_email": str(plat_id.get("bot_email") or ""),
            "connection_fields": fields,
            "stored_secrets": stored_secrets,
            "connection_values": values,
            "configured": any(stored_secrets.values())
            or any(bool(values.get(f["key"])) for f in fields if f["kind"] == "config"),
        }
    out = dict(agent)
    out["platform_identity"] = identity
    out["gateways"] = platforms_out
    out["gateway_fields"] = AGENT_GATEWAY_FIELDS
    return out


def save_agent_gateway(
    workflow_id: str,
    agent_id: str,
    platform: str,
    *,
    enabled: bool | None = None,
    identity_updates: dict[str, Any] | None = None,
    config_updates: dict[str, Any] | None = None,
    secret_updates: dict[str, str] | None = None,
    current_identity: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Persist per-agent gateway secrets and return updated platform_identity dict
    (caller writes platform_identity_json to DB).
    """
    platform = (platform or "").strip().lower()
    if platform not in PLATFORMS:
        raise ValueError(f"platform must be one of {PLATFORMS}")

    identity = normalize_platform_identity(current_identity)
    block = dict(identity[platform])
    cfg = dict(block.get("config") or {}) if isinstance(block.get("config"), dict) else {}

    if enabled is not None:
        block["enabled"] = bool(enabled)
    if identity_updates:
        for k in ("bot_user_id", "bot_username", "bot_email"):
            if k in identity_updates and identity_updates[k] is not None:
                block[k] = str(identity_updates[k])

    fields = gateway_fields_for_platform(platform)
    field_by_key = {f["key"]: f for f in fields}
    secret_entries: dict[str, str] = {}

    if config_updates:
        for k, v in config_updates.items():
            meta = field_by_key.get(k)
            if meta and meta["kind"] == "config":
                cfg[k] = str(v) if v is not None else ""
                if k == "ZULIP_SITE":
                    block["site"] = cfg[k]
                elif k == "ZULIP_EMAIL":
                    block["bot_email"] = cfg[k]

    if secret_updates:
        for k, v in secret_updates.items():
            meta = field_by_key.get(k)
            if not meta or meta["kind"] != "secret":
                continue
            if v is None or v == "" or str(v).startswith("(stored"):
                continue
            secret_entries[agent_secret_key(agent_id, k)] = str(v)

    if cfg:
        block["config"] = cfg
    identity[platform] = block

    if secret_entries:
        update_workflow_secrets(workflow_id, secret_entries)
    return identity


def resolve_agent_gateway_credentials(
    workflow_id: str, agent_id: str, platform: str, identity: dict[str, Any] | None = None
) -> dict[str, str]:
    """Resolve flat credential dict for an agent gateway (for tests / adapters)."""
    platform = (platform or "").strip().lower()
    secrets = read_env_file(workflow_secrets_path(workflow_id))
    identity = normalize_platform_identity(identity)
    block = identity.get(platform) or {}
    cfg = block.get("config") if isinstance(block.get("config"), dict) else {}
    out: dict[str, str] = {}
    for f in gateway_fields_for_platform(platform):
        key = f["key"]
        if f["kind"] == "secret":
            out[key] = secrets.get(agent_secret_key(agent_id, key)) or ""
        else:
            if key == "ZULIP_SITE":
                out[key] = str(cfg.get(key) or block.get("site") or "")
            elif key == "ZULIP_EMAIL":
                out[key] = str(cfg.get(key) or block.get("bot_email") or "")
            else:
                out[key] = str(cfg.get(key) or "")
    return out


def agent_has_gateway_credentials(
    workflow_id: str, agent_id: str, platform: str, identity: dict[str, Any] | None = None
) -> bool:
    creds = resolve_agent_gateway_credentials(workflow_id, agent_id, platform, identity)
    identity = normalize_platform_identity(identity)
    if not identity.get(platform, {}).get("enabled"):
        return False
    if platform == "discord":
        return bool(creds.get("DISCORD_BOT_TOKEN"))
    if platform == "telegram":
        return bool(creds.get("TELEGRAM_BOT_TOKEN"))
    if platform == "slack":
        return bool(creds.get("SLACK_BOT_TOKEN") and creds.get("SLACK_APP_TOKEN"))
    if platform == "zulip":
        return bool(
            creds.get("ZULIP_API_KEY")
            and creds.get("ZULIP_SITE")
            and creds.get("ZULIP_EMAIL")
        )
    return False


def projects_secrets_root() -> Path:
    return Path(
        os.environ.get(
            "OMC_PROJECT_SECRETS_DIR",
            str(Path.home() / ".hermes" / "omc" / "projects"),
        )
    ).expanduser()


def project_secrets_path(project_id: str) -> Path:
    root = projects_secrets_root() / project_id
    root.mkdir(parents=True, exist_ok=True)
    return root / "secrets.env"


def get_project_secrets_meta(project_id: str) -> dict[str, Any]:
    path = project_secrets_path(project_id)
    data = read_env_file(path)
    return {
        "project_id": project_id,
        "path": str(path),
        "keys": sorted(k for k in data.keys() if data.get(k)),
        "has_pat": bool(data.get("GITHUB_PAT")),
        "has_username": bool(data.get("GITHUB_USERNAME")),
        "note": "Values are write-only; blank on save keeps existing",
    }


def update_project_secrets(project_id: str, entries: dict[str, str]) -> dict[str, Any]:
    path = project_secrets_path(project_id)
    existing = read_env_file(path)
    for k, v in entries.items():
        if not k:
            continue
        if v is None or v == "" or str(v).startswith("(stored"):
            continue
        existing[k] = str(v)
    write_env_file(path, existing)
    return get_project_secrets_meta(project_id)


def resolve_project_secrets(project_id: str) -> dict[str, str]:
    return read_env_file(project_secrets_path(project_id))


def delete_project_secrets(project_id: str) -> None:
    path = project_secrets_path(project_id)
    if path.exists():
        path.unlink()
    parent = path.parent
    if parent.exists() and parent.is_dir() and not any(parent.iterdir()):
        parent.rmdir()
