#!/usr/bin/env bash
# Go2 时间同步脚本
# 用法: sudo bash time_sync_start.sh
# 功能: NTP 校准本机时钟 -> 打印本机时间/雷达时间/误差

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WS_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
TIME_SYNC_DIR="${WS_ROOT}/src/Go2_time_sync"
CONFIG_FILE="${TIME_SYNC_DIR}/config/ptp_sync.yaml"
NVIDIA_HOME="${NVIDIA_HOME:-/home/nvidia}"
LIVOX_WS="${LIVOX_WS:-${NVIDIA_HOME}/ws_Livox}"

DEFAULT_LIDAR_IP="192.168.1.12"
DEFAULT_HOST_IP="192.168.1.5"
DEFAULT_IFACE="eth0"

if command -v python3 &>/dev/null && [[ -f "${CONFIG_FILE}" ]]; then
    _y() { python3 -c "import yaml; c=yaml.safe_load(open('${CONFIG_FILE}')); print(c$1)" 2>/dev/null || echo "$2"; }
    DEFAULT_LIDAR_IP="$(_y "['lidar']['ip']"      "${DEFAULT_LIDAR_IP}")"
    DEFAULT_HOST_IP="$(_y  "['lidar']['host_ip']" "${DEFAULT_HOST_IP}")"
    DEFAULT_IFACE="$(_y    "['network']['interface']" "${DEFAULT_IFACE}")"
fi

LIDAR_IP="${LIDAR_IP:-${DEFAULT_LIDAR_IP}}"
HOST_IP="${HOST_IP:-${DEFAULT_HOST_IP}}"
IFACE="${IFACE:-${DEFAULT_IFACE}}"
NTP_SERVER="${NTP_SERVER:-ntp.aliyun.com}"
PRINT_INTERVAL="${PRINT_INTERVAL:-5}"

RED='\033[0;31m'; YELLOW='\033[1;33m'; GREEN='\033[0;32m'
CYAN='\033[0;36m'; BOLD='\033[1m'; NC='\033[0m'

MONITOR_PID=""
PTP4L_PID=""

log()  { echo -e "${BOLD}[$(date '+%H:%M:%S')]${NC} $*"; }
warn() { echo -e "${YELLOW}[WARN $(date '+%H:%M:%S')]${NC} $*"; }
err()  { echo -e "${RED}[ERR  $(date '+%H:%M:%S')]${NC} $*" >&2; }

cleanup() {
    echo ""
    log "正在停止..."
    [[ -n "$MONITOR_PID" ]] && kill "$MONITOR_PID" 2>/dev/null || true
    [[ -n "$PTP4L_PID"   ]] && kill "$PTP4L_PID"   2>/dev/null || true
    wait 2>/dev/null || true
    log "已退出"
}
trap cleanup EXIT INT TERM

[[ $EUID -eq 0 ]] || { err "需要 root 权限，请使用 sudo 运行"; exit 1; }

# ── 步骤 1: NTP 校准 ──────────────────────────────────────────────────────────
echo -e "\n${CYAN}${BOLD}── NTP 本机时间校准 ──${NC}"
if [[ -f "${TIME_SYNC_DIR}/scripts/sync_host_time.py" ]]; then
    python3 "${TIME_SYNC_DIR}/scripts/sync_host_time.py" \
        --config "${CONFIG_FILE}" || warn "NTP 校准失败，继续"
fi

# ── 步骤 2: 启动 ptp4l PTP Master ────────────────────────────────────────────
echo -e "\n${CYAN}${BOLD}── 启动 PTP Master (ptp4l) ──${NC}"

PTP4L_CFG="/tmp/ptp4l_${IFACE}.cfg"
cat > "${PTP4L_CFG}" <<PTPCFG
[global]
domainNumber          0
priority1             10
priority2             10
clockClass            135
clockAccuracy         0xFE
offsetScaledLogVariance 0xFFFF
network_transport     UDPv4
delay_mechanism       E2E
time_stamping         software
logSyncInterval       0
logAnnounceInterval   1
logMinDelayReqInterval 0
announceReceiptTimeout 3
twoStepFlag           1
free_running          0
summary_interval      1

