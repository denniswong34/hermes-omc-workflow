"""Create / sync on-disk Hermes profiles for OMC workflow agents.

Clones the default Hermes profile (config.yaml, .env, skills), then overlays
each agent's OMC persona into ``SOUL.md``, profile description, gateway tokens,
and Windows/Unix command aliases.
"""

from __future__ import annotations

import logging
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Optional

from core.config import load_workflow_agent_prompt
from core.db import REPO_ROOT
from core.secrets import PLATFORMS, resolve_agent_gateway_credentials

logger = logging.getLogger(__name__)

_PROFILE_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")

_CLONE_CONFIG_FILES = ("config.yaml", ".env", "SOUL.md")
_CLONE_SUBDIR_FILES = ("memories/MEMORY.md", "memories/USER.md")
_PROFILE_DIRS = (
    "memories",
    "sessions",
    "skills",
    "skins",
    "logs",
    "plans",
    "workspace",
    "cron",
    "home",
)

# Env keys written into a Hermes profile .env from OMC agent gateways
_GATEWAY_ENV_KEYS: dict[str, tuple[str, ...]] = {
    "discord": ("DISCORD_BOT_TOKEN",),
    "telegram": ("TELEGRAM_BOT_TOKEN",),
    "slack": ("SLACK_BOT_TOKEN", "SLACK_APP_TOKEN"),
    "zulip": ("ZULIP_SITE", "ZULIP_EMAIL", "ZULIP_API_KEY"),
}


class HermesProfileError(RuntimeError):
    """Raised when a Hermes profile cannot be created or synced."""


def platform_default_hermes_home() -> Path:
    """Platform-native Hermes root (mirrors hermes_constants)."""
    if sys.platform == "win32":
        local_appdata = os.environ.get("LOCALAPPDATA", "").strip()
        base = Path(local_appdata) if local_appdata else Path.home() / "AppData" / "Local"
        return base / "hermes"
    return Path.home() / ".hermes"


def default_hermes_root() -> Path:
    """Root used for ``profiles/<name>/`` (default Hermes home)."""
    override = os.environ.get("OMC_HERMES_HOME", "").strip()
    if override:
        return Path(override)
    native = platform_default_hermes_home()
    env_home = os.environ.get("HERMES_HOME", "").strip()
    if not env_home:
        return native
    env_path = Path(env_home)
    try:
        env_path.resolve().relative_to(native.resolve())
        return native
    except ValueError:
        pass
    if env_path.parent.name == "profiles":
        return env_path.parent.parent
    return env_path


def profiles_root() -> Path:
    return default_hermes_root() / "profiles"


def profile_dir(name: str) -> Path:
    canon = normalize_profile_name(name)
    if canon == "default":
        return default_hermes_root()
    return profiles_root() / canon


def normalize_profile_name(name: str) -> str:
    stripped = (name or "").strip()
    if not stripped:
        raise ValueError("profile name cannot be empty")
    if stripped.casefold() == "default":
        return "default"
    return stripped.lower()


def validate_profile_name(name: str) -> None:
    if name == "default":
        return
    if not _PROFILE_ID_RE.match(name):
        raise ValueError(
            f"Invalid Hermes profile name {name!r}. "
            "Must match [a-z0-9][a-z0-9_-]{0,63}."
        )


def profile_exists(name: str) -> bool:
    canon = normalize_profile_name(name)
    if canon == "default":
        return default_hermes_root().is_dir()
    return profile_dir(canon).is_dir()


def default_agent_profile_name(workflow_id: str = "", role_id: str = "") -> str:
    """Canonical OMC profile id: ``omc-{role}`` (short, memorable).

    ``workflow_id`` is accepted for call-site compatibility but not used — Hermes
    profiles are global on the machine, so names stay ``omc-pm``, ``omc-sa``, etc.
    """
    role = re.sub(r"[^a-z0-9_-]+", "-", (role_id or "agent").strip().lower()).strip("-_")
    if not role:
        role = "agent"
    safe = f"omc-{role}"
    if len(safe) > 64:
        safe = safe[:64].rstrip("-_")
    if not _PROFILE_ID_RE.match(safe):
        raise ValueError(f"Cannot derive valid Hermes profile name from role {role_id!r}")
    return safe


def hermes_profile_env_path(profile_name: str) -> Path:
    return profile_dir(profile_name) / ".env"


