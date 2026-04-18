#!/usr/bin/env bash
# Go2 PTP 时间同步脚本
# 用法: sudo bash time_sync_start.sh
# 功能: NTP 校准本机时钟 -> 启动 ptp4l Master -> 打印本机时间/雷达时间/误差

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WS_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
TIME_SYNC_DIR="${WS_ROOT}/src/Go2_time_sync"
CONFIG_FILE="${TIME_SYNC_DIR}/config/ptp_sync.yaml"
LIVOX_WS="/home/unitree/ws_Livox"
PTP4L_CFG="/tmp/ptp4l_go2.cfg"
PTP4L_LOG="/tmp/ptp4l_go2.log"

LIDAR_IP="192.168.1.129"
HOST_IP="192.168.1.50"
IFACE="eth0"
NTP_SERVER="ntp.aliyun.com"
PRINT_INTERVAL=5

if command -v python3 &>/dev/null && [[ -f "${CONFIG_FILE}" ]]; then
    _y() { python3 -c "import yaml; c=yaml.safe_load(open('${CONFIG_FILE}')); print(c$1)" 2>/dev/null || echo "$2"; }
    LIDAR_IP="$(_y "['lidar']['ip']"          "${LIDAR_IP}")"
    HOST_IP="$(_y  "['lidar']['host_ip']"     "${HOST_IP}")"
    IFACE="$(_y    "['network']['interface']" "${IFACE}")"
fi

RED='\033[0;31m'; YELLOW='\033[1;33m'; GREEN='\033[0;32m'
CYAN='\033[0;36m'; BOLD='\033[1m'; NC='\033[0m'

PTP4L_PID=""
MONITOR_PID=""

log()  { echo -e "${BOLD}[$(date '+%H:%M:%S')]${NC} $*"; }
warn() { echo -e "${YELLOW}[WARN $(date '+%H:%M:%S')]${NC} $*"; }
err()  { echo -e "${RED}[ERR  $(date '+%H:%M:%S')]${NC} $*" >&2; }

cleanup() {
    echo ""
    log "正在停止..."
    [[ -n "$MONITOR_PID" ]] && kill "$MONITOR_PID" 2>/dev/null || true
    [[ -n "$PTP4L_PID"   ]] && kill "$PTP4L_PID"   2>/dev/null || true
    wait 2>/dev/null || true
    rm -f "${PTP4L_CFG}"
    log "已退出"
}
trap cleanup EXIT INT TERM

[[ $EUID -eq 0 ]] || { err "需要 root 权限，请使用 sudo 运行"; exit 1; }

# source ROS2（sudo 下 PATH 不含 ros2）
set +u
for f in /opt/ros/foxy/setup.bash /opt/ros/humble/setup.bash; do
    [[ -f "$f" ]] && { source "$f"; break; }
done
set -u

# ── 步骤 1: NTP 校准 ──────────────────────────────────────────────────────────
echo -e "\n${CYAN}${BOLD}── 步骤 1/2 — NTP 本机时间校准 ──${NC}"
if [[ -f "${TIME_SYNC_DIR}/scripts/sync_host_time.py" ]]; then
    python3 "${TIME_SYNC_DIR}/scripts/sync_host_time.py" \
        --config "${CONFIG_FILE}" || warn "NTP 校准失败，继续"
fi

# ── 步骤 2: 启动 ptp4l ───────────────────────────────────────────────────────
echo -e "\n${CYAN}${BOLD}── 步骤 2/2 — 启动 PTP Master ──${NC}"

ts_mode="software"
if ethtool -T "${IFACE}" 2>/dev/null | grep -qi "hardware-transmit"; then
    ts_mode="hardware"
    log "网卡 ${IFACE} 支持硬件时间戳"
else
    warn "网卡 ${IFACE} 不支持硬件时间戳，使用软件时间戳"
fi
two_step=1; [[ "$ts_mode" == "hardware" ]] && two_step=0

cat > "${PTP4L_CFG}" <<EOF
[global]
domainNumber          0
priority1             128
priority2             128
clockClass            135
clockAccuracy         0xFE
offsetScaledLogVariance 0xFFFF
network_transport     UDPv4
delay_mechanism       E2E
time_stamping         ${ts_mode}
logSyncInterval       0
logAnnounceInterval   1
logMinDelayReqInterval 0
announceReceiptTimeout 3
twoStepFlag           ${two_step}
free_running          0
summary_interval      1
[${IFACE}]
EOF

ptp4l -f "${PTP4L_CFG}" -m >> "${PTP4L_LOG}" 2>&1 &
PTP4L_PID=$!
sleep 2
if ! kill -0 "${PTP4L_PID}" 2>/dev/null; then
    err "ptp4l 启动失败"; tail -5 "${PTP4L_LOG}" >&2; exit 1
fi
log "ptp4l 已启动 (PID=${PTP4L_PID})"

# 清理 fastrtps 共享内存，让 root 重新建立 DDS 连接
rm -f /dev/shm/fastrtps_* 2>/dev/null || true

