#!/bin/bash
# ============================================================
#  Endpoint Central — Linux Agent Installer
#  Chạy: sudo bash install.sh
# ============================================================

set -e

# ── Màu sắc terminal ────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
BLUE='\033[0;34m'; CYAN='\033[0;36m'; BOLD='\033[1m'; NC='\033[0m'

info()    { echo -e "${BLUE}[*]${NC} $1"; }
success() { echo -e "${GREEN}[✓]${NC} $1"; }
warn()    { echo -e "${YELLOW}[!]${NC} $1"; }
error()   { echo -e "${RED}[✗]${NC} $1"; exit 1; }
header()  { echo -e "\n${BOLD}${CYAN}$1${NC}"; echo "────────────────────────────────────"; }

# ── Kiểm tra quyền root ─────────────────────────────────────
if [[ $EUID -ne 0 ]]; then
    error "Cần chạy với quyền root: sudo bash install.sh"
fi

# ── Đọc file config ─────────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CONFIG_FILE="$SCRIPT_DIR/agent.conf"

if [[ ! -f "$CONFIG_FILE" ]]; then
    error "Không tìm thấy file agent.conf cạnh install.sh"
fi

# Parse config (bỏ qua comment và dòng trống)
while IFS='=' read -r key value; do
    [[ "$key" =~ ^#.*$ || -z "$key" ]] && continue
    key=$(echo "$key" | xargs)
    value=$(echo "$value" | xargs)
    export "$key=$value"
done < "$CONFIG_FILE"

# Kiểm tra các biến bắt buộc
[[ -z "$EC_GATEWAY_URL" ]] && error "EC_GATEWAY_URL chưa được đặt trong agent.conf"
[[ -z "$EC_GATEWAY_KEY" ]] && error "EC_GATEWAY_KEY chưa được đặt trong agent.conf"

# ── Banner ──────────────────────────────────────────────────
echo ""
echo -e "${BOLD}╔═══════════════════════════════════════╗${NC}"
echo -e "${BOLD}║     Endpoint Central Linux Agent      ║${NC}"
echo -e "${BOLD}╚═══════════════════════════════════════╝${NC}"
echo ""
info "Gateway URL : $EC_GATEWAY_URL"
info "Gateway Key : ${EC_GATEWAY_KEY:0:8}..."
echo ""

# ── Kiểm tra kết nối đến gateway ────────────────────────────
header "Kiểm tra kết nối"
info "Đang kiểm tra kết nối đến $EC_GATEWAY_URL ..."

if curl -sf --connect-timeout 5 "$EC_GATEWAY_URL/docs" > /dev/null 2>&1 || \
   curl -sf --connect-timeout 5 "$EC_GATEWAY_URL" > /dev/null 2>&1; then
    success "Kết nối đến gateway thành công"
else
    warn "Không thể kết nối đến gateway tại $EC_GATEWAY_URL"
    warn "Hãy kiểm tra:"
    echo "    1. Server đang chạy (docker compose up)"
    echo "    2. IP trong agent.conf đúng chưa"
    echo "    3. Firewall cho phép port 8001"
    echo ""
    read -rp "Tiếp tục cài đặt dù không kết nối được? [y/N]: " cont
    [[ "$cont" != "y" && "$cont" != "Y" ]] && error "Hủy cài đặt"
fi

# ── Cài đặt Python và pip ────────────────────────────────────
header "Cài đặt Python"
info "Kiểm tra Python 3..."

if command -v python3 &>/dev/null; then
    PY_VER=$(python3 --version 2>&1)
    success "Đã có $PY_VER"
else
    info "Đang cài Python 3..."
    if command -v apt-get &>/dev/null; then
        apt-get update -qq && apt-get install -y -qq python3 python3-pip python3-venv
    elif command -v yum &>/dev/null; then
        yum install -y -q python3 python3-pip
    elif command -v dnf &>/dev/null; then
        dnf install -y -q python3 python3-pip
    else
        error "Không tìm thấy package manager. Hãy cài Python 3 thủ công."
    fi
    success "Đã cài Python 3"
fi

# Cài curl nếu chưa có
command -v curl &>/dev/null || {
    info "Cài curl..."
    apt-get install -y -qq curl 2>/dev/null || yum install -y -q curl 2>/dev/null || true
}

# ── Tạo thư mục cài đặt ──────────────────────────────────────
header "Cài đặt Agent"
INSTALL_DIR="/opt/endpoint-central"
CONFIG_DIR="/etc/endpoint-central"
LOG_DIR="/var/log/endpoint-central"

info "Tạo thư mục cài đặt..."
mkdir -p "$INSTALL_DIR" "$CONFIG_DIR" "$LOG_DIR"

# Ghi file agent.py (nhúng thẳng vào script)
info "Ghi agent.py..."
cat > "$INSTALL_DIR/agent.py" << 'AGENT_PY'
#!/usr/bin/env python3
"""
Endpoint Central — Linux Agent
"""
import json, logging, os, platform, shutil, socket
import subprocess, sys, tempfile, time, uuid
from pathlib import Path
from typing import Optional

import psutil, requests

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
log = logging.getLogger("ec-agent")
HEADERS = {"X-Gateway-Key": GATEWAY_KEY, "Content-Type": "application/json"}
DEVICE_ID_FILE = Path("/etc/endpoint-central/device-id")

def get_device_id() -> str:
    mid = Path("/etc/machine-id")
    if mid.exists():
        val = mid.read_text().strip()
        if val: return val
    if DEVICE_ID_FILE.exists():
        return DEVICE_ID_FILE.read_text().strip()
    new_id = str(uuid.uuid4())
    DEVICE_ID_FILE.parent.mkdir(parents=True, exist_ok=True)
    DEVICE_ID_FILE.write_text(new_id)
    return new_id

def get_distro() -> str:
    try:
        r = subprocess.run(["lsb_release", "-ds"], capture_output=True, text=True, timeout=5)
        if r.returncode == 0: return r.stdout.strip()
    except Exception: pass
    try: return platform.freedesktop_os_release().get("PRETTY_NAME", "Linux")
    except Exception: return platform.system() + " " + platform.release()

def get_user() -> str:
    try:
        return os.environ.get("USER") or os.environ.get("LOGNAME") or \
               subprocess.run(["whoami"], capture_output=True, text=True).stdout.strip()
    except Exception: return "unknown"

def get_ip() -> Optional[str]:
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80)); ip = s.getsockname()[0]; s.close(); return ip
    except Exception: return None