def build_agent_setup_commands(
    profile_name: str,
    *,
    platforms: list[str] | None = None,
) -> dict[str, Any]:
    """Build copy-paste CLI instructions for one Hermes profile."""
    canon = normalize_profile_name(profile_name)
    validate_profile_name(canon)
    exists = profile_exists(canon)
    env_path = hermes_profile_env_path(canon)
    plats = [p for p in (platforms or []) if p in _GATEWAY_ENV_KEYS]

    if sys.platform == "win32":
        open_env = f'notepad "{env_path}"'
        env_hint = r"%LOCALAPPDATA%\hermes\profiles\{}\.env".format(canon)
    else:
        open_env = f'${EDITOR:-nano} "{env_path}"'
        env_hint = f"~/.hermes/profiles/{canon}/.env"

    token_lines: list[str] = []
    for platform in plats:
        for key in _GATEWAY_ENV_KEYS[platform]:
            token_lines.append(f"# {key}=<paste from OMC Agent -> Gateways -> {platform}>")

    commands: list[str] = []
    if exists:
        commands.append(f"# Profile already exists — skip create (or delete first)")
        commands.append(f"# hermes profile delete {canon}   # optional reset")
    else:
        commands.append(f"hermes profile create {canon} --clone-from default")
        commands.append(f"# Creates Windows/Unix command alias: {canon}")

    commands.append(f"# Ensure command alias exists (omc-qa -> hermes -p omc-qa)")
    commands.append(f"hermes profile alias {canon}")

    commands.append("# 2) Put bot tokens + allowlist into the profile .env")
    commands.append(f"#    File: {env_hint}")
    commands.append("#    IMPORTANT: replace DISCORD_BOT_TOKEN with THIS agent's token from")
    commands.append("#    OMC -> Agents -> Gateways (do NOT keep the cloned default token).")
    commands.append(open_env)
    if token_lines:
        commands.extend(token_lines)
    else:
        commands.append("# (No Discord/Telegram/Slack/Zulip tokens configured on this agent yet)")
    commands.append("#    Also add these lines in the same .env file:")
    commands.append("# DISCORD_ALLOW_ALL_USERS=true")
    commands.append("# GATEWAY_ALLOW_ALL_USERS=true")
    if "telegram" in plats:
        commands.append("# TELEGRAM_ALLOW_ALL_USERS=true")

    commands.append("# 3) Start gateway now + auto-start on Windows login")
    commands.append(f"hermes -p {canon} gateway install --start-now --start-on-login")
    commands.append(f"hermes -p {canon} gateway status")
    commands.append("hermes profile list")
    commands.append("# Tip: if Discord still says Improper token, the .env token is wrong/expired.")
    commands.append("# Tip: do not run OMC bridge_multi on the SAME bot token at the same time.")

    return {
        "hermes_profile": canon,
        "profile_exists": exists,
        "env_path": str(env_path),
        "env_path_display": env_hint,
        "platforms": plats,
        "commands": commands,
        "command_block": "\n".join(commands),
    }


def build_hermes_setup_guide(
    repo: Any,
    workflow_id: str,
    *,
    assign_names: bool = True,
) -> dict[str, Any]:
    """
    Assign short ``omc-{role}`` profile names and return CLI setup instructions.

    Does **not** run ``hermes`` automatically — users create profiles and start
    gateways from their own terminal (more reliable on Windows).
    """
    wf = repo.get_workflow(workflow_id)
    if not wf:
        raise HermesProfileError(f"Workflow not found: {workflow_id}")

    root = default_hermes_root()
    agents_out: list[dict[str, Any]] = []
    script_parts: list[str] = [
        "# OMC -> Hermes profile setup (run in Command Prompt / PowerShell / terminal)",
        "# 1) Create each profile from default",
        "# 2) Paste bot tokens into that profile's .env (from OMC Agent -> Gateways)",
        "# 3) Start the Hermes gateway for that profile",
        "#",
        f"# Hermes root: {root}",
        "",
    ]

    for ag in wf.agents:
        role = (ag.role_id or "").strip().lower() or "agent"
        expected = default_agent_profile_name(workflow_id, role)
        if assign_names:
            current = (ag.hermes_profile or "").strip()
            if current != expected:
                repo.update_agent(ag.id, {"hermes_profile": expected})

        platforms: list[str] = []
        identity = ag.platform_identity if hasattr(ag, "platform_identity") else {}
        for platform in PLATFORMS:
            creds = resolve_agent_gateway_credentials(
                workflow_id, ag.id, platform, identity
            )
            keys = _GATEWAY_ENV_KEYS.get(platform) or ()
            if any(creds.get(k) for k in keys):
                platforms.append(platform)

        setup = build_agent_setup_commands(expected, platforms=platforms)
        entry = {
            "agent_id": ag.id,
            "role_id": role,
            "display_name": ag.display_name,
            "mention": getattr(ag, "mention", role),
            **setup,
        }
        agents_out.append(entry)
        script_parts.append(f"# --- @{entry['mention']} / {role} -> {expected} ---")
        script_parts.append(setup["command_block"])
        script_parts.append("")

    return {
        "ok": True,
        "workflow_id": workflow_id,
        "hermes_root": str(root),
        "profiles_root": str(profiles_root()),
        "naming": "omc-{role}",
        "agents": agents_out,
        "script": "\n".join(script_parts).strip() + "\n",
        "instructions": [
            "Open a terminal where the `hermes` command works.",
            "Create each profile with: hermes profile create omc-<role> --clone-from default",
            "Edit that profile's .env: paste THIS agent's Discord/Telegram token from OMC -> Agents -> Gateways (cloned default token will NOT work).",
            "Also set DISCORD_ALLOW_ALL_USERS=true and GATEWAY_ALLOW_ALL_USERS=true so DMs are accepted.",
            "Start with: hermes -p omc-<role> gateway install --start-now --start-on-login",
            "Verify with hermes profile list (Gateway=running) and Discord connected in gateway.log.",
            "Do not run OMC bridge_multi against the same bot token while the Hermes gateway is connected.",
        ],
    }


