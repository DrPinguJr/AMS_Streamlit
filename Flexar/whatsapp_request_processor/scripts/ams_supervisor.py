"""Single-console local process supervisor for the AMS WhatsApp simulator."""

from __future__ import annotations

import argparse
import ctypes
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import queue
import shutil
import signal
import subprocess
import sys
import threading
import time
from typing import Any, TextIO
from urllib.error import URLError
from urllib.request import Request, urlopen
import webbrowser


REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from Flexar.whatsapp_request_processor.runtime_support import (  # noqa: E402
    PROCESS_FILE,
    RUNTIME_DIR,
    SHUTDOWN_FILE,
    STATUS_FILE,
    atomic_write_json,
    command_matches,
    load_json_file,
    redact_sensitive,
    safe_runtime_status,
    select_https_tunnel,
)


PACKAGE_DIR = REPO_ROOT / "Flexar" / "whatsapp_request_processor"
LOGS_DIR = PACKAGE_DIR / "logs"
API_URL = "http://127.0.0.1:8000"
STREAMLIT_URL = "http://127.0.0.1:8501"
NGROK_API_URL = "http://127.0.0.1:4040/api/tunnels"
DASHBOARD_URL = f"{STREAMLIT_URL}/whatsapp-request-processor"
CREATE_FLAGS = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def pid_alive(pid: int | None) -> bool:
    if not pid or pid <= 0:
        return False
    if os.name == "nt":
        # os.kill(pid, 0) is not a safe probe on Windows: non-console signals
        # map to TerminateProcess. Query the process handle without mutating it.
        process_query_limited_information = 0x1000
        still_active = 259
        handle = ctypes.windll.kernel32.OpenProcess(process_query_limited_information, False, int(pid))
        if not handle:
            return False
        try:
            exit_code = ctypes.c_ulong()
            if not ctypes.windll.kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
                return False
            return exit_code.value == still_active
        finally:
            ctypes.windll.kernel32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
        return True
    except (OSError, ProcessLookupError, PermissionError):
        return False


def _hidden_startup_info() -> subprocess.STARTUPINFO | None:
    if os.name != "nt":
        return None
    info = subprocess.STARTUPINFO()
    info.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    info.wShowWindow = 0
    return info


def powershell_value(script: str) -> str:
    try:
        result = subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
            capture_output=True,
            text=True,
            timeout=5,
            startupinfo=_hidden_startup_info(),
            check=False,
        )
        return result.stdout.strip().splitlines()[0] if result.stdout.strip() else ""
    except (OSError, subprocess.SubprocessError):
        return ""


def process_command_line(pid: int | None) -> str:
    if not pid:
        return ""
    return powershell_value(
        f"$p=Get-CimInstance Win32_Process -Filter \"ProcessId={int(pid)}\" -ErrorAction SilentlyContinue; if($p){{$p.CommandLine}}"
    )


def port_owner_pid(port: int) -> int | None:
    value = powershell_value(
        f"$p=Get-NetTCPConnection -LocalPort {int(port)} -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1 -ExpandProperty OwningProcess; if($p){{$p}}"
    )
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def http_json(url: str, timeout: float = 1.5) -> dict[str, Any]:
    request = Request(url, headers={"User-Agent": "AMS-Local-Supervisor/1.0"})
    with urlopen(request, timeout=timeout) as response:  # noqa: S310 - localhost URLs only
        value = json.loads(response.read().decode("utf-8"))
    return value if isinstance(value, dict) else {}


def http_text(url: str, timeout: float = 1.5) -> str:
    request = Request(url, headers={"User-Agent": "AMS-Local-Supervisor/1.0"})
    with urlopen(request, timeout=timeout) as response:  # noqa: S310 - localhost URLs only
        return response.read().decode("utf-8", errors="replace")


