"""
Endpoint Central — Windows Agent
Runs as a Windows Service via pywin32.
Collects hardware/OS info, sends heartbeats, executes commands.
"""
import json
import os
import platform
import socket
import subprocess
import sys
import time
import uuid
import logging
from pathlib import Path
from typing import Optional

import psutil
import requests

# ── Windows Service support ───────────────────────────────────────────────
# Only import win32 if we're actually on Windows
IS_WINDOWS = platform.system() == "Windows"
if IS_WINDOWS:
    import win32serviceutil
    import win32service
    import win32event
    import servicemanager

# ── Configuration ─────────────────────────────────────────────────────────
GATEWAY_URL = os.environ.get("EC_GATEWAY_URL", "http://localhost:8001")
GATEWAY_KEY = os.environ.get("EC_GATEWAY_KEY", "dev-gateway-key")
HEARTBEAT_INTERVAL = int(os.environ.get("EC_HEARTBEAT_INTERVAL", "60"))

LOG_DIR = Path(os.environ.get("EC_LOG_DIR", "C:/ProgramData/EndpointCentral/logs"))
LOG_DIR.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_DIR / "agent.log"),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger("ec-agent")

HEADERS = {"X-Gateway-Key": GATEWAY_KEY, "Content-Type": "application/json"}


# ── Device identity ────────────────────────────────────────────────────────

def get_device_id() -> str:
    """Stable unique ID — uses Windows MachineGuid from registry, falls back to MAC."""
    if IS_WINDOWS:
        try:
            import winreg
            key = winreg.OpenKey(
                winreg.HKEY_LOCAL_MACHINE,
                r"SOFTWARE\Microsoft\Cryptography"
            )
            value, _ = winreg.QueryValueEx(key, "MachineGuid")
            return value
        except Exception:
            pass
    return str(uuid.UUID(int=uuid.getnode()))


def get_windows_version() -> str:
    try:
        v = platform.version()
        r = platform.release()
        return f"Windows {r} ({v})"
    except Exception:
        return "Windows (unknown)"


def get_current_user() -> str:
    try:
        return os.environ.get("USERNAME") or os.environ.get("USER") or "unknown"
    except Exception:
        return "unknown"


def get_ip_address() -> Optional[str]:
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return None


# ── Metrics collection ─────────────────────────────────────────────────────

def collect_metrics() -> dict:
    cpu = psutil.cpu_percent(interval=1)
    ram = psutil.virtual_memory()
    disk = psutil.disk_usage("/")
    return {
        "cpu_percent": cpu,
        "ram_percent": ram.percent,
        "disk_percent": disk.percent,
        "ram_total": ram.total,
        "disk_total": disk.total,
    }


# ── Software inventory ─────────────────────────────────────────────────────

def collect_software_inventory() -> list[dict]:
    software = []
    if not IS_WINDOWS:
        return software
    try:
        import winreg
        for hive in [winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER]:
            for path in [
                r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall",
                r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall",
            ]:
                try:
                    key = winreg.OpenKey(hive, path)
                    for i in range(winreg.QueryInfoKey(key)[0]):
                        try:
                            sub = winreg.OpenKey(key, winreg.EnumKey(key, i))
                            name = _reg_val(sub, "DisplayName")
                            if not name:
                                continue
                            software.append({
                                "name": name,
                                "version": _reg_val(sub, "DisplayVersion"),
                                "publisher": _reg_val(sub, "Publisher"),
                                "install_date": _reg_val(sub, "InstallDate"),
                            })
                        except Exception:
                            pass
                except Exception:
                    pass
    except Exception as e:
        log.warning(f"SW inventory error: {e}")
    return software


def _reg_val(key, name: str) -> Optional[str]:
    try:
        import winreg
        val, _ = winreg.QueryValueEx(key, name)
        return str(val).strip() or None
    except Exception:
        return None


# ── Script execution ───────────────────────────────────────────────────────