def upsert_env_values(path: Path, updates: dict[str, str]) -> list[str]:
    """Set keys in a ``.env`` file while preserving comments and key order."""
    changed: list[str] = []
    updates = {k: v for k, v in updates.items() if k and v is not None and str(v) != ""}
    if not updates:
        return changed

    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        lines = path.read_text(encoding="utf-8").splitlines()
    else:
        lines = [
            "# Per-profile secrets for this Hermes profile.",
            "# Managed in part by OMC Agentic OS Hermes profile sync.",
        ]

    remaining = dict(updates)
    out: list[str] = []
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            out.append(line)
            continue
        key, _ = stripped.split("=", 1)
        key = key.strip()
        if key in remaining:
            out.append(f"{key}={remaining.pop(key)}")
            changed.append(key)
        else:
            out.append(line)

    if remaining:
        if out and out[-1].strip():
            out.append("")
        out.append("# OMC agent gateway credentials")
        for key in sorted(remaining):
            out.append(f"{key}={remaining[key]}")
            changed.append(key)

    path.write_text("\n".join(out) + "\n", encoding="utf-8")
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
    return changed


def _which_hermes() -> Optional[str]:
    from shutil import which

    override = os.environ.get("OMC_HERMES_BIN", "").strip()
    if override:
        return override
    return which("hermes")


def _hermes_cli_env() -> dict[str, str]:
    env = os.environ.copy()
    env.setdefault("HERMES_HOME", str(default_hermes_root()))
    env["HERMES_NONINTERACTIVE"] = "1"
    # Prefer start-now + login auto-start during automated sync (CLI flags still win).
    env["HERMES_GATEWAY_INSTALL_START_NOW"] = "1"
    env["HERMES_GATEWAY_INSTALL_START_ON_LOGIN"] = "1"
    # Force UTF-8 for hermes CLI unicode status glyphs on Windows.
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    return env


def _run_hermes(cmd: list[str], *, timeout: float = 120) -> subprocess.CompletedProcess[str]:
    """Run a hermes CLI command with UTF-8 decoding (Windows cp* locales break ✓/✗)."""
    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        env=_hermes_cli_env(),
        stdin=subprocess.DEVNULL,
        check=False,
    )


def _clone_profile_files(source: Path, dest: Path) -> None:
    """Python fallback mirroring ``hermes profile create --clone-from``."""
    dest.mkdir(parents=True, exist_ok=True)
    for subdir in _PROFILE_DIRS:
        (dest / subdir).mkdir(parents=True, exist_ok=True)

    for filename in _CLONE_CONFIG_FILES:
        src = source / filename
        if src.exists():
            shutil.copy2(src, dest / filename)
            if filename == ".env":
                try:
                    os.chmod(dest / filename, 0o600)
                except OSError:
                    pass

    source_skills = source / "skills"
    if source_skills.is_dir():
        shutil.copytree(source_skills, dest / "skills", symlinks=True, dirs_exist_ok=True)

    for relpath in _CLONE_SUBDIR_FILES:
        src = source / relpath
        if src.exists():
            dst = dest / relpath
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)

    env_path = dest / ".env"
    if not env_path.exists():
        env_path.write_text(
            "# Per-profile secrets for this Hermes profile.\n",
            encoding="utf-8",
        )
        try:
            os.chmod(env_path, 0o600)
        except OSError:
            pass


def wrapper_bin_dir() -> Path:
    """Directory where Hermes installs profile command wrappers (``~/.local/bin``)."""
    return Path.home() / ".local" / "bin"


def wrapper_script_path(profile_name: str) -> Path:
    """Path to the shell/bat wrapper for a profile alias."""
    canon = normalize_profile_name(profile_name)
    if sys.platform == "win32":
        return wrapper_bin_dir() / f"{canon}.bat"
    return wrapper_bin_dir() / canon


def _write_wrapper_script(profile_name: str) -> Path:
    """Write ``~/.local/bin/<profile>`` that runs ``hermes -p <profile>``."""
    canon = normalize_profile_name(profile_name)
    validate_profile_name(canon)
    wrapper_dir = wrapper_bin_dir()
    wrapper_dir.mkdir(parents=True, exist_ok=True)
    path = wrapper_script_path(canon)
    if sys.platform == "win32":
        path.write_text(f"@echo off\r\nhermes -p {canon} %*\r\n", encoding="utf-8")
    else:
        path.write_text(
            "#!/usr/bin/env bash\n"
            f'exec hermes -p {canon} "$@"\n',
            encoding="utf-8",
        )
        try:
            os.chmod(path, 0o755)
        except OSError:
            pass
    return path


