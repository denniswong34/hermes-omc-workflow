"""Manage the multi-workflow bridge process (start / stop / restart / status)."""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Optional

from core.db import REPO_ROOT

PID_FILE = Path(
    os.environ.get("OMC_BRIDGE_PID_FILE", "~/.hermes/omc/bridge.pid")
).expanduser()
LOG_FILE = Path(
    os.environ.get("OMC_BRIDGE_LOG", str(REPO_ROOT / "bridge.log"))
).expanduser()


def _pid_running(pid: int) -> bool:
    if pid <= 0:
        return False
    if sys.platform == "win32":
        try:
            out = subprocess.check_output(
                ["tasklist", "/FI", f"PID eq {pid}", "/NH"],
                text=True,
                stderr=subprocess.DEVNULL,
            )
            return str(pid) in out and "No tasks" not in out
        except Exception:
            return False
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def _read_pid() -> Optional[int]:
    if not PID_FILE.exists():
        return None
    try:
        pid = int(PID_FILE.read_text(encoding="utf-8").strip())
        return pid
    except Exception:
        return None


def _write_pid(pid: int) -> None:
    PID_FILE.parent.mkdir(parents=True, exist_ok=True)
    PID_FILE.write_text(str(pid), encoding="utf-8")


def _clear_pid() -> None:
    try:
        if PID_FILE.exists():
            PID_FILE.unlink()
    except Exception:
        pass


def bridge_status() -> dict[str, Any]:
    pid = _read_pid()
    running = bool(pid and _pid_running(pid))
    if pid and not running:
        _clear_pid()
        pid = None
    return {
        "running": running,
        "pid": pid,
        "mode": "bridge_multi",
        "pid_file": str(PID_FILE),
        "log_file": str(LOG_FILE),
        "message": "Bridge is running" if running else "Bridge is stopped",
    }


def stop_bridge(timeout_sec: float = 8.0) -> dict[str, Any]:
    status = bridge_status()
    pid = status.get("pid")
    if not status.get("running") or not pid:
        _clear_pid()
        return {"ok": True, "stopped": False, "message": "Bridge was not running"}

    try:
        if sys.platform == "win32":
            subprocess.run(
                ["taskkill", "/PID", str(pid), "/T", "/F"],
                capture_output=True,
                text=True,
                check=False,
            )
        else:
            os.kill(pid, signal.SIGTERM)
            deadline = time.time() + timeout_sec
            while time.time() < deadline and _pid_running(pid):
                time.sleep(0.2)
            if _pid_running(pid):
                os.kill(pid, signal.SIGKILL)
    except Exception as e:
        return {"ok": False, "stopped": False, "message": str(e), "pid": pid}

    # Wait briefly for death
    deadline = time.time() + timeout_sec
    while time.time() < deadline and _pid_running(pid):
        time.sleep(0.15)
    alive = _pid_running(pid)
    if not alive:
        _clear_pid()
    return {
        "ok": not alive,
        "stopped": not alive,
        "pid": pid,
        "message": "Bridge stopped" if not alive else "Bridge still running after kill",
    }


def _bridge_python() -> str:
    """Prefer a Python that can import discord (Hermes venv), else current interpreter."""
    override = (os.environ.get("OMC_BRIDGE_PYTHON") or "").strip()
    if override and Path(override).exists():
        return override
    candidates = [
        Path.home() / "AppData/Local/hermes/hermes-agent/venv/Scripts/python.exe",
        Path.home() / ".local/share/hermes/venv/bin/python",
        Path("/opt/hermes/venv/bin/python"),
    ]
    for c in candidates:
        if c.exists():
            return str(c)
    return sys.executable


def start_bridge() -> dict[str, Any]:
    current = bridge_status()
    if current.get("running"):
        return {
            "ok": True,
            "started": False,
            "pid": current.get("pid"),
            "message": "Bridge already running",
        }

    try:
        from core.db import get_db
        from core.secrets import load_workflow_secrets_into_environ
        from core.workflow.repository import WorkflowRepository

        repo = WorkflowRepository(get_db())
        for wf in repo.list_active():
            load_workflow_secrets_into_environ(wf.id)
    except Exception:
        pass

    env = os.environ.copy()
    env["PYTHONPATH"] = str(REPO_ROOT) + os.pathsep + env.get("PYTHONPATH", "")
    env["OMC_MULTI_WORKFLOW"] = "1"
    env.setdefault("PYTHONIOENCODING", "utf-8")

    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    log_f = open(LOG_FILE, "a", encoding="utf-8")

    creationflags = 0
    if sys.platform == "win32":
        creationflags = subprocess.CREATE_NEW_PROCESS_GROUP  # type: ignore[attr-defined]

    py = _bridge_python()
    try:
        proc = subprocess.Popen(
            [py, str(REPO_ROOT / "bridge_multi.py")],
            cwd=str(REPO_ROOT),
            env=env,
            stdout=log_f,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            creationflags=creationflags,
            close_fds=sys.platform != "win32",
        )
    except Exception as e:
        log_f.close()
        return {"ok": False, "started": False, "message": str(e)}

    _write_pid(proc.pid)
    time.sleep(2.5)
    if not _pid_running(proc.pid):
        _clear_pid()
        return {
            "ok": False,
            "started": False,
            "pid": proc.pid,
            "python": py,
            "message": "Bridge exited immediately — check bridge.log",
        }
    return {
        "ok": True,
        "started": True,
        "pid": proc.pid,
        "python": py,
        "message": f"Bridge started (pid {proc.pid})",
    }


def restart_bridge() -> dict[str, Any]:
    stop = stop_bridge()
    time.sleep(0.5)
    start = start_bridge()
    return {
        "ok": bool(start.get("ok")),
        "stop": stop,
        "start": start,
        "status": bridge_status(),
        "message": start.get("message") or stop.get("message") or "Restart finished",
    }