# ── 步骤 3: 状态监控 ──────────────────────────────────────────────────────────
PYTHON_MONITOR=$(cat <<'PYEOF'
import subprocess, threading, time, datetime, socket, struct, os, re, sys

NTP_SERVER   = os.environ.get("NTP_SERVER",      "ntp.aliyun.com")
INTERVAL     = float(os.environ.get("PRINT_INTERVAL", "5"))
ROS_SETUP    = os.environ.get("ROS_SETUP",       "/opt/ros/foxy/setup.bash")
LIVOX_SETUP  = os.environ.get("LIVOX_SETUP",     "")

RED="\033[0;31m"; YELLOW="\033[1;33m"; GREEN="\033[0;32m"
CYAN="\033[0;36m"; BOLD="\033[1m"; DIM="\033[2m"; NC="\033[0m"

def color_off(ms):
    s = f"{ms:+.3f} ms"
    if abs(ms) < 1:    return f"{GREEN}{s}{NC}"
    elif abs(ms) < 10: return f"{YELLOW}{s}{NC}"
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

# 构建 source 前缀（以 unitree 用户身份运行 ros2 命令）
setups = [s for s in [ROS_SETUP, LIVOX_SETUP] if s and os.path.isfile(s)]
ROS_SRC = (" && ".join(f"source {s}" for s in setups) + " && ") if setups else ""

def ros2_cmd(cmd_suffix, timeout=6):
    try:
        r = subprocess.run(
            ["bash", "-c", ROS_SRC + cmd_suffix],
            capture_output=True, text=True, timeout=timeout
        )
        return r.stdout
    except Exception:
        return ""

# 直接从 ROS2 bag 格式读取 IMU 时间戳（通过 /livox/imu topic 的 ROS2 消息）
# 用 Python socket 监听 UDP 56401 端口获取 IMU 原始数据中的时间戳
_lock   = threading.Lock()
_imu_ns = None
_imu_hz = 0.0

def _imu_poll():
    """直接监听 UDP 56401 端口读取 Livox IMU 数据包中的时间戳"""
    global _imu_ns, _imu_hz
    HOST = "192.168.1.50"
    PORT = 56401
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        sock.bind((HOST, PORT))
    except OSError as e:
        # 端口被占用（livox_ros_driver2 在用），改用 SO_REUSEPORT
        try:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
            sock.bind((HOST, PORT))
        except Exception:
            return
    sock.settimeout(2.0)
    recv_times = []
    while True:
        try:
            data, _ = sock.recvfrom(4096)
            t_recv = time.time()
            # Livox IMU UDP 包：前 24 字节是 SdkPreamble
            # timestamp 在字节 4-11（uint64 小端，单位纳秒）
            if len(data) >= 36:
                ts_ns = struct.unpack_from('<Q', data, 28)[0]  # IMU 时间戳在 offset 28
                if 1_600_000_000 * 10**9 < ts_ns < 2_000_000_000 * 10**9:
                    recv_times.append(t_recv)
                    if len(recv_times) > 20:
                        recv_times.pop(0)
                    hz = 0.0
                    if len(recv_times) >= 2:
                        span = recv_times[-1] - recv_times[0]
                        if span > 0:
                            hz = (len(recv_times) - 1) / span
                    with _lock:
                        _imu_ns = ts_ns
                        _imu_hz = hz
        except socket.timeout:
            pass
        except Exception:
            time.sleep(1)

threading.Thread(target=_imu_poll, daemon=True).start()

print(f"\n{BOLD}{'═'*64}{NC}")
print(f"{BOLD}  Go2 时间同步状态监控{NC}  (NTP: {NTP_SERVER}  刷新: {INTERVAL}s)")
print(f"{BOLD}{'═'*64}{NC}\n")

iteration = 0
while True:
    iteration += 1
    t_host = time.time()
    t_ntp, rtt_ms = query_ntp(NTP_SERVER)
    with _lock:
        imu_ns = _imu_ns
        imu_hz = _imu_hz

    if iteration % 20 == 1:
        print(f"\n{CYAN}{'─'*64}{NC}")
        print(f"{CYAN}{BOLD}  {'时间源':<12} {'当前时间 (UTC)':<26} {'与主机误差'}{NC}")
        print(f"{CYAN}{'─'*64}{NC}")

    print(f"  {BOLD}{'主机':<12}{NC} {BOLD}{fmt_ts(t_host)}{NC}")

    if t_ntp is not None:
        off = (t_ntp - t_host) * 1000
        print(f"  {'NTP 云端':<12} {fmt_ts(t_ntp):<26} {color_off(off)}  RTT={rtt_ms:.0f}ms")
    else:
        print(f"  {'NTP 云端':<12} {'─':<26} {RED}查询失败{NC}")

    if imu_ns and imu_ns > 1_600_000_000 * 10**9:
        lidar_unix = imu_ns / 1e9
        off = (lidar_unix - t_host) * 1000
        print(f"  {'MID360':<12} {fmt_ts(lidar_unix):<26} {color_off(off)}  IMU {imu_hz:.0f}Hz")
    else:
        print(f"  {'MID360':<12} {'─':<26} {YELLOW}等待 /livox/imu ...{NC}")

    print()
    time.sleep(INTERVAL)
PYEOF
)

livox_setup=""
[[ -f "${LIVOX_WS}/install/setup.bash" ]] && livox_setup="${LIVOX_WS}/install/setup.bash"

NTP_SERVER="${NTP_SERVER}" PRINT_INTERVAL="${PRINT_INTERVAL}" \
ROS_SETUP="/opt/ros/foxy/setup.bash" LIVOX_SETUP="${livox_setup}" \
    python3 -c "${PYTHON_MONITOR}" &
MONITOR_PID=$!
log "监控已启动，按 Ctrl+C 停止"

wait "${MONITOR_PID}"