def ensure_profile_alias(profile_name: str) -> dict[str, Any]:
    """
    Ensure a Windows/Unix command alias exists for the profile.

    Creates ``~/.local/bin/<name>.bat`` (Windows) or ``~/.local/bin/<name>``
    so users can run ``omc-qa gateway status`` instead of
    ``hermes -p omc-qa gateway status``.
    """
    canon = normalize_profile_name(profile_name)
    validate_profile_name(canon)
    if canon == "default":
        return {
            "name": canon,
            "action": "skipped",
            "reason": "default profile has no alias wrapper",
        }

    existing = wrapper_script_path(canon)
    if existing.is_file():
        try:
            content = existing.read_text(encoding="utf-8", errors="replace")
        except OSError:
            content = ""
        if f"hermes -p {canon}" in content:
            return {
                "name": canon,
                "action": "exists",
                "path": str(existing),
            }

    hermes_bin = _which_hermes()
    if hermes_bin:
        try:
            proc = _run_hermes(
                [hermes_bin, "profile", "alias", canon],
                timeout=60,
            )
        except (OSError, subprocess.TimeoutExpired) as e:
            logger.warning("hermes profile alias failed (%s); writing wrapper", e)
        else:
            if proc.returncode == 0 and wrapper_script_path(canon).is_file():
                return {
                    "name": canon,
                    "action": "created",
                    "path": str(wrapper_script_path(canon)),
                    "method": "cli",
                }
            combined = f"{proc.stdout or ''}\n{proc.stderr or ''}".lower()
            if wrapper_script_path(canon).is_file():
                return {
                    "name": canon,
                    "action": "exists",
                    "path": str(wrapper_script_path(canon)),
                    "method": "cli",
                }
            if "conflict" in combined or "already" in combined:
                return {
                    "name": canon,
                    "action": "error",
                    "error": (proc.stderr or proc.stdout or "alias conflict").strip()[:300],
                }

    try:
        path = _write_wrapper_script(canon)
    except OSError as e:
        return {"name": canon, "action": "error", "error": str(e)}
    return {
        "name": canon,
        "action": "created",
        "path": str(path),
        "method": "write",
        "note": (
            f"Ensure {wrapper_bin_dir()} is on PATH "
            "(Hermes normally adds %USERPROFILE%\\.local\\bin)."
        ),
    }


def create_profile_from_default(
    name: str,
    *,
    description: str = "",
    clone_source: str = "default",
    create_alias: bool = True,
) -> dict[str, Any]:
    """
    Ensure a named Hermes profile exists, cloned from the default profile.

    Prefers ``hermes profile create --clone-from default`` (with Windows/Unix
    command alias); falls back to a local file copy if the CLI is unavailable.
    """
    canon = normalize_profile_name(name)
    validate_profile_name(canon)
    if canon == "default":
        raise HermesProfileError("Cannot create a profile named 'default'")

    dest = profile_dir(canon)
    if dest.is_dir():
        result = {
            "name": canon,
            "path": str(dest),
            "action": "exists",
            "source": clone_source,
        }
        if create_alias:
            result["alias"] = ensure_profile_alias(canon)
        return result

    source_name = normalize_profile_name(clone_source)
    source = profile_dir(source_name)
    if not source.is_dir():
        raise HermesProfileError(
            f"Source Hermes profile {source_name!r} not found at {source}. "
            "Install/configure Hermes first (default profile)."
        )

    hermes_bin = _which_hermes()
    method = "copy"
    if hermes_bin:
        cmd = [
            hermes_bin,
            "profile",
            "create",
            canon,
            "--clone-from",
            source_name,
        ]
        if description:
            cmd.extend(["--description", description])
        try:
            proc = _run_hermes(cmd, timeout=120)
        except (OSError, subprocess.TimeoutExpired) as e:
            logger.warning("hermes CLI create failed (%s); using file clone", e)
            _clone_profile_files(source, dest)
            method = "copy"
        else:
            if proc.returncode == 0 and dest.is_dir():
                method = "cli"
            else:
                combined = f"{proc.stdout or ''}\n{proc.stderr or ''}".lower()
                if dest.is_dir() or "already exists" in combined:
                    result = {
                        "name": canon,
                        "path": str(dest if dest.is_dir() else profile_dir(canon)),
                        "action": "exists",
                        "source": source_name,
                        "method": "cli",
                    }
                    if create_alias:
                        result["alias"] = ensure_profile_alias(canon)
                    return result

                logger.warning(
                    "hermes profile create failed (code=%s): %s; falling back to copy",
                    proc.returncode,
                    (proc.stderr or proc.stdout or "").strip()[:400],
                )
                _clone_profile_files(source, dest)
                method = "copy"
    else:
        _clone_profile_files(source, dest)
        method = "copy"

    if not dest.is_dir():
        raise HermesProfileError(f"Failed to create Hermes profile {canon!r}")

    result = {
        "name": canon,
        "path": str(dest),
        "action": "created",
        "source": source_name,
        "method": method,
    }
    if create_alias:
        # CLI create normally installs the alias; ensure for copy fallback /
        # --no-alias races / partial installs.
        result["alias"] = ensure_profile_alias(canon)
    return result


def resolve_omc_agents_dir(repo: Any | None = None) -> Path:
    """Resolve the OMC personas directory (portal markdown files)."""
    if repo is not None:
        db = getattr(repo, "db", None)
        if db is not None and hasattr(db, "get_setting"):
            raw = (db.get_setting("agents_dir", "") or "").strip()
            if raw:
                path = Path(raw).expanduser()
                if path.is_dir():
                    return path.resolve()
    return (REPO_ROOT / "agents").resolve()