def execute_script(cmd: dict) -> dict:
    script_type = cmd.get("script_type", "powershell")
    content = cmd.get("content", "")
    deployment_id = cmd.get("deployment_id")

    # Write to temp file
    ext_map = {"powershell": ".ps1", "cmd": ".bat", "python": ".py", "bash": ".sh"}
    ext = ext_map.get(script_type, ".ps1")
    tmp_path = Path(os.environ.get("TEMP", "C:/Temp")) / f"ec_script_{uuid.uuid4().hex[:8]}{ext}"
    tmp_path.write_text(content, encoding="utf-8")

    try:
        if script_type == "powershell":
            proc_args = ["powershell.exe", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", str(tmp_path)]
        elif script_type == "cmd":
            proc_args = ["cmd.exe", "/c", str(tmp_path)]
        elif script_type == "python":
            proc_args = [sys.executable, str(tmp_path)]
        else:
            proc_args = ["cmd.exe", "/c", str(tmp_path)]

        result = subprocess.run(
            proc_args, capture_output=True, text=True, timeout=300
        )
        return {
            "deployment_id": deployment_id,
            "device_id": get_device_id(),
            "status": "success" if result.returncode == 0 else "failed",
            "stdout": result.stdout[:4096],
            "stderr": result.stderr[:2048],
            "exit_code": result.returncode,
        }
    except subprocess.TimeoutExpired:
        return {"deployment_id": deployment_id, "device_id": get_device_id(),
                "status": "failed", "stderr": "Timeout after 300s", "exit_code": -1}
    except Exception as e:
        return {"deployment_id": deployment_id, "device_id": get_device_id(),
                "status": "failed", "stderr": str(e), "exit_code": -1}
    finally:
        tmp_path.unlink(missing_ok=True)


# ── Gateway communication ──────────────────────────────────────────────────

class AgentClient:
    def __init__(self):
        self.device_id = get_device_id()
        self.session = requests.Session()
        self.session.headers.update(HEADERS)

    def register(self) -> bool:
        try:
            payload = {
                "device_id": self.device_id,
                "hostname": socket.gethostname(),
                "ip_address": get_ip_address(),
                "os_type": "windows",
                "os_version": get_windows_version(),
                "username": get_current_user(),
            }
            resp = self.session.post(f"{GATEWAY_URL}/agent/register", json=payload, timeout=10)
            resp.raise_for_status()
            log.info(f"Registered with gateway. device_id={self.device_id}")
            return True
        except Exception as e:
            log.error(f"Registration failed: {e}")
            return False

    def heartbeat(self) -> list[dict]:
        try:
            metrics = collect_metrics()
            payload = {
                "device_id": self.device_id,
                "ip_address": get_ip_address(),
                "username": get_current_user(),
                **metrics,
            }
            resp = self.session.post(f"{GATEWAY_URL}/agent/heartbeat", json=payload, timeout=10)
            resp.raise_for_status()
            data = resp.json()
            return data.get("commands", [])
        except Exception as e:
            log.warning(f"Heartbeat failed: {e}")
            return []

    def report_script_result(self, result: dict) -> None:
        try:
            self.session.post(f"{GATEWAY_URL}/agent/script-result", json=result, timeout=10)
        except Exception as e:
            log.warning(f"Could not report script result: {e}")

    def send_software_inventory(self) -> None:
        try:
            sw = collect_software_inventory()
            payload = {"device_id": self.device_id, "software": sw}
            self.session.post(f"{GATEWAY_URL}/agent/software-inventory", json=payload, timeout=30)
            log.info(f"Sent software inventory: {len(sw)} items")
        except Exception as e:
            log.warning(f"SW inventory send failed: {e}")


# ── Main loop ──────────────────────────────────────────────────────────────

def run_agent_loop(stop_event=None) -> None:
    client = AgentClient()

    # Register with gateway
    while not client.register():
        log.info("Retrying registration in 30s…")
        time.sleep(30)

    # Send initial software inventory
    client.send_software_inventory()

    tick = 0
    while True:
        if stop_event and stop_event.is_set():
            break

        commands = client.heartbeat()
        for cmd in commands:
            cmd_type = cmd.get("type")
            log.info(f"Received command: {cmd_type}")
            if cmd_type == "run_script":
                result = execute_script(cmd)
                client.report_script_result(result)

        tick += 1
        # Refresh SW inventory every 6 heartbeats (~6 min)
        if tick % 6 == 0:
            client.send_software_inventory()

        for _ in range(HEARTBEAT_INTERVAL):
            if stop_event and stop_event.is_set():
                return
            time.sleep(1)


# ── Windows Service wrapper ────────────────────────────────────────────────

if IS_WINDOWS:
    class EndpointCentralService(win32serviceutil.ServiceFramework):
        _svc_name_ = "EndpointCentralAgent"
        _svc_display_name_ = "Endpoint Central Agent"
        _svc_description_ = "Endpoint Central monitoring and management agent"

        def __init__(self, args):
            win32serviceutil.ServiceFramework.__init__(self, args)
            self.stop_event = win32event.CreateEvent(None, 0, 0, None)
            self._running = True

        def SvcStop(self):
            self.ReportServiceStatus(win32service.SERVICE_STOP_PENDING)
            win32event.SetEvent(self.stop_event)
            self._running = False

        def SvcDoRun(self):
            servicemanager.LogMsg(
                servicemanager.EVENTLOG_INFORMATION_TYPE,
                servicemanager.PYS_SERVICE_STARTED,
                (self._svc_name_, ""),
            )
            import threading
            stop = threading.Event()

            def _watch():
                win32event.WaitForSingleObject(self.stop_event, win32event.INFINITE)
                stop.set()

            import threading
            threading.Thread(target=_watch, daemon=True).start()
            run_agent_loop(stop_event=stop)


if __name__ == "__main__":
    if IS_WINDOWS and len(sys.argv) > 1:
        win32serviceutil.HandleCommandLine(EndpointCentralService)
    else:
        # Run directly (dev / Linux test mode)
        run_agent_loop()
