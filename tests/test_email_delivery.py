"""QA tests for HOAO-10 / TASK-002: email delivery layer.

Tests the email providers, factory, and auth-router integration.

Run: python -m tests.test_email_delivery
"""
from __future__ import annotations

import os
import re
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

tmp = tempfile.mkdtemp(prefix="omc-qa-email-")
os.environ["OMC_DB_PATH"] = str(Path(tmp) / "api.db")

# Clear any cached provider before tests
import apps.api.email as email_mod
email_mod._provider_cache = None

from fastapi.testclient import TestClient
from apps.api.main import app
from apps.api.email import (
    ConsoleEmailProvider,
    EmailProvider,
    SmtpEmailProvider,
    SesEmailProvider,
    get_email_provider,
    send_magic_link_email,
    log_active_provider,
)
from apps.api.auth import generate_magic_link_token

passed = 0
failed = 0

def check(label: str, condition: bool, detail: str = ""):
    global passed, failed
    if condition:
        print(f"  ✓ {label}")
        passed += 1
    else:
        print(f"  ✗ {label}  {detail}")
        failed += 1

# =========================================================================
# 1. Provider interface & ConsoleEmailProvider
# =========================================================================
print("\n── 1. Abstract interface & ConsoleEmailProvider ──")

check(
    "EmailProvider is abstract (has abstractmethod)",
    EmailProvider.send_email.__isabstractmethod__,
)

cp = ConsoleEmailProvider()
check("ConsoleEmailProvider.send_email returns None", cp.send_email("a@b.com", "S", "B") is None)

# =========================================================================
# 2. get_email_provider() factory
# =========================================================================
print("\n── 2. get_email_provider() factory ──")

# 2a. No env vars → ConsoleEmailProvider
email_mod._provider_cache = None
orig_environ = dict(os.environ)
for k in list(os.environ):
    if k.startswith("SMTP_") or k.startswith("AWS_SES_") or k.startswith("SES_") or k == "MAILER_BACKEND":
        del os.environ[k]
p = get_email_provider()
check("Fallback (no env) → ConsoleEmailProvider", isinstance(p, ConsoleEmailProvider))

# 2b. MAILER_BACKEND=console → ConsoleEmailProvider
os.environ["MAILER_BACKEND"] = "console"
email_mod._provider_cache = None
p = get_email_provider()
check("MAILER_BACKEND=console → ConsoleEmailProvider", isinstance(p, ConsoleEmailProvider))

# 2c. MAILER_BACKEND=smtp without SMTP_HOST → RuntimeError
os.environ["MAILER_BACKEND"] = "smtp"
if "SMTP_HOST" in os.environ:
    del os.environ["SMTP_HOST"]
email_mod._provider_cache = None
try:
    get_email_provider()
    check("MAILER_BACKEND=smtp without SMTP_HOST → raises", False, "should have raised")
except RuntimeError:
    check("MAILER_BACKEND=smtp without SMTP_HOST → RuntimeError", True)

# 2d. MAILER_BACKEND=smtp with SMTP_HOST → SmtpEmailProvider
os.environ["MAILER_BACKEND"] = "smtp"
os.environ["SMTP_HOST"] = "smtp.example.com"
os.environ["SMTP_PORT"] = "587"
os.environ["SMTP_USERNAME"] = "bot@example.com"
os.environ["SMTP_PASSWORD"] = "s3cret"
email_mod._provider_cache = None
p = get_email_provider()
check("MAILER_BACKEND=smtp + SMTP_HOST → SmtpEmailProvider", isinstance(p, SmtpEmailProvider))
check("SmtpEmailProvider.host == smtp.example.com", p.host == "smtp.example.com")
check("SmtpEmailProvider.port == 587", p.port == 587)
check("SmtpEmailProvider.from_addr == bot@example.com", p.from_addr == "bot@example.com")
check("SmtpEmailProvider.use_tls == True", p.use_tls is True)

# 2e. Auto-detect from SMTP_* vars
os.environ.pop("MAILER_BACKEND", None)
os.environ["SMTP_HOST"] = "mail.example.com"
os.environ["SMTP_USERNAME"] = "auto@example.com"
os.environ["SMTP_PASSWORD"] = "autopass"
email_mod._provider_cache = None
p = get_email_provider()
check("Auto-detect from SMTP_HOST → SmtpEmailProvider", isinstance(p, SmtpEmailProvider))
check("Auto-detect host == mail.example.com", p.host == "mail.example.com")

# 2f. Caching — second call returns same instance
p2 = get_email_provider()
check("Provider is cached (same instance)", p is p2)