def profile_description_text(display_name: str, role_id: str) -> str:
    """Short Hermes profile description shown in dashboards / profile list."""
    name = (display_name or "").strip() or (role_id or "agent").strip()
    if name.lower().startswith("omc "):
        return name
    return f"OMC {name}"


def build_soul_markdown(
    *,
    display_name: str,
    mention: str,
    role_id: str,
    persona_file: str,
    agents_dir: Path,
) -> str:
    """Build Hermes ``SOUL.md`` from the OMC Agent Portal persona."""
    role = (role_id or "").strip().lower() or "agent"
    handle = (mention or role).strip().lstrip("@") or role
    title = (display_name or "").strip() or handle
    body = load_workflow_agent_prompt(agents_dir, role, persona_file or "")
    header = (
        f"# {title}\n\n"
        f"You are @{handle} from the OMC Agent Portal "
        f"(Hermes profile `omc-{role}`).\n"
        "Follow the portal persona and shared SDLC rules below.\n"
    )
    return f"{header}\n---\n\n{body.strip()}\n"


def set_hermes_profile_description(profile_name: str, description: str) -> dict[str, Any]:
    """Set Hermes profile description via CLI."""
    canon = normalize_profile_name(profile_name)
    text = (description or "").strip()
    if not text:
        return {"action": "skipped", "reason": "empty description"}

    hermes_bin = _which_hermes()
    if not hermes_bin:
        return {
            "action": "skipped",
            "reason": "hermes CLI not found",
            "description": text,
        }

    try:
        proc = _run_hermes(
            [hermes_bin, "profile", "describe", canon, "--text", text],
            timeout=60,
        )
    except (OSError, subprocess.TimeoutExpired) as e:
        return {"action": "error", "error": str(e), "description": text}

    if proc.returncode == 0:
        return {"action": "updated", "description": text, "method": "cli"}
    return {
        "action": "error",
        "error": (proc.stderr or proc.stdout or f"exit {proc.returncode}").strip()[:300],
        "description": text,
    }


def apply_agent_persona_to_profile(
    profile_name: str,
    *,
    display_name: str,
    mention: str,
    role_id: str,
    persona_file: str,
    agents_dir: Path,
) -> dict[str, Any]:
    """Write OMC persona into Hermes ``SOUL.md`` and refresh profile description."""
    canon = normalize_profile_name(profile_name)
    dest = profile_dir(canon)
    if not dest.is_dir():
        raise HermesProfileError(f"Hermes profile not found: {canon}")

    soul_path = dest / "SOUL.md"
    content = build_soul_markdown(
        display_name=display_name,
        mention=mention,
        role_id=role_id,
        persona_file=persona_file,
        agents_dir=agents_dir,
    )
    previous = ""
    if soul_path.exists():
        try:
            previous = soul_path.read_text(encoding="utf-8")
        except OSError:
            previous = ""
    soul_changed = previous != content
    if soul_changed:
        soul_path.write_text(content, encoding="utf-8")

    description = profile_description_text(display_name, role_id)
    desc_result = set_hermes_profile_description(canon, description)

    return {
        "soul_path": str(soul_path),
        "soul_changed": soul_changed,
        "soul_bytes": len(content.encode("utf-8")),
        "persona_file": persona_file,
        "agents_dir": str(agents_dir),
        "description": description,
        "description_result": desc_result,
    }