def find_ngrok() -> Path | None:
    configured = os.getenv("AMS_NGROK_PATH") or os.getenv("NGROK_PATH")
    candidates = [
        Path(configured) if configured else None,
        Path(shutil.which("ngrok") or "") if shutil.which("ngrok") else None,
        REPO_ROOT / "tools" / "ngrok.exe",
        Path(os.getenv("LOCALAPPDATA", "")) / "Microsoft" / "WinGet" / "Links" / "ngrok.exe",
        Path(os.getenv("USERPROFILE", "")) / "AppData" / "Local" / "ngrok" / "ngrok.exe",
    ]
    return next((candidate.resolve() for candidate in candidates if candidate and candidate.is_file()), None)


class ConsoleLog:
    COLOURS = {
        "SYSTEM": "\033[96m",
        "API": "\033[94m",
        "WORKER": "\033[95m",
        "STREAMLIT": "\033[92m",
        "NGROK": "\033[93m",
        "DATABASE": "\033[36m",
        "WARNING": "\033[33m",
        "ERROR": "\033[91m",
    }

    def __init__(self, log_dir: Path) -> None:
        self.log_dir = log_dir
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.lock = threading.Lock()
        self.handles: dict[str, TextIO] = {
            name: (self.log_dir / filename).open("a", encoding="utf-8", buffering=1)
            for name, filename in {
                "SYSTEM": "supervisor.log",
                "API": "fastapi.log",
                "WORKER": "fastapi.log",
                "DATABASE": "fastapi.log",
                "STREAMLIT": "streamlit.log",
                "NGROK": "ngrok.log",
                "WARNING": "errors.log",
                "ERROR": "errors.log",
            }.items()
        }
        self.colour = sys.stdout.isatty() and os.getenv("NO_COLOR") is None

    def close(self) -> None:
        seen: set[int] = set()
        for handle in self.handles.values():
            if id(handle) not in seen:
                seen.add(id(handle))
                handle.close()

    def write(self, component: str, message: object, terminal: bool = True) -> None:
        component = component if component in self.handles else "SYSTEM"
        clean = redact_sensitive(message).strip()
        if not clean:
            return
        stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        line = f"{stamp} [{component}] {clean}"
        with self.lock:
            self.handles[component].write(line + "\n")
            if terminal:
                prefix = f"[{component}]"
                if self.colour:
                    prefix = f"{self.COLOURS.get(component, '')}{prefix}\033[0m"
                print(f"{prefix} {clean}", flush=True)


