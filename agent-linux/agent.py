#!/usr/bin/env python3
"""
Endpoint Central — Linux Agent
Runs as a systemd service.
Collects hardware/OS info, sends heartbeats, executes bash/python scripts.
"""
import json
import logging
import os
import platform
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import uuid
from pathlib import Path
from typing import Optional

import psutil
import requests

# ── Configuration ─────────────────────────────────────────────────────────
GATEWAY_URL = os.environ.get("EC_GATEWAY_URL", "http://localhost:8001")
GATEWAY_KEY = os.environ.get("EC_GATEWAY_KEY", "dev-gateway-key")
HEARTBEAT_INTERVAL = int(os.environ.get("EC_HEARTBEAT_INTERVAL", "60"))

LOG_DIR = Path(os.environ.get("EC_LOG_DIR", "/var/log/endpoint-central"))
LOG_DIR.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_DIR / "agent.log"),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger("ec-agent-linux")

HEADERS = {"X-Gateway-Key": GATEWAY_KEY, "Content-Type": "application/json"}
DEVICE_ID_FILE = Path("/etc/endpoint-central/device-id")


# ── Device identity ────────────────────────────────────────────────────────

def get_device_id() -> str:
    """
    Stable ID using /etc/machine-id.
    Falls back to stored UUID file, then generates a new one.
    """
    # Primary: /etc/machine-id (systemd standard)
    mid = Path("/etc/machine-id")
    if mid.exists():
        val = mid.read_text().strip()
        if val:
            return val

    # Secondary: stored file
    if DEVICE_ID_FILE.exists():
        return DEVICE_ID_FILE.read_text().strip()

    # Generate
    new_id = str(uuid.uuid4())
    DEVICE_ID_FILE.parent.mkdir(parents=True, exist_ok=True)
    DEVICE_ID_FILE.write_text(new_id)
    return new_id