def collect_metrics() -> dict:
    cpu = psutil.cpu_percent(interval=1)
    ram = psutil.virtual_memory()
    disk = psutil.disk_usage("/")
    return {"cpu_percent": cpu, "ram_percent": ram.percent, "disk_percent": disk.percent,
            "ram_total": ram.total, "disk_total": disk.total}

def collect_software() -> list:
    sw = []
    if shutil.which("dpkg-query"):
        try:
            r = subprocess.run(["dpkg-query", "-W", "-f=${Package}\t${Version}\t${Maintainer}\n"],
                               capture_output=True, text=True, timeout=30)
            for line in r.stdout.strip().splitlines():
                p = line.split("\t")
                if len(p) >= 2: sw.append({"name": p[0], "version": p[1],
                    "publisher": p[2] if len(p) > 2 else None, "install_date": None})
            return sw
        except Exception: pass
    if shutil.which("rpm"):
        try:
            r = subprocess.run(["rpm", "-qa", "--queryformat", "%{NAME}\t%{VERSION}\t%{VENDOR}\n"],
                               capture_output=True, text=True, timeout=30)
            for line in r.stdout.strip().splitlines():
                p = line.split("\t")
                if p[0]: sw.append({"name": p[0], "version": p[1] if len(p) > 1 else None,
                    "publisher": p[2] if len(p) > 2 else None, "install_date": None})
            return sw
        except Exception: pass
    return sw

def execute_script(cmd: dict) -> dict:
    script_type = cmd.get("script_type", "bash")
    content = cmd.get("content", "")
    deployment_id = cmd.get("deployment_id")
    ext = {"bash": ".sh", "python": ".py"}.get(script_type, ".sh")
    with tempfile.NamedTemporaryFile(mode="w", suffix=ext, delete=False, prefix="ec_") as f:
        f.write(content); tmp = f.name
    os.chmod(tmp, 0o700)
    try:
        args = [sys.executable, tmp] if script_type == "python" else ["/bin/bash", tmp]
        r = subprocess.run(args, capture_output=True, text=True, timeout=300)
        return {"deployment_id": deployment_id, "device_id": get_device_id(),
                "status": "success" if r.returncode == 0 else "failed",
                "stdout": r.stdout[:4096], "stderr": r.stderr[:2048], "exit_code": r.returncode}
    except subprocess.TimeoutExpired:
        return {"deployment_id": deployment_id, "device_id": get_device_id(),
                "status": "failed", "stderr": "Timeout 300s", "exit_code": -1}
    except Exception as e:
        return {"deployment_id": deployment_id, "device_id": get_device_id(),
                "status": "failed", "stderr": str(e), "exit_code": -1}
    finally: Path(tmp).unlink(missing_ok=True)

class AgentClient:
    def __init__(self):
        self.device_id = get_device_id()
        self.session = requests.Session()
        self.session.headers.update(HEADERS)
        self.distro = get_distro()

    def register(self) -> bool:
        try:
            r = self.session.post(f"{GATEWAY_URL}/agent/register", json={
                "device_id": self.device_id, "hostname": socket.gethostname(),
                "ip_address": get_ip(), "os_type": "linux",
                "os_version": self.distro, "username": get_user()
            }, timeout=10)
            r.raise_for_status()
            log.info(f"Đã đăng ký thành công. device_id={self.device_id}")
            return True
        except Exception as e:
            log.error(f"Đăng ký thất bại: {e}"); return False

    def heartbeat(self) -> list:
        try:
            r = self.session.post(f"{GATEWAY_URL}/agent/heartbeat",
                json={"device_id": self.device_id, "ip_address": get_ip(),
                      "username": get_user(), **collect_metrics()}, timeout=10)
            r.raise_for_status()
            return r.json().get("commands", [])
        except Exception as e:
            log.warning(f"Heartbeat thất bại: {e}"); return []

    def report_result(self, result: dict):
        try: self.session.post(f"{GATEWAY_URL}/agent/script-result", json=result, timeout=10)
        except Exception as e: log.warning(f"Không gửi được kết quả: {e}")

    def send_software(self):
        try:
            sw = collect_software()
            self.session.post(f"{GATEWAY_URL}/agent/software-inventory",
                json={"device_id": self.device_id, "software": sw}, timeout=30)
            log.info(f"Đã gửi danh sách phần mềm: {len(sw)} gói")
        except Exception as e: log.warning(f"Gửi phần mềm thất bại: {e}")