def enable_platforms_in_profile_config(
    profile_name: str,
    platforms: list[str],
    *,
    enabled: bool = True,
) -> list[str]:
    """Set ``platforms.<name>.enabled`` in the profile ``config.yaml``.

    Hermes dashboard Channel toggles read this block. Tokens alone auto-enable
    at runtime unless ``enabled: false`` was set explicitly — writing
    ``enabled: true`` keeps the dashboard in sync with OMC gateways.
    """
    try:
        import yaml
    except ImportError as e:  # pragma: no cover
        raise HermesProfileError("PyYAML required to update profile config.yaml") from e

    canon = normalize_profile_name(profile_name)
    cfg_path = profile_dir(canon) / "config.yaml"
    if not cfg_path.exists():
        return []

    plats = [p for p in platforms if p in _GATEWAY_ENV_KEYS]
    if not plats:
        return []

    data = yaml.safe_load(cfg_path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        data = {}
    block = data.get("platforms")
    if not isinstance(block, dict):
        block = {}
        data["platforms"] = block

    for name in plats:
        entry = block.get(name)
        if not isinstance(entry, dict):
            entry = {}
            block[name] = entry
        entry["enabled"] = enabled

    cfg_path.write_text(
        yaml.safe_dump(
            data, default_flow_style=False, sort_keys=False, allow_unicode=True
        ),
        encoding="utf-8",
    )
    return plats


def apply_agent_gateways_to_profile(
    profile_name: str,
    workflow_id: str,
    agent_id: str,
    platform_identity: dict[str, Any] | None,
) -> list[str]:
    """Write OMC gateway credentials + allow-all flags into the profile ``.env``.

    Always overwrites platform tokens from OMC so a cloned default profile does
    not keep a dead/shared ``DISCORD_BOT_TOKEN``. Also sets
    ``platforms.<name>.enabled: true`` in ``config.yaml`` so the Hermes
    dashboard Channel toggles match the configured gateways.
    """
    updates: dict[str, str] = {}
    applied_platforms: list[str] = []
    identity = platform_identity or {}

    for platform in PLATFORMS:
        creds = resolve_agent_gateway_credentials(
            workflow_id, agent_id, platform, identity
        )
        keys = _GATEWAY_ENV_KEYS.get(platform) or ()
        plat_updates = {k: creds.get(k, "") for k in keys if creds.get(k)}
        if not plat_updates:
            continue
        block = (identity.get(platform) or {}) if isinstance(identity, dict) else {}
        enabled = bool(block.get("enabled")) if isinstance(block, dict) else False
        if not enabled and not plat_updates:
            continue
        updates.update(plat_updates)
        applied_platforms.append(platform)

    if not updates:
        return []

    # Without these, Hermes denies all users when no allowlist is configured.
    updates["GATEWAY_ALLOW_ALL_USERS"] = "true"
    if "discord" in applied_platforms:
        updates["DISCORD_ALLOW_ALL_USERS"] = "true"
    if "telegram" in applied_platforms:
        updates["TELEGRAM_ALLOW_ALL_USERS"] = "true"
    if "slack" in applied_platforms:
        updates["SLACK_ALLOW_ALL_USERS"] = "true"
    if "zulip" in applied_platforms:
        updates["ZULIP_ALLOW_ALL_USERS"] = "true"

    env_path = profile_dir(profile_name) / ".env"
    upsert_env_values(env_path, updates)
    enable_platforms_in_profile_config(profile_name, applied_platforms, enabled=True)
    return applied_platforms


def gateway_status(profile_name: str) -> dict[str, Any]:
    """Return whether a profile gateway process appears to be running."""
    canon = normalize_profile_name(profile_name)

    # Fast path: Hermes writes gateway.pid when the process is up
    pid_file = profile_dir(canon) / "gateway.pid"
    if pid_file.is_file():
        try:
            raw = pid_file.read_text(encoding="utf-8").strip()
            pid = int(re.split(r"\s+", raw)[0])
            if pid > 0:
                if sys.platform == "win32":
                    # os.kill(pid, 0) terminates on Windows — use OpenProcess via tasklist-ish check
                    import ctypes

                    kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
                    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
                    handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, 0, pid)
                    if handle:
                        kernel32.CloseHandle(handle)
                        return {"running": True, "pids": [pid], "source": "pid_file"}
                else:
                    os.kill(pid, 0)
                    return {"running": True, "pids": [pid], "source": "pid_file"}
        except (OSError, ValueError, AttributeError):
            pass

    hermes_bin = _which_hermes()
    if not hermes_bin:
        return {"running": False, "error": "hermes CLI not found"}

    cmd = [hermes_bin, "-p", canon, "gateway", "status"]
    try:
        proc = _run_hermes(cmd, timeout=60)
    except (OSError, subprocess.TimeoutExpired) as e:
        return {"running": False, "error": str(e)}

    text = f"{proc.stdout or ''}\n{proc.stderr or ''}"
    running = bool(
        re.search(
            r"(Gateway (is running|process running|already running)|✓ Gateway)",
            text,
            re.I,
        )
    ) and not bool(re.search(r"Gateway is not running|✗ Gateway", text, re.I))
    # Prefer positive markers even when "not running" appears for other profiles
    if re.search(r"Gateway is running|Gateway process running|Gateway already running", text, re.I):
        running = True
    pids = re.findall(r"PID[:\s]+([\d,\s]+)", text, flags=re.I)
    pid_list: list[int] = []
    for chunk in pids:
        for part in re.split(r"[,\s]+", chunk.strip()):
            if part.isdigit():
                pid_list.append(int(part))
    return {
        "running": running,
        "pids": pid_list,
        "output": text.strip()[:500],
        "source": "cli",
    }


def _wait_for_gateway(profile_name: str, *, attempts: int = 8, delay: float = 1.0) -> dict[str, Any]:
    last: dict[str, Any] = {"running": False}
    for _ in range(max(1, attempts)):
        last = gateway_status(profile_name)
        if last.get("running"):
            return last
        time.sleep(delay)
    return last


def stop_hermes_gateway(profile_name: str) -> dict[str, Any]:
    """Stop a named profile gateway (best-effort)."""
    canon = normalize_profile_name(profile_name)
    hermes_bin = _which_hermes()
    if not hermes_bin:
        return {"status": "error", "error": "hermes CLI not found"}
    try:
        proc = _run_hermes([hermes_bin, "-p", canon, "gateway", "stop"], timeout=120)
    except (OSError, subprocess.TimeoutExpired) as e:
        return {"status": "error", "error": str(e)}
    text = f"{proc.stdout or ''}\n{proc.stderr or ''}".strip()
    time.sleep(1.0)
    return {
        "status": "stopped",
        "profile": canon,
        "output": text[:400],
        "running": bool(gateway_status(canon).get("running")),
    }


