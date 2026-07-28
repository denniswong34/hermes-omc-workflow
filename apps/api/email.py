"""Email delivery abstraction — env-configurable SMTP/SES/console provider.

Usage:
    provider = get_email_provider()
    provider.send_email("alice@example.com", "Subject", "Body text")
"""

from __future__ import annotations

import logging
import os
import smtplib
import ssl
from abc import ABC, abstractmethod
from email.mime.text import MIMEText
from typing import Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Abstract provider
# ---------------------------------------------------------------------------


class EmailProvider(ABC):
    """Interface for sending emails."""

    @abstractmethod
    def send_email(self, to: str, subject: str, body_text: str) -> None:
        """Send a plain-text email. Raises on failure."""
        ...


# ---------------------------------------------------------------------------
# Console / log provider (dev mode)
# ---------------------------------------------------------------------------


class ConsoleEmailProvider(EmailProvider):
    """Logs the email to the application log instead of sending it."""

    def send_email(self, to: str, subject: str, body_text: str) -> None:
        logger.info(
            "[ConsoleEmailProvider] To: %s | Subject: %s\n%s",
            to,
            subject,
            body_text,
        )
        print(f"[EMAIL] To: {to} | Subject: {subject}")
        print(f"[EMAIL] Body:\n{body_text}")


# ---------------------------------------------------------------------------
# SMTP provider
# ---------------------------------------------------------------------------


class SmtpEmailProvider(EmailProvider):
    """Send email via an SMTP server (env-configurable)."""

    def __init__(
        self,
        host: str,
        port: int,
        username: str,
        password: str,
        from_addr: str,
        use_tls: bool = True,
    ) -> None:
        self.host = host
        self.port = port
        self.username = username
        self.password = password
        self.from_addr = from_addr
        self.use_tls = use_tls

    def send_email(self, to: str, subject: str, body_text: str) -> None:
        msg = MIMEText(body_text, "plain", "utf-8")
        msg["Subject"] = subject
        msg["From"] = self.from_addr
        msg["To"] = to

        context = ssl.create_default_context()

        try:
            with smtplib.SMTP(self.host, self.port, timeout=30) as server:
                if self.use_tls:
                    server.starttls(context=context)
                if self.username:
                    server.login(self.username, self.password)
                server.sendmail(self.from_addr, [to], msg.as_string())
        except smtplib.SMTPAuthenticationError:
            logger.error(
                "SMTP authentication failed — check SMTP_USERNAME / SMTP_PASSWORD "
                "(host=%s, user=%s, port=%s)",
                self.host, self.username, self.port,
            )
            raise
        except smtplib.SMTPConnectError as exc:
            logger.error(
                "SMTP connection failed — check SMTP_HOST / SMTP_PORT "
                "(host=%s, port=%s): %s",
                self.host, self.port, exc,
            )
            raise
        except (smtplib.SMTPServerDisconnected, OSError) as exc:
            logger.error(
                "SMTP send failed — connection lost (host=%s, port=%s): %s",
                self.host, self.port, exc,
            )
            raise
        except smtplib.SMTPException as exc:
            logger.error(
                "SMTP send failed (host=%s, to=%s, subject=%s): %s",
                self.host, to, subject, exc,
            )
            raise

        logger.info("Email sent via SMTP to %s (subject: %s)", to, subject)


# ---------------------------------------------------------------------------
# AWS SES provider (requires boto3)
# ---------------------------------------------------------------------------


class SesEmailProvider(EmailProvider):
    """Send email via Amazon SES using boto3.

    Falls back to ConsoleEmailProvider with a warning if boto3 is not installed.
    """

    def __init__(
        self,
        from_addr: str,
        region: str = "us-east-1",
        aws_access_key_id: Optional[str] = None,
        aws_secret_access_key: Optional[str] = None,
    ) -> None:
        self.from_addr = from_addr
        self.region = region
        self.aws_access_key_id = aws_access_key_id
        self.aws_secret_access_key = aws_secret_access_key
        self._client = None

    def _get_client(self):
        if self._client is not None:
            return self._client
        try:
            import boto3

            kwargs = {"region_name": self.region}
            if self.aws_access_key_id and self.aws_secret_access_key:
                kwargs["aws_access_key_id"] = self.aws_access_key_id
                kwargs["aws_secret_access_key"] = self.aws_secret_access_key
            self._client = boto3.client("ses", **kwargs)
            return self._client
        except ImportError:
            raise RuntimeError(
                "boto3 is not installed. Install with: pip install boto3"
            )
        except Exception as exc:
            raise RuntimeError(f"Failed to create SES client: {exc}") from exc

    def send_email(self, to: str, subject: str, body_text: str) -> None:
        client = self._get_client()
        client.send_email(
            Source=self.from_addr,
            Destination={"ToAddresses": [to]},
            Message={
                "Subject": {"Data": subject, "Charset": "UTF-8"},
                "Body": {"Text": {"Data": body_text, "Charset": "UTF-8"}},
            },
        )
        logger.info("Email sent via SES to %s (subject: %s)", to, subject)


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------