def main():
    log.info(f"Endpoint Central Linux Agent khởi động. Gateway={GATEWAY_URL}")
    client = AgentClient()
    while not client.register():
        log.info("Thử lại sau 30 giây..."); time.sleep(30)
    client.send_software()
    tick = 0
    while True:
        for cmd in client.heartbeat():
            if cmd.get("type") == "run_script":
                client.report_result(execute_script(cmd))
        tick += 1
        if tick % 6 == 0: client.send_software()
        time.sleep(HEARTBEAT_INTERVAL)

if __name__ == "__main__": main()
AGENT_PY

# ── Ghi requirements.txt ─────────────────────────────────────
cat > "$INSTALL_DIR/requirements.txt" << 'EOF'
psutil==6.0.0
requests==2.32.3
EOF

# ── Tạo virtualenv và cài dependencies ──────────────────────
info "Tạo Python virtualenv..."
python3 -m venv "$INSTALL_DIR/venv"
success "Đã tạo virtualenv"

info "Cài đặt dependencies (psutil, requests)..."
"$INSTALL_DIR/venv/bin/pip" install --quiet -r "$INSTALL_DIR/requirements.txt"
success "Đã cài dependencies"

# ── Ghi file environment ─────────────────────────────────────
info "Ghi file cấu hình..."
cat > "$CONFIG_DIR/agent.env" << EOF
EC_GATEWAY_URL=$EC_GATEWAY_URL
EC_GATEWAY_KEY=$EC_GATEWAY_KEY
EC_HEARTBEAT_INTERVAL=${EC_HEARTBEAT_INTERVAL:-60}
EC_LOG_DIR=$LOG_DIR
EOF
chmod 600 "$CONFIG_DIR/agent.env"
success "Đã ghi /etc/endpoint-central/agent.env"

# ── Hỏi có muốn cài systemd service không ───────────────────
header "Tùy chọn cài đặt"
echo -e "  ${BOLD}[1]${NC} Chạy thử ngay (foreground, Ctrl+C để dừng)"
echo -e "  ${BOLD}[2]${NC} Cài systemd service (chạy ngầm, tự khởi động cùng máy)"
echo ""
read -rp "Chọn [1/2]: " choice

if [[ "$choice" == "2" ]]; then
    # Cài systemd service
    info "Cài systemd service..."
    cat > /etc/systemd/system/endpoint-central.service << EOF
[Unit]
Description=Endpoint Central Agent
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=root
WorkingDirectory=$INSTALL_DIR
EnvironmentFile=$CONFIG_DIR/agent.env
ExecStart=$INSTALL_DIR/venv/bin/python $INSTALL_DIR/agent.py
Restart=always
RestartSec=30
StandardOutput=journal
StandardError=journal
SyslogIdentifier=ec-agent

[Install]
WantedBy=multi-user.target
EOF

    systemctl daemon-reload
    systemctl enable endpoint-central
    systemctl restart endpoint-central

    echo ""
    success "Service đã được cài và khởi động!"
    echo ""
    info "Kiểm tra trạng thái:"
    echo "    systemctl status endpoint-central"
    echo ""
    info "Xem log realtime:"
    echo "    journalctl -u endpoint-central -f"
    echo ""
    info "Dừng/khởi động lại:"
    echo "    systemctl stop endpoint-central"
    echo "    systemctl restart endpoint-central"
    echo ""

    # Hiện log 5 giây đầu
    sleep 3
    echo -e "${BOLD}Log khởi động:${NC}"
    journalctl -u endpoint-central -n 20 --no-pager 2>/dev/null || true

else
    # Chạy thử foreground
    echo ""
    success "Khởi động agent (Ctrl+C để dừng)..."
    echo ""
    source "$CONFIG_DIR/agent.env"
    export EC_GATEWAY_URL EC_GATEWAY_KEY EC_HEARTBEAT_INTERVAL EC_LOG_DIR
    exec "$INSTALL_DIR/venv/bin/python" "$INSTALL_DIR/agent.py"
fi

echo ""
echo -e "${GREEN}${BOLD}✓ Cài đặt hoàn tất!${NC}"
echo -e "  Dashboard: ${CYAN}http://${EC_GATEWAY_URL#http://*/}${NC}"
echo ""