# =========================================================================
# 3. SmtpEmailProvider — MIME construction (no real SMTP)
# =========================================================================
print("\n── 3. SmtpEmailProvider — MIME construction ──")

smtp = SmtpEmailProvider(
    host="smtp.test.com",
    port=587,
    username="test@test.com",
    password="pass",
    from_addr="from@test.com",
    use_tls=True,
)

# Patch smtplib to capture the MIME without connecting
with patch("smtplib.SMTP") as mock_smtp:
    mock_instance = MagicMock()
    mock_smtp.return_value.__enter__.return_value = mock_instance
    smtp.send_email("to@test.com", "Hello", "Body text")

    mock_smtp.assert_called_once()
    args, kwargs = mock_smtp.call_args
    check("SMTP called with correct host:port", args == ("smtp.test.com", 587))

    # Check starttls was called
    check("starttls() was called", mock_instance.starttls.called)

    # Check login was called
    check("login() was called with correct creds",
          mock_instance.login.call_args[0] == ("test@test.com", "pass"))

    # Check sendmail was called
    check("sendmail() was called", mock_instance.sendmail.called)
    sendmail_args = mock_instance.sendmail.call_args[0]
    check("sendmail from=from@test.com", sendmail_args[0] == "from@test.com")
    check("sendmail to=to@test.com", sendmail_args[1] == ["to@test.com"])

    # Check MIME content (MIMEText may base64/quoted-printable encode the body)
    raw_msg = sendmail_args[2]
    check("MIME contains Subject: Hello", "Subject: Hello" in raw_msg)
    check("MIME contains To: to@test.com", "To: to@test.com" in raw_msg)
    check("MIME contains From: from@test.com", "From: from@test.com" in raw_msg)
    check("MIME contains text/plain content-type", "text/plain" in raw_msg)

# 3b. SMTP error handling — authentication failure
with patch("smtplib.SMTP") as mock_smtp:
    import smtplib
    mock_instance = MagicMock()
    mock_smtp.return_value.__enter__.return_value = mock_instance
    mock_instance.login.side_effect = smtplib.SMTPAuthenticationError(535, b"Auth failed")
    try:
        smtp.send_email("to@test.com", "S", "B")
        check("SMTP auth failure → should raise", False, "no exception")
    except smtplib.SMTPAuthenticationError:
        check("SMTP auth failure → SMTPAuthenticationError propagated", True)

# 3c. SMTP connect error
with patch("smtplib.SMTP") as mock_smtp:
    mock_smtp.side_effect = smtplib.SMTPConnectError(421, b"Service unavailable")
    try:
        smtp.send_email("to@test.com", "S", "B")
        check("SMTP connect failure → should raise", False, "no exception")
    except smtplib.SMTPConnectError:
        check("SMTP connect failure → SMTPConnectError propagated", True)

# =========================================================================
# 4. SES provider — error handling
# =========================================================================
print("\n── 4. SES provider — missing boto3 ──")

# Simulate boto3 not being installed by patching _get_client
import apps.api.email as email_mod_2
original_get_client = email_mod_2.SesEmailProvider._get_client

def _fake_get_client_no_boto3(self):
    raise RuntimeError("boto3 is not installed. Install with: pip install boto3")

email_mod_2.SesEmailProvider._get_client = _fake_get_client_no_boto3

ses = SesEmailProvider(from_addr="ses@test.com", region="us-east-1")
try:
    ses.send_email("to@test.com", "S", "B")
    check("SES without boto3 → should raise", False, "no exception")
except RuntimeError as e:
    check("SES without boto3 → RuntimeError with hint", "boto3 is not installed" in str(e))

email_mod_2.SesEmailProvider._get_client = original_get_client

# =========================================================================
# 5. send_magic_link_email()
# =========================================================================
print("\n── 5. send_magic_link_email() — content ──")

email_mod._provider_cache = None
os.environ["MAILER_BACKEND"] = "console"

with patch.object(ConsoleEmailProvider, "send_email") as mock_send:
    send_magic_link_email("alice@example.com", "ABC123", ttl_minutes=15)
    args, kwargs = mock_send.call_args
    to, subject, body = args
    check("send_magic_link_email to=alice@example.com", to == "alice@example.com")
    check("Subject is 'Your magic-link login code'", subject == "Your magic-link login code")
    check("Body contains the token ABC123", "ABC123" in body)
    check("Body mentions 15 minutes", "15 minutes" in body)
    check("Body has login-code format", re.search(r"one-time login code", body) is not None)