[${IFACE}]
PTPCFG

# 加入 PTP 组播组，确保雷达能收到 Announce/Sync 报文
ip maddr add 224.0.1.129 dev "${IFACE}" 2>/dev/null || true
ip maddr add 224.0.0.107 dev "${IFACE}" 2>/dev/null || true
log "已加入 PTP 组播组 (接口=${IFACE})"

ptp4l -f "${PTP4L_CFG}" -m >> /tmp/ptp4l.log 2>&1 &
PTP4L_PID=$!
log "ptp4l 已启动 (PID=${PTP4L_PID}, 接口=${IFACE}，日志: /tmp/ptp4l.log)"
sleep 2

# 清理 fastrtps 共享内存
rm -f /dev/shm/fastrtps_* 2>/dev/null || true

# ── 步骤 3: 状态监控 ──────────────────────────────────────────────────────────
PYTHON_MONITOR=$(cat <<'PYEOF'
import time, datetime, socket, struct, os

NTP_SERVER = os.environ.get("NTP_SERVER",   "ntp.aliyun.com")
INTERVAL   = float(os.environ.get("PRINT_INTERVAL", "5"))

RED="\033[0;31m"; YELLOW="\033[1;33m"; GREEN="\033[0;32m"
CYAN="\033[0;36m"; BOLD="\033[1m"; NC="\033[0m"

def color_off(ms):
    s = f"{ms:+.1f} ms"
    if abs(ms) < 10:   return f"{GREEN}{s}{NC}"
    elif abs(ms) < 50: return f"{YELLOW}{s}{NC}"
    else:              return f"{RED}{s}{NC}"

def fmt_ts(unix_ts):
    dt = datetime.datetime.utcfromtimestamp(unix_ts)
    return dt.strftime("%Y-%m-%d %H:%M:%S.") + f"{dt.microsecond//1000:03d}"

NTP_DELTA = 2208988800
def query_ntp(server, timeout=3):
    try:
        pkt = bytearray(48); pkt[0] = 0b00011011
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.settimeout(timeout)
        t0 = time.time()
        s.sendto(bytes(pkt), (server, 123))
        data, _ = s.recvfrom(1024)
        t1 = time.time(); s.close()
        sec, frac = struct.unpack("!II", data[40:48])
        ntp = sec - NTP_DELTA + frac / (2**32)
        return ntp + (t1 - t0) / 2, (t1 - t0) * 1000
    except Exception:
        return None, None

print(f"\n{BOLD}{'═'*60}{NC}")
print(f"{BOLD}  Go2 时间监控{NC}  (NTP: {NTP_SERVER}  刷新: {INTERVAL}s)")
print(f"{BOLD}{'═'*60}{NC}\n")

iteration = 0
while True:
    iteration += 1
    t_host = time.time()
    t_ntp, rtt_ms = query_ntp(NTP_SERVER)

    if iteration % 20 == 1:
        print(f"\n{CYAN}{'─'*60}{NC}")
        print(f"{CYAN}{BOLD}  {'时间源':<10} {'当前时间 (UTC)':<26} {'与主机误差'}{NC}")
        print(f"{CYAN}{'─'*60}{NC}")

    print(f"  {BOLD}{'主机':<10}{NC} {BOLD}{fmt_ts(t_host)}{NC}")

    if t_ntp is not None:
        off = (t_ntp - t_host) * 1000
        print(f"  {'NTP':<10} {fmt_ts(t_ntp):<26} {color_off(off)}  RTT={rtt_ms:.0f}ms")
    else:
        print(f"  {'NTP':<10} {'─':<26} {RED}查询失败{NC}")

    print()
    time.sleep(INTERVAL)
PYEOF
)

NTP_SERVER="${NTP_SERVER}" PRINT_INTERVAL="${PRINT_INTERVAL}" \
    python3 -c "${PYTHON_MONITOR}" &
MONITOR_PID=$!
log "监控已启动，按 Ctrl+C 停止"

wait "${MONITOR_PID}"