def get_linux_distro() -> str:
    try:
        result = subprocess.run(
            ["lsb_release", "-ds"], capture_output=True, text=True, timeout=5
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except Exception:
        pass
    # Fallback: /etc/os-release
    try:
        info = platform.freedesktop_os_release()
        return info.get("PRETTY_NAME", "Linux")
    except Exception:
        return platform.system() + " " + platform.release()


def get_current_user() -> str:
    try:
        return os.environ.get("USER") or os.environ.get("LOGNAME") or \
               subprocess.run(["whoami"], capture_output=True, text=True).stdout.strip()
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

    # Try dpkg (Debian/Ubuntu)
    if shutil.which("dpkg-query"):
        try:
            result = subprocess.run(
                ["dpkg-query", "-W", "-f=${Package}\t${Version}\t${Maintainer}\n"],
                capture_output=True, text=True, timeout=30,
            )
            for line in result.stdout.strip().splitlines():
                parts = line.split("\t")
                if len(parts) >= 2:
                    software.append({
                        "name": parts[0],
                        "version": parts[1],
                        "publisher": parts[2] if len(parts) > 2 else None,
                        "install_date": None,
                    })
            return software
        except Exception as e:
            log.warning(f"dpkg-query failed: {e}")

    # Try rpm (RHEL/CentOS/Fedora)
    if shutil.which("rpm"):
        try:
            result = subprocess.run(
                ["rpm", "-qa", "--queryformat", "%{NAME}\t%{VERSION}\t%{VENDOR}\n"],
                capture_output=True, text=True, timeout=30,
            )
            for line in result.stdout.strip().splitlines():
                parts = line.split("\t")
                if parts[0]:
                    software.append({
                        "name": parts[0],
                        "version": parts[1] if len(parts) > 1 else None,
                        "publisher": parts[2] if len(parts) > 2 else None,
                        "install_date": None,
                    })
            return software
        except Exception as e:
            log.warning(f"rpm query failed: {e}")

    return software

# ── Policy application (Linux) ──────────────────────────────────────────────

def _detect_desktop_env() -> str:
    de = os.environ.get("XDG_CURRENT_DESKTOP", "") or os.environ.get("DESKTOP_SESSION", "")
    return de.lower()


def _graphical_user_env() -> dict:
    """Best-effort: tìm user đang đăng nhập GUI để chạy lệnh gsettings/dconf
    đúng session, vì agent chạy bằng systemd thường ở quyền root."""
    env = os.environ.copy()
    try:
        who = subprocess.run(["who"], capture_output=True, text=True, timeout=5)
        for line in who.stdout.splitlines():
            parts = line.split()
            if parts and parts[0] != "root":
                user = parts[0]
                uid = subprocess.run(
                    ["id", "-u", user], capture_output=True, text=True, timeout=5
                ).stdout.strip()
                env["DISPLAY"] = env.get("DISPLAY", ":0")
                env["DBUS_SESSION_BUS_ADDRESS"] = f"unix:path=/run/user/{uid}/bus"
                env["RUN_AS_USER"] = user
                break
    except Exception:
        pass
    return env


def policy_wallpaper(config: dict) -> dict:
    """Set desktop wallpaper. Hỗ trợ GNOME/Cinnamon/XFCE qua best-effort."""
    url = config.get("url")
    style = config.get("style", "fill")
    if not url:
        return {"ok": False, "message": "Missing 'url' in policy config"}

    try:
        dest = Path("/tmp/ec_wallpaper" + (Path(url).suffix or ".jpg"))
        if url.startswith("http://") or url.startswith("https://"):
            r = requests.get(url, timeout=30)
            r.raise_for_status()
            dest.write_bytes(r.content)
        else:
            dest = Path(url)
            if not dest.exists():
                return {"ok": False, "message": f"Local wallpaper path not found: {url}"}

        env = _graphical_user_env()
        user = env.get("RUN_AS_USER")
        de = _detect_desktop_env()

        def run_as_user(args):
            if user:
                full = ["sudo", "-u", user, "env",
                        f"DISPLAY={env.get('DISPLAY', ':0')}",
                        f"DBUS_SESSION_BUS_ADDRESS={env.get('DBUS_SESSION_BUS_ADDRESS', '')}"] + args
            else:
                full = args
            return subprocess.run(full, capture_output=True, text=True, timeout=15)

        if "gnome" in de or "cinnamon" in de or "unity" in de or shutil.which("gsettings"):
            run_as_user(["gsettings", "set", "org.gnome.desktop.background",
                         "picture-uri", f"file://{dest}"])
            run_as_user(["gsettings", "set", "org.gnome.desktop.background",
                         "picture-uri-dark", f"file://{dest}"])
            run_as_user(["gsettings", "set", "org.gnome.desktop.background",
                         "picture-options", style])
        elif "xfce" in de or shutil.which("xfconf-query"):
            run_as_user(["xfconf-query", "-c", "xfce4-desktop", "-p",
                         "/backdrop/screen0/monitor0/workspace0/last-image",
                         "-s", str(dest)])
        elif shutil.which("feh"):
            run_as_user(["feh", "--bg-fill", str(dest)])
        else:
            return {"ok": False, "message": f"No supported wallpaper tool found for DE='{de}'"}

        return {"ok": True, "message": f"Wallpaper set via {de or 'feh'}"}
    except Exception as e:
        return {"ok": False, "message": str(e)}


def policy_disable_usb(config: dict) -> dict:
    """Disable/enable USB storage qua blacklist usb-storage kernel module."""
    enabled = config.get("enabled", True)
    try:
        blacklist_file = Path("/etc/modprobe.d/ec-usb-storage.conf")
        if enabled:
            blacklist_file.write_text("blacklist usb_storage\n")
            subprocess.run(["modprobe", "-r", "usb_storage"], capture_output=True, timeout=10)
        else:
            blacklist_file.unlink(missing_ok=True)
            subprocess.run(["modprobe", "usb_storage"], capture_output=True, timeout=10)
        subprocess.run(["update-initramfs", "-u"], capture_output=True, timeout=60)
        return {"ok": True, "message": f"USB storage {'disabled' if enabled else 'enabled'} (reboot may be required)"}
    except Exception as e:
        return {"ok": False, "message": str(e)}


def policy_linux_sysctl(config: dict) -> dict:
    """Set sysctl key + persist vào /etc/sysctl.d."""
    key = config.get("key")
    value = config.get("value")
    if not key or value is None:
        return {"ok": False, "message": "Missing 'key' or 'value' in policy config"}
    try:
        subprocess.run(["sysctl", "-w", f"{key}={value}"], check=True,
                        capture_output=True, text=True, timeout=10)
        conf_path = Path(f"/etc/sysctl.d/99-ec-{key.replace('.', '-')}.conf")
        conf_path.write_text(f"{key} = {value}\n")
        return {"ok": True, "message": f"sysctl {key}={value} applied and persisted"}
    except subprocess.CalledProcessError as e:
        return {"ok": False, "message": e.stderr.strip() or str(e)}
    except Exception as e:
        return {"ok": False, "message": str(e)}


def policy_unsupported(config: dict) -> dict:
    return {"ok": False, "message": "Policy type not supported on Linux agent"}


POLICY_HANDLERS = {
    "wallpaper": policy_wallpaper,
    "disable_usb": policy_disable_usb,
    "linux_sysctl": policy_linux_sysctl,
    "disable_cmd": policy_unsupported,
    "disable_task_manager": policy_unsupported,
    "custom_registry": policy_unsupported,
}


def apply_policy(cmd: dict) -> dict:
    policy_type = cmd.get("policy_type", "")
    config = cmd.get("config") or {}
    handler = POLICY_HANDLERS.get(policy_type, policy_unsupported)
    log.info(f"Applying policy: {policy_type}")
    result = handler(config)
    return {
        "device_id": get_device_id(),
        "policy_id": cmd.get("policy_id"),
        "assignment_id": cmd.get("assignment_id"),
        "policy_type": policy_type,
        "status": "success" if result.get("ok") else "failed",
        "message": result.get("message", ""),
    }

# ── Script execution ───────────────────────────────────────────────────────

def execute_script(cmd: dict) -> dict:
    script_type = cmd.get("script_type", "bash")
    content = cmd.get("content", "")
    deployment_id = cmd.get("deployment_id")

    ext_map = {"bash": ".sh", "python": ".py", "powershell": ".ps1"}
    ext = ext_map.get(script_type, ".sh")

    with tempfile.NamedTemporaryFile(
        mode="w", suffix=ext, delete=False, prefix="ec_script_"
    ) as f:
        f.write(content)
        tmp_path = f.name

    os.chmod(tmp_path, 0o700)

    try:
        if script_type == "bash":
            proc_args = ["/bin/bash", tmp_path]
        elif script_type == "python":
            proc_args = [sys.executable, tmp_path]
        else:
            log.warning(f"Script type '{script_type}' not supported on Linux")
            return {
                "deployment_id": deployment_id,
                "device_id": get_device_id(),
                "status": "failed",
                "stderr": f"Script type '{script_type}' not supported on Linux",
                "exit_code": -1,
            }

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
        return {
            "deployment_id": deployment_id,
            "device_id": get_device_id(),
            "status": "failed",
            "stderr": "Timeout after 300s",
            "exit_code": -1,
        }
    except Exception as e:
        return {
            "deployment_id": deployment_id,
            "device_id": get_device_id(),
            "status": "failed",
            "stderr": str(e),
            "exit_code": -1,
        }
    finally:
        Path(tmp_path).unlink(missing_ok=True)


# ── Gateway communication ──────────────────────────────────────────────────

class AgentClient:
    def __init__(self):
        self.device_id = get_device_id()
        self.session = requests.Session()
        self.session.headers.update(HEADERS)
        self.distro = get_linux_distro()

    def register(self) -> bool:
        try:
            payload = {
                "device_id": self.device_id,
                "hostname": socket.gethostname(),
                "ip_address": get_ip_address(),
                "os_type": "linux",
                "os_version": self.distro,
                "username": get_current_user(),
            }
            resp = self.session.post(f"{GATEWAY_URL}/agent/register", json=payload, timeout=10)
            resp.raise_for_status()
            log.info(f"Registered. device_id={self.device_id}")
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
            return resp.json().get("commands", [])
        except Exception as e:
            log.warning(f"Heartbeat failed: {e}")
            return []

    def report_script_result(self, result: dict) -> None:
        try:
            self.session.post(f"{GATEWAY_URL}/agent/script-result", json=result, timeout=10)
        except Exception as e:
            log.warning(f"Could not report result: {e}")

    def report_policy_result(self, result: dict) -> None:
        try:
            self.session.post(f"{GATEWAY_URL}/agent/policy-result", json=result, timeout=10)
        except Exception as e:
            log.warning(f"Could not report policy result: {e}")

    def send_software_inventory(self) -> None:
        try:
            sw = collect_software_inventory()
            payload = {"device_id": self.device_id, "software": sw}
            self.session.post(f"{GATEWAY_URL}/agent/software-inventory", json=payload, timeout=30)
            log.info(f"SW inventory sent: {len(sw)} packages")
        except Exception as e:
            log.warning(f"SW inventory failed: {e}")


# ── Main loop ──────────────────────────────────────────────────────────────

def main() -> None:
    log.info(f"Endpoint Central Linux Agent starting. GATEWAY={GATEWAY_URL}")
    client = AgentClient()

    # Register with retry
    while not client.register():
        log.info("Retrying registration in 30s…")
        time.sleep(30)

    client.send_software_inventory()

    tick = 0
    while True:
        commands = client.heartbeat()
        for cmd in commands:
            cmd_type = cmd.get("type")
            log.info(f"Received command: {cmd_type}")
            if cmd_type == "run_script":
                result = execute_script(cmd)
                client.report_script_result(result)
            elif cmd_type == "apply_policy":
                result = apply_policy(cmd)
                client.report_policy_result(result)
    
        tick += 1
        if tick % 6 == 0:
            client.send_software_inventory()

        time.sleep(HEARTBEAT_INTERVAL)


if __name__ == "__main__":
    main()