def start_hermes_gateway(
    profile_name: str,
    *,
    start_on_login: bool = True,
    force_restart: bool = False,
) -> dict[str, Any]:
    """
    Start a Hermes messaging gateway for a named profile (non-interactive).

    Uses ``hermes -p <name> gateway install --start-now [--start-on-login]``.
    """
    canon = normalize_profile_name(profile_name)
    validate_profile_name(canon)
    if canon == "default":
        raise HermesProfileError("Refusing to manage the default profile gateway from OMC sync")

    if not profile_exists(canon):
        raise HermesProfileError(f"Profile {canon!r} does not exist")

    current = gateway_status(canon)
    if current.get("running") and not force_restart:
        return {
            "status": "already_running",
            "profile": canon,
            "pids": current.get("pids") or [],
        }

    if current.get("running") and force_restart:
        stop_hermes_gateway(canon)

    hermes_bin = _which_hermes()
    if not hermes_bin:
        raise HermesProfileError(
            "Hermes CLI not found on PATH. Install hermes or set OMC_HERMES_BIN."
        )

    login_flag = "--start-on-login" if start_on_login else "--no-start-on-login"
    cmd = [
        hermes_bin,
        "-p",
        canon,
        "gateway",
        "install",
        "--start-now",
        login_flag,
    ]
    try:
        proc = _run_hermes(cmd, timeout=180)
    except (OSError, subprocess.TimeoutExpired) as e:
        raise HermesProfileError(f"Failed to start gateway for {canon}: {e}") from e

    text = f"{proc.stdout or ''}\n{proc.stderr or ''}".strip()
    spawn_ok = bool(
        re.search(
            r"(Gateway started|direct spawn|already running|Gateway is running|"
            r"Startup folder|login item|Scheduled Task)",
            text,
            re.I,
        )
    )
    after = _wait_for_gateway(canon)
    if after.get("running") or (proc.returncode == 0 and spawn_ok):
        return {
            "status": "restarted" if force_restart else "started",
            "profile": canon,
            "pids": after.get("pids") or [],
            "output": text[:400],
            "start_on_login": start_on_login,
        }

    start_cmd = [hermes_bin, "-p", canon, "gateway", "start"]
    try:
        start_proc = _run_hermes(start_cmd, timeout=120)
        text = f"{text}\n{start_proc.stdout or ''}\n{start_proc.stderr or ''}".strip()
        spawn_ok = spawn_ok or bool(
            re.search(r"(Gateway started|direct spawn|already running)", text, re.I)
        )
    except (OSError, subprocess.TimeoutExpired) as e:
        text = f"{text}\nstart fallback failed: {e}".strip()

    after = _wait_for_gateway(canon)
    if after.get("running") or spawn_ok:
        return {
            "status": "restarted" if force_restart else "started",
            "profile": canon,
            "pids": after.get("pids") or [],
            "output": text[:400],
            "start_on_login": start_on_login,
        }

    return {
        "status": "error",
        "profile": canon,
        "error": text[:500] or f"gateway install exited {proc.returncode}",
        "pids": [],
    }