def get_email_provider() -> EmailProvider:
    """Build an EmailProvider from environment variables.

    The MAILER_BACKEND env var can be set to explicitly select a backend
    (``dev``, ``console``, ``smtp``, or ``ses``).  When unset (or set to
    ``auto``) the provider is auto-detected from which SMTP_* / AWS_SES_*
    variables are present, falling back to ConsoleEmailProvider.

    Because the call may be used in logging/response logic as well as
    sending, we keep a simple module-level cache so the same provider
    instance is reused within a process lifetime.
    """
    global _provider_cache
    if _provider_cache is not None:
        return _provider_cache

    backend = os.environ.get("MAILER_BACKEND", "").strip().lower()

    # ── Explicit backend selection ────────────────────────────────────
    if backend in ("dev", "console"):
        _provider_cache = ConsoleEmailProvider()
        return _provider_cache

    if backend == "smtp":
        host = os.environ.get("SMTP_HOST")
        if not host:
            raise RuntimeError(
                "MAILER_BACKEND=smtp but SMTP_HOST is not set"
            )
        _provider_cache = SmtpEmailProvider(
            host=host,
            port=int(os.environ.get("SMTP_PORT", "587")),
            username=os.environ.get("SMTP_USERNAME", "")
                      or os.environ.get("SMTP_USER", ""),
            password=os.environ.get("SMTP_PASSWORD", "")
                      or os.environ.get("SMTP_PASS", ""),
            from_addr=os.environ.get(
                "SMTP_FROM",
                os.environ.get("SMTP_USERNAME",
                               os.environ.get("SMTP_USER", "noreply@example.com")),
            ),
            use_tls=os.environ.get("SMTP_TLS", "1") == "1",
        )
        return _provider_cache

    if backend == "ses":
        ses_from = os.environ.get("AWS_SES_FROM") or os.environ.get("SES_FROM")
        if not ses_from:
            raise RuntimeError(
                "MAILER_BACKEND=ses but AWS_SES_FROM / SES_FROM is not set"
            )
        _provider_cache = SesEmailProvider(
            from_addr=ses_from,
            region=os.environ.get("AWS_SES_REGION", "us-east-1"),
            aws_access_key_id=os.environ.get("AWS_ACCESS_KEY_ID"),
            aws_secret_access_key=os.environ.get("AWS_SECRET_ACCESS_KEY"),
        )
        return _provider_cache

    # ── Auto-detect (backward-compatible) ─────────────────────────────
    ses_from = os.environ.get("AWS_SES_FROM") or os.environ.get("SES_FROM")
    smtp_host = os.environ.get("SMTP_HOST")

    if ses_from:
        _provider_cache = SesEmailProvider(
            from_addr=ses_from,
            region=os.environ.get("AWS_SES_REGION", "us-east-1"),
            aws_access_key_id=os.environ.get("AWS_ACCESS_KEY_ID"),
            aws_secret_access_key=os.environ.get("AWS_SECRET_ACCESS_KEY"),
        )
        return _provider_cache

    if smtp_host:
        _provider_cache = SmtpEmailProvider(
            host=smtp_host,
            port=int(os.environ.get("SMTP_PORT", "587")),
            username=os.environ.get("SMTP_USERNAME", "")
                      or os.environ.get("SMTP_USER", ""),
            password=os.environ.get("SMTP_PASSWORD", "")
                      or os.environ.get("SMTP_PASS", ""),
            from_addr=os.environ.get(
                "SMTP_FROM",
                os.environ.get("SMTP_USERNAME",
                               os.environ.get("SMTP_USER", "noreply@example.com")),
            ),
            use_tls=os.environ.get("SMTP_TLS", "1") == "1",
        )
        return _provider_cache

    # Fallback
    logger.warning(
        "No SMTP_* or AWS_SES_* env vars set and MAILER_BACKEND unset — "
        "using ConsoleEmailProvider (emails are logged, not delivered)"
    )
    _provider_cache = ConsoleEmailProvider()
    return _provider_cache


_provider_cache: Optional[EmailProvider] = None


# ---------------------------------------------------------------------------
# Startup logging
# ---------------------------------------------------------------------------


def log_active_provider() -> str:
    """Log which email provider is active at startup. Returns class name."""
    provider = get_email_provider()
    name = type(provider).__name__
    logger.info("Active email provider: %s", name)
    return name


# ---------------------------------------------------------------------------
# Magic-link convenience
# ---------------------------------------------------------------------------


def send_magic_link_email(to: str, token: str, ttl_minutes: int = 15) -> None:
    """Send a magic-link token to the given email address.

    Raises
    ------
    RuntimeError
        If the configured provider fails to send the email.
    """
    subject = "Your magic-link login code"
    body = (
        f"Hello,\n\n"
        f"Your one-time login code is:\n\n"
        f"    {token}\n\n"
        f"This code expires in {ttl_minutes} minutes.\n"
        f"Enter it on the login page to sign in.\n\n"
        f"If you did not request this code, please ignore this email.\n"
    )
    provider = get_email_provider()
    try:
        provider.send_email(to, subject, body)
    except Exception:
        logger.exception(
            "Failed to send magic-link email to %s via %s "
            "(host=%s, port=%s, from=%s)",
            to,
            type(provider).__name__,
            getattr(provider, "host", "n/a"),
            getattr(provider, "port", "n/a"),
            getattr(provider, "from_addr", "n/a"),
        )
        raise RuntimeError(
            f"Failed to send magic-link email to {to} "
            f"via {type(provider).__name__}"
        ) from None
