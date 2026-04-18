#!/usr/bin/env bash
# Go2 时间同步脚本
# 用法: sudo bash time_sync_start.sh
# 功能: NTP 校准本机时钟 -> 打印本机时间/雷达时间/误差

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WS_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
TIME_SYNC_DIR="${WS_ROOT}/src/Go2_time_sync"
CONFIG_FILE="${TIME_SYNC_DIR}/config/ptp_sync.yaml"
LIVOX_WS="/home/unitree/ws_Livox"

LIDAR_IP="192.168.1.129"
HOST_IP="192.168.1.50"
NTP_SERVER="ntp.aliyun.com"
PRINT_INTERVAL=5

if command -v python3 &>/dev/null && [[ -f "${CONFIG_FILE}" ]]; then
    _y() { python3 -c "import yaml; c=yaml.safe_load(open('${CONFIG_FILE}')); print(c$1)" 2>/dev/null || echo "$2"; }
    LIDAR_IP="$(_y "['lidar']['ip']"      "${LIDAR_IP}")"
    HOST_IP="$(_y  "['lidar']['host_ip']" "${HOST_IP}")"
fi

RED='\033[0;31m'; YELLOW='\033[1;33m'; GREEN='\033[0;32m'
CYAN='\033[0;36m'; BOLD='\033[1m'; NC='\033[0m'

MONITOR_PID=""

log()  { echo -e "${BOLD}[$(date '+%H:%M:%S')]${NC} $*"; }
warn() { echo -e "${YELLOW}[WARN $(date '+%H:%M:%S')]${NC} $*"; }
err()  { echo -e "${RED}[ERR  $(date '+%H:%M:%S')]${NC} $*" >&2; }

cleanup() {
    echo ""
    log "正在停止..."
    [[ -n "$MONITOR_PID" ]] && kill "$MONITOR_PID" 2>/dev/null || true
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

# 清理 fastrtps 共享内存
rm -f /dev/shm/fastrtps_* 2>/dev/null || true

# ── 步骤 2: 状态监控 ──────────────────────────────────────────────────────────
PYTHON_MONITOR=$(cat <<'PYEOF'
import threading, time, datetime, socket, struct, os

NTP_SERVER = os.environ.get("NTP_SERVER",      "ntp.aliyun.com")
INTERVAL   = float(os.environ.get("PRINT_INTERVAL", "5"))
HOST_IP    = os.environ.get("HOST_IP",         "192.168.1.50")

RED="\033[0;31m"; YELLOW="\033[1;33m"; GREEN="\033[0;32m"
CYAN="\033[0;36m"; BOLD="\033[1m"; NC="\033[0m"

def color_off(ms):
    s = f"{ms:+.1f} ms"
    if abs(ms) < 10:  return f"{GREEN}{s}{NC}"
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

_lock   = threading.Lock()
_imu_ns = None
_imu_hz = 0.0

def _imu_poll():
    global _imu_ns, _imu_hz
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
    sock.bind((HOST_IP, 56401))
    sock.settimeout(2.0)
    recv_times = []
    while True:
        try:
            data, _ = sock.recvfrom(4096)
            t_recv = time.time()
            if len(data) >= 36:
                ts_ns = struct.unpack_from('<Q', data, 28)[0]
                if 1_600_000_000 * 10**9 < ts_ns < 2_000_000_000 * 10**9:
                    recv_times.append(t_recv)
                    if len(recv_times) > 20:
                        recv_times.pop(0)
                    hz = (len(recv_times)-1)/(recv_times[-1]-recv_times[0]) if len(recv_times) >= 2 else 0.0
                    with _lock:
                        _imu_ns = ts_ns
                        _imu_hz = hz
        except socket.timeout:
            pass
        except Exception:
            time.sleep(1)

threading.Thread(target=_imu_poll, daemon=True).start()

print(f"\n{BOLD}{'═'*60}{NC}")
print(f"{BOLD}  Go2 时间监控{NC}  (NTP: {NTP_SERVER}  刷新: {INTERVAL}s)")
print(f"{BOLD}{'═'*60}{NC}\n")

iteration = 0
while True:
    iteration += 1
    t_host = time.time()
    t_ntp, rtt_ms = query_ntp(NTP_SERVER)
    with _lock:
        imu_ns = _imu_ns
        imu_hz = _imu_hz

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

    if imu_ns and imu_ns > 1_600_000_000 * 10**9:
        lidar_unix = imu_ns / 1e9
        off = (lidar_unix - t_host) * 1000
        print(f"  {'MID360':<10} {fmt_ts(lidar_unix):<26} {color_off(off)}  IMU {imu_hz:.0f}Hz")
    else:
        print(f"  {'MID360':<10} {'─':<26} {YELLOW}等待数据...{NC}")

    print()
    time.sleep(INTERVAL)
PYEOF
)

livox_setup=""
[[ -f "${LIVOX_WS}/install/setup.bash" ]] && livox_setup="${LIVOX_WS}/install/setup.bash"

NTP_SERVER="${NTP_SERVER}" PRINT_INTERVAL="${PRINT_INTERVAL}" HOST_IP="${HOST_IP}" \
    python3 -c "${PYTHON_MONITOR}" &
MONITOR_PID=$!
log "监控已启动，按 Ctrl+C 停止"

wait "${MONITOR_PID}"