# 5b. send_magic_link_email failure → RuntimeError
with patch.object(ConsoleEmailProvider, "send_email", side_effect=Exception("Boom")):
    try:
        send_magic_link_email("fail@test.com", "XXX", ttl_minutes=15)
        check("Send failure → should raise", False, "no exception")
    except RuntimeError as e:
        check("Send failure → RuntimeError with context", "fail@test.com" in str(e))

# =========================================================================
# 6. log_active_provider()
# =========================================================================
print("\n── 6. log_active_provider() ──")

os.environ["MAILER_BACKEND"] = "console"
email_mod._provider_cache = None
name = log_active_provider()
check("log_active_provider returns 'ConsoleEmailProvider'", name == "ConsoleEmailProvider")

# =========================================================================
# 7. Auth-router integration — DEV_MODE token visibility
# =========================================================================
print("\n── 7. Auth-router integration ──")

c = TestClient(app)

# 7a. ConsoleEmailProvider → token visible in response
os.environ["MAILER_BACKEND"] = "console"
email_mod._provider_cache = None

r = c.post("/api/auth/magic-link", json={"email": "qa@test.com"})
check("DEV: POST magic-link returns 200", r.status_code == 200, str(r.status_code))
data = r.json()
check("DEV: ok is True", data.get("ok") is True)
check("DEV: token is returned (dev mode)", "token" in data, str(data.keys()))
if "token" in data:
    check("DEV: token is 6 chars", len(data["token"]) == 6, data["token"])
check("DEV: ttl_seconds is 900", data.get("ttl_seconds") == 900)

# 7b. Production (SMTP configured) → token hidden
os.environ["MAILER_BACKEND"] = "smtp"
os.environ["SMTP_HOST"] = "mailhog.example.com"
os.environ["SMTP_PORT"] = "1025"
os.environ["SMTP_USERNAME"] = "test"
os.environ["SMTP_PASSWORD"] = "test"
os.environ["SMTP_FROM"] = "noreply@test.com"
email_mod._provider_cache = None

# Mock SMTP to avoid actual connection
with patch("smtplib.SMTP") as mock_smtp:
    mock_instance = MagicMock()
    mock_smtp.return_value.__enter__.return_value = mock_instance
    r = c.post("/api/auth/magic-link", json={"email": "prod@test.com"})
    check("PROD: POST magic-link returns 200", r.status_code == 200, str(r.status_code))
    data = r.json()
    check("PROD: ok is True", data.get("ok") is True)
    check("PROD: token is NOT returned", "token" not in data,
          f"unexpected token: {data.get('token')}")
    check("PROD: generic message (non-enumerating)", "If the email exists" in data.get("message", ""))

# 7c. SMTP failure → 500
with patch("smtplib.SMTP") as mock_smtp:
    mock_smtp.side_effect = ConnectionRefusedError("Connection refused")
    r = c.post("/api/auth/magic-link", json={"email": "fail@test.com"})
    check("PROD: SMTP connection failure → 500", r.status_code == 500, str(r.status_code))

# 7d. Existing /api/auth/login still works
r = c.post("/api/auth/login", json={"email": "admin@example.com", "password": "secret"})
check("Existing login works", r.status_code == 200 and r.json().get("ok") is True)

# =========================================================================
# 8. setup_mailer.py — non-interactive mode
# =========================================================================
print("\n── 8. setup_mailer.py (non-interactive) ──")

import subprocess
import sys

script = Path(__file__).resolve().parents[1] / "scripts" / "setup_mailer.py"
if script.exists():
    env = os.environ.copy()
    env["SMTP_HOST"] = "smtp.test.com"
    env["SMTP_PORT"] = "587"
    env["SMTP_USERNAME"] = "noreply@test.com"
    env["SMTP_PASSWORD"] = "testpass"
    env["SMTP_FROM"] = "noreply@test.com"
    result = subprocess.run(
        [sys.executable, str(script), "--non-interactive", "--print"],
        capture_output=True, text=True, env=env, cwd=script.parents[1],
    )
    check("setup_mailer.py --non-interactive --print exits 0",
          result.returncode == 0, f"exit {result.returncode}: {result.stderr[:200]}")
    check("setup_mailer output mentions SMTP", "SMTP" in result.stdout or "smtp" in result.stdout,
          result.stdout[:300])
else:
    check("setup_mailer.py exists", False, f"not found at {script}")

# =========================================================================
# Summary
# =========================================================================
print(f"\n{'='*50}")
print(f"  Results:  {passed} passed,  {failed} failed")
print(f"{'='*50}")

# Restore env
os.environ.clear()
os.environ.update(orig_environ)

if failed:
    exit(1)