def sync_workflow_hermes_profiles(
    repo: Any,
    workflow_id: str,
    *,
    clone_source: str = "default",
    start_gateways: bool = True,
    start_on_login: bool = True,
) -> dict[str, Any]:
    """
    Sync each workflow agent to a short ``omc-{role}`` Hermes profile:

    1. Assign profile name
    2. Create profile (clone from default) if missing
    3. Write OMC bot tokens + ALLOW_ALL flags into profile ``.env``
    4. Enable matching channels in profile ``config.yaml``
       (``platforms.<name>.enabled: true`` for Hermes dashboard)
    5. Restart gateway with optional Windows login auto-start
    6. Return CLI instructions as a fallback / reference
    """
    wf = repo.get_workflow(workflow_id)
    if not wf:
        raise HermesProfileError(f"Workflow not found: {workflow_id}")

    root = default_hermes_root()
    if not root.is_dir():
        raise HermesProfileError(
            f"Default Hermes home not found at {root}. "
            "Install Hermes Agent first so the default profile can be cloned."
        )

    results: list[dict[str, Any]] = []
    agents_dir = resolve_omc_agents_dir(repo)
    for ag in wf.agents:
        role = (ag.role_id or "").strip().lower()
        entry: dict[str, Any] = {
            "agent_id": ag.id,
            "role_id": role,
            "display_name": ag.display_name,
            "mention": getattr(ag, "mention", role),
            "hermes_profile": "",
            "action": "skipped",
            "path": "",
            "gateways_applied": [],
            "env_keys_written": [],
            "alias": None,
            "persona": None,
            "gateway": None,
            "error": None,
        }
        try:
            expected = default_agent_profile_name(workflow_id, role or "agent")
            current = (ag.hermes_profile or "").strip()
            entry["profile_name_updated"] = current != expected
            if entry["profile_name_updated"]:
                repo.update_agent(ag.id, {"hermes_profile": expected})
            entry["hermes_profile"] = expected

            created = create_profile_from_default(
                expected,
                description=profile_description_text(
                    ag.display_name or "", role or "agent"
                ),
                clone_source=clone_source,
                create_alias=True,
            )
            entry["action"] = created["action"]
            entry["path"] = created["path"]
            entry["method"] = created.get("method")
            entry["alias"] = created.get("alias")
            if (created.get("alias") or {}).get("action") == "error":
                entry["alias_error"] = created["alias"].get("error")

            persona = apply_agent_persona_to_profile(
                expected,
                display_name=ag.display_name or "",
                mention=getattr(ag, "mention", role) or role,
                role_id=role,
                persona_file=getattr(ag, "persona_file", "") or "",
                agents_dir=agents_dir,
            )
            entry["persona"] = persona
            if persona.get("soul_changed") and entry["action"] == "exists":
                entry["action"] = "updated"

            refreshed = repo.get_workflow(workflow_id)
            agent_row = next((a for a in refreshed.agents if a.id == ag.id), ag)
            identity = (
                agent_row.platform_identity
                if hasattr(agent_row, "platform_identity")
                else None
            )
            gateways = apply_agent_gateways_to_profile(
                expected, workflow_id, ag.id, identity
            )
            entry["gateways_applied"] = gateways
            entry["platforms_enabled"] = list(gateways)
            if gateways:
                entry["env_keys_written"] = list(gateways) + ["ALLOW_ALL"]
                if entry["action"] == "exists":
                    entry["action"] = "updated"

            setup = build_agent_setup_commands(expected, platforms=gateways)
            entry["command_block"] = setup["command_block"]
            entry["profile_exists"] = True
            entry["env_path_display"] = setup["env_path_display"]
            entry["platforms"] = gateways

            if start_gateways and gateways:
                gw = start_hermes_gateway(
                    expected,
                    start_on_login=start_on_login,
                    force_restart=True,
                )
                entry["gateway"] = gw
                if gw.get("status") == "error":
                    entry["error"] = gw.get("error") or "gateway start failed"
            elif start_gateways:
                entry["gateway"] = {
                    "status": "skipped",
                    "reason": "no discord/telegram/slack/zulip tokens configured",
                }
        except Exception as e:  # noqa: BLE001 — per-agent isolation
            logger.exception("Hermes profile sync failed for agent %s", ag.id)
            entry["error"] = str(e)
            entry["action"] = "error"
            try:
                expected = default_agent_profile_name(workflow_id, role or "agent")
                setup = build_agent_setup_commands(expected, platforms=[])
                entry["hermes_profile"] = expected
                entry["command_block"] = setup["command_block"]
            except Exception:
                pass

        results.append(entry)

    ok = all(r.get("action") != "error" for r in results)
    gateways_started = sum(
        1
        for r in results
        if (r.get("gateway") or {}).get("status")
        in ("started", "restarted", "already_running")
    )
    gateway_errors = sum(
        1 for r in results if (r.get("gateway") or {}).get("status") == "error"
    )

    script_parts = [
        "# OMC -> Hermes profile sync reference (auto-applied by Sync Hermes profiles)",
        f"# Hermes root: {root}",
        "",
    ]
    for r in results:
        block = r.get("command_block") or ""
        if block:
            script_parts.append(
                f"# --- @{r.get('mention') or r.get('role_id')} -> {r.get('hermes_profile')} ---"
            )
            script_parts.append(block)
            script_parts.append("")

    return {
        "ok": ok and gateway_errors == 0,
        "workflow_id": workflow_id,
        "default_source": str(profile_dir(clone_source)),
        "hermes_root": str(root),
        "profiles_root": str(profiles_root()),
        "naming": "omc-{role}",
        "results": results,
        "agents": results,
        "created": sum(1 for r in results if r.get("action") == "created"),
        "updated": sum(1 for r in results if r.get("action") == "updated"),
        "exists": sum(1 for r in results if r.get("action") == "exists"),
        "errors": sum(1 for r in results if r.get("action") == "error"),
        "gateways_started": gateways_started,
        "gateway_errors": gateway_errors,
        "platforms_enabled": sorted(
            {
                p
                for r in results
                for p in (r.get("platforms_enabled") or r.get("gateways_applied") or [])
            }
        ),
        "script": "\n".join(script_parts).strip() + "\n",
        "instructions": [
            "Sync assigns short names (omc-pm), clones missing profiles from default,",
            "copies OMC Agent Portal persona markdown into each profile SOUL.md,",
            "updates the Hermes profile description from the agent display name,",
            "installs Windows/Unix command aliases (~/.local/bin/omc-pm.bat) so `omc-pm gateway status` works,",
            "writes THIS agent's OMC gateway tokens into the profile .env (replacing the cloned default token),",
            "sets DISCORD_ALLOW_ALL_USERS / GATEWAY_ALLOW_ALL_USERS=true,",
            "enables matching channels in config.yaml (platforms.<name>.enabled: true),",
            "stops OMC bridge_multi before starting gateways (same tokens cannot be shared),",
            "and starts the Hermes gateway with Windows login auto-start.",
            "Use the CLI commands below only if auto-sync fails for an agent.",
            "Do not run OMC bridge_multi on the same bot token while the Hermes gateway is connected.",
        ],
        "agents_dir": str(agents_dir),
        "note": (
            "Hermes gateways use the same bot tokens as OMC agent gateways. "
            "Sync stops bridge_multi before starting profile gateways so Discord/"
            "Telegram are not contested by two clients."
        ),
    }
