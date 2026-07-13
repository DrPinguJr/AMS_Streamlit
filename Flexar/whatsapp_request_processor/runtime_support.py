"""Safe, testable helpers shared by the local AMS process supervisor and UI."""

from __future__ import annotations

import json
import os
from pathlib import Path
import re
import tempfile
from typing import Any, Iterable


PACKAGE_DIR = Path(__file__).resolve().parent
REPO_ROOT = PACKAGE_DIR.parents[1]
RUNTIME_DIR = PACKAGE_DIR / "runtime"
PROCESS_FILE = RUNTIME_DIR / "ams_processes.json"
STATUS_FILE = RUNTIME_DIR / "system_status.json"
SHUTDOWN_FILE = RUNTIME_DIR / "shutdown.request"


def repository_root_from_launcher(launcher: str | Path) -> Path:
    """Resolve the repository root from a root batch file or nested script path."""

    path = Path(launcher).resolve()
    for candidate in [path.parent, *path.parents]:
        if (candidate / "Flexar" / "whatsapp_request_processor" / "api.py").is_file() and (candidate / "app.py").is_file():
            return candidate
    raise ValueError(f"Could not locate the AMS repository from {path}")


def python_candidates(repo_root: str | Path, configured: str | None = None) -> list[Path]:
    root = Path(repo_root).resolve()
    candidates: list[Path] = []
    active_venv = os.getenv("VIRTUAL_ENV")
    for value in [active_venv, str(root / ".venv"), str(root / "venv")]:
        if value:
            candidates.append(Path(value) / "Scripts" / "python.exe")
    if configured:
        candidates.append(Path(configured))
    seen: set[str] = set()
    return [item for item in candidates if not (str(item).lower() in seen or seen.add(str(item).lower()))]


def atomic_write_json(path: str | Path, payload: dict[str, Any]) -> None:
    """Replace a JSON file atomically so readers never see a partial document."""

    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    handle, temp_name = tempfile.mkstemp(prefix=f".{target.name}.", suffix=".tmp", dir=str(target.parent))
    try:
        with os.fdopen(handle, "w", encoding="utf-8", newline="\n") as stream:
            json.dump(payload, stream, indent=2, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp_name, target)
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)


def load_json_file(path: str | Path) -> dict[str, Any]:
    try:
        with Path(path).open("r", encoding="utf-8") as stream:
            value = json.load(stream)
        return value if isinstance(value, dict) else {}
    except (OSError, json.JSONDecodeError, TypeError):
        return {}


def read_system_status(path: str | Path = STATUS_FILE) -> dict[str, Any]:
    return load_json_file(path)


def select_https_tunnel(payload: dict[str, Any], local_port: int = 8000) -> dict[str, Any] | None:
    """Choose the HTTPS ngrok tunnel that forwards to the required local port."""

    for tunnel in payload.get("tunnels", []):
        if not isinstance(tunnel, dict) or not str(tunnel.get("public_url", "")).startswith("https://"):
            continue
        address = str((tunnel.get("config") or {}).get("addr") or "")
        if re.search(rf"(?:^|:){local_port}(?:/|$)", address):
            return tunnel
    return None


_SECRET_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"(?i)(authorization\s*[:=]\s*bearer\s+)[^\s,;]+"), r"\1[REDACTED]"),
    (re.compile(r"(?i)((?:token|secret|password|api[_-]?key)\s*[:=]\s*)[^\s,;]+"), r"\1[REDACTED]"),
    (re.compile(r"(?<!\d)(\d{2})\d{4,8}(\d{2})(?!\d)"), r"\1****\2"),
)


def redact_sensitive(value: object) -> str:
    output = str(value)
    for pattern, replacement in _SECRET_PATTERNS:
        output = pattern.sub(replacement, output)
    return output


def command_matches(command_line: str | None, required_markers: Iterable[str]) -> bool:
    command = (command_line or "").lower()
    markers = [marker.lower() for marker in required_markers]
    return bool(command) and all(marker in command for marker in markers)


def safe_runtime_status(
    *,
    session_started_at: str,
    log_directory: str,
    fastapi: dict[str, Any] | None = None,
    worker: dict[str, Any] | None = None,
    database: dict[str, Any] | None = None,
    ngrok: dict[str, Any] | None = None,
    streamlit: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build the non-secret runtime document consumed by Streamlit."""

    return {
        "session_started_at": session_started_at,
        "last_health_check": None,
        "fastapi": fastapi or {"status": "offline", "url": "http://127.0.0.1:8000"},
        "worker": worker or {"status": "offline"},
        "database": database or {"status": "offline"},
        "ngrok": ngrok or {"status": "offline", "public_url": None},
        "streamlit": streamlit or {"status": "offline", "url": "http://127.0.0.1:8501"},
        "waapi": {
            "status": "disabled",
            "outbound_enabled": False,
            "rider_reply_enabled": False,
            "ops_update_enabled": False,
        },
        "simulation_mode": True,
        "live_sending": False,
        "log_directory": log_directory,
    }