class Supervisor:
    def __init__(self, python: Path) -> None:
        self.python = python.resolve()
        self.started_at = utc_now()
        session_name = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        self.log_dir = LOGS_DIR / session_name
        self.log = ConsoleLog(self.log_dir)
        self.children: dict[str, subprocess.Popen[str]] = {}
        self.processes: dict[str, dict[str, Any]] = {}
        self.status = safe_runtime_status(session_started_at=self.started_at, log_directory=str(self.log_dir))
        self.stop_event = threading.Event()
        self.exit_queue: queue.Queue[tuple[str, int]] = queue.Queue()
        self.ngrok_path: Path | None = None
        self.ngrok_last_online = False

    def write_status(self) -> None:
        self.status["last_health_check"] = utc_now()
        atomic_write_json(STATUS_FILE, self.status)

    def write_process_file(self) -> None:
        atomic_write_json(
            PROCESS_FILE,
            {
                "session_started_at": self.started_at,
                "supervisor": {
                    "pid": os.getpid(),
                    "markers": ["ams_supervisor.py"],
                },
                "processes": self.processes,
                "log_directory": str(self.log_dir),
            },
        )

    def validate(self) -> bool:
        self.log.write("SYSTEM", f"Repository: {REPO_ROOT}")
        self.log.write("SYSTEM", f"Python: {self.python}")
        required_files = [REPO_ROOT / "app.py", PACKAGE_DIR / "api.py", PACKAGE_DIR / "worker.py"]
        for path in required_files:
            if not path.is_file():
                self.log.write("ERROR", f"Required application file was not found: {path}")
                return False
        try:
            test_file = self.log_dir / ".write-test"
            test_file.write_text("ok", encoding="utf-8")
            test_file.unlink()
        except OSError:
            self.log.write("ERROR", f"The log directory is not writable: {self.log_dir}")
            return False
        result = subprocess.run(
            [str(self.python), "-c", "import fastapi,httpx,streamlit,uvicorn,dotenv,pandas"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=20,
            startupinfo=_hidden_startup_info(),
            check=False,
        )
        if result.returncode:
            self.log.write("ERROR", "Required Python packages are missing. Please contact the system administrator to update the project environment.")
            self.log.write("ERROR", result.stderr or result.stdout, terminal=False)
            return False
        self.ngrok_path = find_ngrok()
        if not self.ngrok_path:
            self.log.write("ERROR", "ngrok was not found. Please contact the system administrator for the one-time ngrok setup.")
            self.log.write("WARNING", "FastAPI and Streamlit will remain available locally. WAAPI remains disabled.")
        else:
            self.log.write("SYSTEM", f"ngrok: {self.ngrok_path}")
        return True

    def _component_for_line(self, default: str, line: str) -> tuple[str, str]:
        for component in ["WORKER", "DATABASE", "API", "STREAMLIT", "NGROK"]:
            marker = f"AMS_COMPONENT={component}"
            if marker in line:
                return component, line.replace(marker, "").strip()
        lowered = line.lower()
        if "error" in lowered or "traceback" in lowered:
            return "ERROR", f"{default}: {line}"
        return default, line

    def _relay(self, name: str, process: subprocess.Popen[str]) -> None:
        assert process.stdout is not None
        for line in process.stdout:
            component, clean = self._component_for_line(name, line.rstrip())
            noisy = name == "STREAMLIT" and any(value in clean for value in ["You can now view", "Network URL", "External URL"])
            self.log.write(component, clean, terminal=not noisy)
        code = process.wait()
        self.exit_queue.put((name, code))

    def start_child(self, name: str, command: list[str], markers: list[str], env: dict[str, str]) -> subprocess.Popen[str]:
        process = subprocess.Popen(
            command,
            cwd=REPO_ROOT,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            creationflags=CREATE_FLAGS,
            startupinfo=_hidden_startup_info(),
        )
        self.children[name] = process
        self.processes[name.lower()] = {"pid": process.pid, "markers": markers, "command": command}
        self.write_process_file()
        threading.Thread(target=self._relay, args=(name, process), daemon=True).start()
        self.log.write(name, f"Process started. PID: {process.pid}")
        return process

    def safe_environment(self) -> dict[str, str]:
        env = os.environ.copy()
        env.update(
            {
                "PYTHONUNBUFFERED": "1",
                "SIMULATION_MODE": "true",
                "WAAPI_ENABLED": "false",
                "WAAPI_OUTBOUND_ENABLED": "false",
                "WAAPI_RIDER_REPLY_ENABLED": "false",
                "WAAPI_OPS_UPDATE_ENABLED": "false",
            }
        )
        return env

    def poll_api(self, attempts: int = 20) -> dict[str, Any] | None:
        for attempt in range(1, attempts + 1):
            self.log.write("SYSTEM", f"FastAPI health attempt {attempt}/{attempts}...")
            try:
                health = http_json(f"{API_URL}/health")
                if health.get("status") == "ok" and health.get("service") == "ams-whatsapp-request-processor":
                    return health
            except (OSError, URLError, ValueError, json.JSONDecodeError):
                pass
            time.sleep(0.5)
        return None

    def start_api(self, env: dict[str, str]) -> bool:
        owner = port_owner_pid(8000)
        if owner:
            command = process_command_line(owner)
            try:
                health = http_json(f"{API_URL}/health")
            except Exception:
                health = {}
            if health.get("service") != "ams-whatsapp-request-processor" or not command_matches(command, ["uvicorn", "Flexar.whatsapp_request_processor.api:app"]):
                self.log.write("ERROR", f"Port 8000 is already used by another program (PID {owner}). It was not stopped.")
                return False
            if health.get("simulation_mode") is not True or health.get("waapi", {}).get("status") != "disabled" or health.get("waapi", {}).get("outbound_enabled"):
                self.log.write("ERROR", "An existing AMS FastAPI process is not in the required safe simulation-only mode. It was not reused or stopped.")
                return False
            self.processes["api"] = {"pid": owner, "markers": ["uvicorn", "Flexar.whatsapp_request_processor.api:app"], "reused": True}
            self.write_process_file()
            self.log.write("API", f"Reusing existing AMS FastAPI process. PID: {owner}")
        else:
            self.log.write("SYSTEM", "Starting FastAPI...")
            self.start_child(
                "API",
                [str(self.python), "-m", "uvicorn", "Flexar.whatsapp_request_processor.api:app", "--host", "127.0.0.1", "--port", "8000", "--log-level", "info"],
                ["uvicorn", "Flexar.whatsapp_request_processor.api:app"],
                env,
            )
        self.log.write("SYSTEM", "Waiting for FastAPI health check...")
        health = self.poll_api()
        if not health:
            self.log.write("ERROR", f"FastAPI could not start. See: {self.log_dir / 'fastapi.log'}")
            return False
        worker_online = health.get("worker", {}).get("status") == "online"
        database_online = bool(health.get("database", {}).get("ok"))
        if not worker_online:
            self.log.write("ERROR", "FastAPI responded, but its background request worker is offline.")
            return False
        self.status["fastapi"] = {"status": "online", "pid": self.processes["api"]["pid"], "url": API_URL}
        self.status["worker"] = {"status": "online"}
        self.status["database"] = {"status": "online" if database_online else "offline"}
        self.write_status()
        self.log.write("SYSTEM", "FastAPI is ONLINE.")
        self.log.write("WORKER", "Background request worker is ONLINE.")
        self.log.write("DATABASE", "Database is ONLINE." if database_online else "Database health check failed.")
        return database_online

    def poll_ngrok(self, attempts: int = 20) -> dict[str, Any] | None:
        for attempt in range(1, attempts + 1):
            try:
                tunnel = select_https_tunnel(http_json(NGROK_API_URL), 8000)
                if tunnel:
                    return tunnel
            except Exception:
                pass
            if attempt in {1, 5, 10, 15, 20}:
                self.log.write("SYSTEM", f"ngrok tunnel attempt {attempt}/{attempts}...")
            time.sleep(0.5)
        return None

    def start_ngrok(self, env: dict[str, str]) -> bool:
        if not self.ngrok_path:
            self.status["ngrok"] = {"status": "offline", "public_url": None}
            self.write_status()
            return False
        owner = port_owner_pid(4040)
        if owner:
            command = process_command_line(owner)
            try:
                tunnel = select_https_tunnel(http_json(NGROK_API_URL), 8000)
            except Exception:
                tunnel = None
            if not tunnel or not command_matches(command, ["ngrok"]):
                self.log.write("ERROR", f"Port 4040 is already used by another program (PID {owner}). It was not stopped.")
                return False
            self.processes["ngrok"] = {"pid": owner, "markers": ["ngrok"], "reused": True}
            self.write_process_file()
            self.log.write("NGROK", f"Reusing existing tunnel process. PID: {owner}")
        else:
            self.log.write("SYSTEM", "Starting ngrok tunnel to FastAPI port 8000...")
            self.start_child(
                "NGROK",
                [str(self.ngrok_path), "http", API_URL, "--log", "stdout", "--log-format", "logfmt"],
                ["ngrok", "http", "8000"],
                env,
            )
        tunnel = self.poll_ngrok()
        if not tunnel:
            self.log.write("ERROR", "ngrok could not create the public tunnel. WAAPI remains disabled.")
            self.status["ngrok"] = {"status": "offline", "pid": self.processes.get("ngrok", {}).get("pid"), "public_url": None}
            self.write_status()
            return False
        public_url = str(tunnel["public_url"]).rstrip("/")
        self.ngrok_last_online = True
        self.status["ngrok"] = {"status": "online", "pid": self.processes["ngrok"]["pid"], "public_url": public_url}
        self.write_status()
        self.log.write("SYSTEM", "ngrok is ONLINE.")
        self.log.write("SYSTEM", f"Public FastAPI URL: {public_url}")
        self.log.write("SYSTEM", f"Future WAAPI webhook URL: {public_url}/webhooks/waapi")
        self.log.write("WARNING", "WAAPI remains DISABLED. No webhook was registered.")
        return True

    def poll_streamlit(self, attempts: int = 30) -> bool:
        for attempt in range(1, attempts + 1):
            if attempt in {1, 5, 10, 15, 20, 25, 30}:
                self.log.write("SYSTEM", f"Streamlit health attempt {attempt}/{attempts}...")
            try:
                if http_text(f"{STREAMLIT_URL}/_stcore/health").strip().lower() == "ok":
                    return True
            except Exception:
                pass
            time.sleep(0.5)
        return False

    def start_streamlit(self, env: dict[str, str]) -> bool:
        owner = port_owner_pid(8501)
        if owner:
            command = process_command_line(owner)
            try:
                online = http_text(f"{STREAMLIT_URL}/_stcore/health").strip().lower() == "ok"
            except Exception:
                online = False
            if not online or not command_matches(command, ["streamlit", "app.py"]):
                self.log.write("ERROR", f"Port 8501 is already used by another program (PID {owner}). It was not stopped.")
                return False
            self.processes["streamlit"] = {"pid": owner, "markers": ["streamlit", "app.py"], "reused": True}
            self.write_process_file()
            self.log.write("STREAMLIT", f"Reusing existing AMS dashboard process. PID: {owner}")
        else:
            self.log.write("SYSTEM", "Starting Streamlit dashboard...")
            self.start_child(
                "STREAMLIT",
                [str(self.python), "-m", "streamlit", "run", str(REPO_ROOT / "app.py"), "--server.address=127.0.0.1", "--server.port=8501", "--server.headless=true", "--browser.gatherUsageStats=false"],
                ["streamlit", "app.py", "8501"],
                env,
            )
        if not self.poll_streamlit():
            self.log.write("ERROR", f"Streamlit could not start. See: {self.log_dir / 'streamlit.log'}")
            return False
        self.status["streamlit"] = {"status": "online", "pid": self.processes["streamlit"]["pid"], "url": STREAMLIT_URL}
        self.write_status()
        self.log.write("SYSTEM", "Streamlit is ONLINE.")
        if os.getenv("AMS_NO_BROWSER") != "1":
            webbrowser.open(DASHBOARD_URL)
        return True

    def summary(self) -> None:
        public_url = self.status["ngrok"].get("public_url") or "Not available"
        future = f"{public_url}/webhooks/waapi" if public_url.startswith("https://") else "Not available"
        ngrok_status = self.status["ngrok"]["status"].upper()
        print(
            f"""
============================================================
 AMS WHATSAPP OPERATIONS SYSTEM
============================================================

 FastAPI:           ONLINE
 Request Worker:    ONLINE
 Database:          {self.status['database']['status'].upper()}
 ngrok:             {ngrok_status}
 Streamlit:         ONLINE
 Simulation Mode:   ENABLED
 WAAPI:             DISABLED
 Live Sending:      DISABLED

 Dashboard:
 {DASHBOARD_URL}

 Local API:
 {API_URL}

 Public API:
 {public_url}

 Future Webhook:
 {future}

 Logs:
 {self.log_dir}

 No WAAPI connection or message sending is active.
============================================================
""",
            flush=True,
        )
        self.log.write("SYSTEM", "SYSTEM READY. Leave this terminal open.")

    def _refresh_health(self) -> None:
        try:
            health = http_json(f"{API_URL}/health")
            self.status["fastapi"]["status"] = "online" if health.get("status") == "ok" else "offline"
            self.status["worker"]["status"] = health.get("worker", {}).get("status", "offline")
            self.status["database"]["status"] = "online" if health.get("database", {}).get("ok") else "offline"
        except Exception:
            self.status["fastapi"]["status"] = "offline"
            self.status["worker"]["status"] = "offline"
            self.status["database"]["status"] = "offline"
        try:
            tunnel = select_https_tunnel(http_json(NGROK_API_URL), 8000)
            if tunnel:
                self.status["ngrok"].update(status="online", public_url=tunnel["public_url"])
            else:
                self.status["ngrok"]["status"] = "offline"
        except Exception:
            self.status["ngrok"]["status"] = "offline"
        try:
            streamlit_online = http_text(f"{STREAMLIT_URL}/_stcore/health").strip().lower() == "ok"
        except Exception:
            streamlit_online = False
        self.status["streamlit"]["status"] = "online" if streamlit_online else "offline"
        self.write_status()

    def monitor(self) -> None:
        last_health = 0.0
        while not self.stop_event.wait(0.5):
            if SHUTDOWN_FILE.exists():
                self.log.write("SYSTEM", "Shutdown request received.")
                break
            try:
                name, code = self.exit_queue.get_nowait()
            except queue.Empty:
                name = ""
                code = 0
            if name and not self.stop_event.is_set():
                self.log.write("ERROR", f"{name.title()} stopped unexpectedly with exit code {code}.")
                key = name.lower()
                if key in self.status:
                    self.status[key]["status"] = "offline"
                if name == "API":
                    self.status["worker"]["status"] = "offline"
                self.write_status()
            if time.monotonic() - last_health >= 5:
                self._refresh_health()
                last_health = time.monotonic()

    def stop_child(self, name: str) -> None:
        key = name.lower()
        process_info = self.processes.get(key)
        if not process_info:
            return
        pid = int(process_info.get("pid") or 0)
        markers = process_info.get("markers") or []
        if not pid_alive(pid):
            self.log.write("SYSTEM", f"{name.title()} is already stopped.")
            return
        command = process_command_line(pid)
        if not command_matches(command, markers):
            self.log.write("WARNING", f"Recorded PID {pid} no longer belongs to AMS {name}; it was not stopped.")
            return
        self.log.write("SYSTEM", f"Stopping {name.title()}...")
        process = self.children.get(name.upper())
        try:
            if process:
                process.send_signal(signal.CTRL_BREAK_EVENT if os.name == "nt" else signal.SIGINT)
            else:
                os.kill(pid, signal.CTRL_BREAK_EVENT if os.name == "nt" else signal.SIGINT)
        except (OSError, ValueError):
            pass
        deadline = time.monotonic() + 5
        while pid_alive(pid) and time.monotonic() < deadline:
            time.sleep(0.2)
        if pid_alive(pid):
            self.log.write("WARNING", f"{name.title()} did not exit cleanly; stopping recorded PID {pid}.")
            subprocess.run(["taskkill", "/PID", str(pid), "/F"], capture_output=True, startupinfo=_hidden_startup_info(), check=False)
        self.log.write("SYSTEM", f"{name.title()} stopped.")

    def shutdown(self) -> None:
        self.stop_event.set()
        for name in ["streamlit", "ngrok", "api"]:
            self.stop_child(name)
        for key in ["streamlit", "ngrok", "fastapi", "worker", "database"]:
            if key in self.status:
                self.status[key]["status"] = "offline"
        self.status["stopped_at"] = utc_now()
        self.write_status()
        PROCESS_FILE.unlink(missing_ok=True)
        SHUTDOWN_FILE.unlink(missing_ok=True)
        self.log.write("SYSTEM", "AMS WhatsApp Operations System is OFFLINE.")
        self.log.close()

    def run(self) -> int:
        RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
        SHUTDOWN_FILE.unlink(missing_ok=True)
        self.write_status()
        self.write_process_file()
        if not self.validate():
            self.shutdown()
            return 1
        env = self.safe_environment()
        if not self.start_api(env):
            self.shutdown()
            return 1
        self.start_ngrok(env)
        if not self.start_streamlit(env):
            self.log.write("ERROR", "Partial startup is being cleaned up.")
            self.shutdown()
            return 1
        self.summary()
        try:
            self.monitor()
        except KeyboardInterrupt:
            self.log.write("SYSTEM", "Console shutdown requested.")
        finally:
            self.shutdown()
        return 0


def existing_supervisor() -> dict[str, Any] | None:
    runtime = load_json_file(PROCESS_FILE)
    supervisor = runtime.get("supervisor") or {}
    pid = int(supervisor.get("pid") or 0)
    if pid_alive(pid) and command_matches(process_command_line(pid), supervisor.get("markers") or ["ams_supervisor.py"]):
        return runtime
    return None


def terminate_recorded_process(info: dict[str, Any], label: str) -> str:
    pid = int(info.get("pid") or 0)
    if not pid_alive(pid):
        return f"[SYSTEM] {label} is already stopped."
    if not command_matches(process_command_line(pid), info.get("markers") or []):
        return f"[WARNING] Recorded PID {pid} does not belong to AMS {label}; it was not stopped."
    try:
        os.kill(pid, signal.CTRL_BREAK_EVENT if os.name == "nt" else signal.SIGINT)
    except (OSError, ValueError):
        pass
    deadline = time.monotonic() + 5
    while pid_alive(pid) and time.monotonic() < deadline:
        time.sleep(0.2)
    if pid_alive(pid):
        subprocess.run(["taskkill", "/PID", str(pid), "/F"], capture_output=True, startupinfo=_hidden_startup_info(), check=False)
    return f"[SYSTEM] {label} stopped."


def stop_system() -> int:
    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    runtime = load_json_file(PROCESS_FILE)
    if not runtime:
        print("[SYSTEM] AMS WhatsApp Operations System is already OFFLINE.")
        return 0
    supervisor = existing_supervisor()
    if supervisor:
        SHUTDOWN_FILE.write_text(utc_now(), encoding="utf-8")
        pid = int((supervisor.get("supervisor") or {}).get("pid") or 0)
        print("[SYSTEM] Shutdown request sent to the AMS supervisor.")
        deadline = time.monotonic() + 20
        while pid_alive(pid) and time.monotonic() < deadline:
            time.sleep(0.25)
        if not pid_alive(pid):
            print("[SYSTEM] AMS WhatsApp Operations System is OFFLINE.")
            return 0
        print("[WARNING] The supervisor did not finish in time; checking recorded child processes.")
    processes = runtime.get("processes") or {}
    for key, label in [("streamlit", "Streamlit"), ("ngrok", "ngrok"), ("api", "FastAPI and request worker")]:
        if key in processes:
            print(terminate_recorded_process(processes[key], label))
    PROCESS_FILE.unlink(missing_ok=True)
    SHUTDOWN_FILE.unlink(missing_ok=True)
    status = load_json_file(STATUS_FILE)
    if status:
        for key in ["streamlit", "ngrok", "fastapi", "worker", "database"]:
            if isinstance(status.get(key), dict):
                status[key]["status"] = "offline"
        status["stopped_at"] = utc_now()
        atomic_write_json(STATUS_FILE, status)
    print("[SYSTEM] AMS WhatsApp Operations System is OFFLINE.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--python", default=sys.executable)
    parser.add_argument("--stop", action="store_true")
    args = parser.parse_args()
    if args.stop:
        return stop_system()
    active = existing_supervisor()
    if active:
        status = load_json_file(STATUS_FILE)
        print("[WARNING] The AMS WhatsApp Operations System is already running. No duplicate services were started.")
        print(f"[SYSTEM] Dashboard: {status.get('streamlit', {}).get('url', DASHBOARD_URL)}/whatsapp-request-processor")
        return 0
    return Supervisor(Path(args.python)).run()


if __name__ == "__main__":
    raise SystemExit(main())
