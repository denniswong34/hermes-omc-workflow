#!/usr/bin/env python3
"""Configure SMTP credentials for the magic-link email delivery system.

Reads SMTP_* / AWS_SES_* from the current environment, interactive prompts,
or a .env file, and writes them to ~/.hermes/omc/secrets.env.

Usage:
    python scripts/setup_mailer.py                          # interactive prompts
    python scripts/setup_mailer.py --env-file .env           # read from .env file
    SMTP_HOST=smtp.example.com python scripts/setup_mailer.py --non-interactive
    python scripts/setup_mailer.py --help
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path


SECRETS_PATH = Path.home() / ".hermes" / "omc" / "secrets.env"

SMTP_VARS = {
    "SMTP_HOST": "SMTP server hostname (e.g. smtp.gmail.com)",
    "SMTP_PORT": "SMTP server port (default 587)",
    "SMTP_TLS": "Use TLS? 1=yes, 0=no (default 1)",
    "SMTP_USERNAME": "SMTP username (often the full email address)",
    "SMTP_PASSWORD": "SMTP password or app-specific password",
    "SMTP_FROM": "From: address for outgoing emails",
}

SES_VARS = {
    "AWS_SES_FROM": "Verified SES sender email address",
    "AWS_SES_REGION": "AWS region (default us-east-1)",
    "AWS_ACCESS_KEY_ID": "AWS access key ID (optional — uses IAM chain if unset)",
    "AWS_SECRET_ACCESS_KEY": "AWS secret access key (optional)",
}


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
    existing = read_env_file(path)
    existing.update(entries)
    lines = [f"{k}={v}" for k, v in sorted(existing.items()) if k]
    path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
    print(f"  ✓ Wrote {len(entries)} entries to {path}")


def prompt_var(key: str, label: str, current: str = "") -> str:
    default = current or os.environ.get(key, "")
    hint = f" [{default}]" if default else ""
    val = input(f"  {label}{hint}: ").strip()
    return val if val else default


def detect_backend_from_env(env: dict[str, str]) -> str:
    """Detect which email backend is configured."""
    if env.get("MAILER_BACKEND") in ("smtp", "ses", "console"):
        return env["MAILER_BACKEND"]
    if env.get("AWS_SES_FROM") or env.get("SES_FROM"):
        return "ses"
    if env.get("SMTP_HOST"):
        return "smtp"
    return "none"


def do_interactive() -> dict[str, str]:
    print("\n--- SMTP / Email Provider Configuration ---\n")
    print("Choose a backend:")
    print("  1) SMTP  (generic — Gmail, Mailgun, SendGrid SMTP, etc.)")
    print("  2) AWS SES")
    print("  3) Console (dev only — emails are logged, not sent)")
    choice = input("\nChoice [1]: ").strip() or "1"

    entries: dict[str, str] = {}
    current = read_env_file(SECRETS_PATH)

    if choice == "1":
        print("\n── SMTP Configuration ──\n")
        for key, label in SMTP_VARS.items():
            val = prompt_var(key, label, current.get(key, ""))
            if val:  # only write non-empty
                entries[key] = val
    elif choice == "2":
        print("\n── SES Configuration ──\n")
        for key, label in SES_VARS.items():
            val = prompt_var(key, label, current.get(key, ""))
            if val:
                entries[key] = val
    else:
        entries["MAILER_BACKEND"] = "console"
        print("  → ConsoleEmailProvider (dev mode)")

    entries["MAILER_BACKEND"] = detect_backend_from_env({**current, **entries})
    print(f"  → Detected backend: {entries['MAILER_BACKEND']}")
    return entries


def do_from_env_file(env_path: str) -> dict[str, str]:
    path = Path(env_path).expanduser()
    if not path.exists():
        print(f"  ✗ File not found: {path}", file=sys.stderr)
        sys.exit(1)
    env = read_env_file(path)
    print(f"  ✓ Read {len(env)} entries from {path}")
    # Filter only SMTP/SES vars
    keys = set(SMTP_VARS.keys()) | set(SES_VARS.keys()) | {"MAILER_BACKEND"}
    entries = {k: v for k, v in env.items() if k in keys}
    if not entries:
        print("  ⚠ No recognised SMTP/SES vars found in file", file=sys.stderr)
        sys.exit(1)
    entries["MAILER_BACKEND"] = detect_backend_from_env(env)
    return entries


def do_non_interactive() -> dict[str, str]:
    """Pick up SMTP/SES vars already set in the current environment."""
    entries = {k: os.environ[k] for k in SMTP_VARS if os.environ.get(k)}
    entries.update({k: os.environ[k] for k in SES_VARS if os.environ.get(k)})
    if "MAILER_BACKEND" in os.environ:
        entries["MAILER_BACKEND"] = os.environ["MAILER_BACKEND"]
    if not entries:
        print("  ⚠ No SMTP_* or AWS_SES_* env vars found in environment")
        print("  Run with --help to see available options")
        sys.exit(1)
    entries.setdefault("MAILER_BACKEND", detect_backend_from_env(os.environ))
    return entries


def main() -> None:
    parser = argparse.ArgumentParser(description="Configure SMTP/SES email credentials")
    parser.add_argument("--env-file", help="Read SMTP vars from a .env file")
    parser.add_argument(
        "--non-interactive",
        action="store_true",
        help="Use env vars already set in the environment (no prompts)",
    )
    parser.add_argument(
        "--print",
        dest="print_only",
        action="store_true",
        help="Print the resulting config to stdout (don't write to secrets.env)",
    )
    args = parser.parse_args()

    # Collect entries
    if args.env_file:
        entries = do_from_env_file(args.env_file)
    elif args.non_interactive:
        entries = do_non_interactive()
    else:
        entries = do_interactive()

    if not entries:
        print("  ⚠ No entries to save")
        sys.exit(1)

    if args.print_only:
        print("\n── Mailer Config ──")
        for k, v in sorted(entries.items()):
            if "PASS" in k.upper() or "SECRET" in k.upper():
                print(f"  {k}=****")
            else:
                print(f"  {k}={v}")
        return

    # Write to secrets.env
    write_env_file(SECRETS_PATH, entries)

    # Also export into the current process environment so it's live
    n_exported = 0
    for k, v in entries.items():
        os.environ[k] = v
        n_exported += 1
    print(f"  ✓ Exported {n_exported} keys into current process environment")

    print(f"\n  ✓ Done! SMTP backend: {entries.get('MAILER_BACKEND', 'auto')}")
    print()
    print("  Next steps:")
    print("    1. Restart the API server so the new env vars take effect")
    print("       or run: python -m apps.api.main")
    print()
    print("    2. Verify: python -m tests.test_magic_link  (all 13 must pass)")
    print()
    if entries.get("SMTP_HOST", "").endswith("example.com") or entries.get("SMTP_PASSWORD", "").startswith("your-"):
        print("  ⚠  Some values appear to be placeholders (e.g. smtp.example.com).")
        print("     Replace them with real SMTP credentials before testing delivery.")


if __name__ == "__main__":
    main()
