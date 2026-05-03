#!/usr/bin/env bash
# Start Go2 WebSocket bridge to remote server.
#
# 功能:
#   - 将 /odom、/localization、/navigate_to_pose/_action/status 上报给服务器
#   - 接收服务器下发的导航目标点，发布到 /goal_pose 让 Nav2 执行
#   - 接收服务器下发的 TTS 文本，发布到 /tts_text 话题
#
# 终端颜色说明:
#   绿色 [TX]  — 机器人 → 服务器 发送的话题数据
#   红色 [RX]  — 服务器 → 机器人 接收的消息
#   青色       — 连接状态
#
# 用法示例:
#   bash run_web_bridge.sh
#   SERVER_URL="ws://..." ODOM_HZ=1.0 bash run_web_bridge.sh

set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEFAULT_GO2_WS="$(cd "${SCRIPT_DIR}/../.." && pwd)"

ROS_DISTRO_NAME="${ROS_DISTRO_NAME:-foxy}"
ROS_SETUP="${ROS_SETUP:-/opt/ros/${ROS_DISTRO_NAME}/setup.bash}"
GO2_NAV_WS="${GO2_NAV_WS:-${DEFAULT_GO2_WS}}"

SERVER_URL="${SERVER_URL:-ws://121.40.212.85:30100/ws/source?token=c7e4a9d2b5f1c8e3a6d4b7f2c9a1e5d8&source_id=dog_001}"
ODOM_HZ="${ODOM_HZ:-2.0}"
NAV_STATUS_HZ="${NAV_STATUS_HZ:-1.0}"
RECONNECT_DELAY="${RECONNECT_DELAY:-5.0}"
TTS_ALSA_DEVICE="${TTS_ALSA_DEVICE:-plughw:2,0}"
TTS_LANGUAGE="${TTS_LANGUAGE:-zh}"
TTS_SPEED="${TTS_SPEED:-150}"
TTS_AMPLITUDE="${TTS_AMPLITUDE:-100}"

LOG_DIR="${LOG_DIR:-/tmp/go2_nav_bringup}"
mkdir -p "${LOG_DIR}"
LOG_FILE="${LOG_DIR}/web_bridge.log"

RED='\033[0;31m'
YELLOW='\033[1;33m'
GREEN='\033[0;32m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m'

log()  { echo -e "${BOLD}[$(date '+%H:%M:%S')]${NC} $*"; }
ok()   { echo -e "${GREEN}[ OK $(date '+%H:%M:%S')]${NC} $*"; }
warn() { echo -e "${YELLOW}[WARN $(date '+%H:%M:%S')]${NC} $*"; }
err()  { echo -e "${RED}[ERR  $(date '+%H:%M:%S')]${NC} $*" >&2; }

PID=""
PGID=""
TAIL_PID=""

cleanup() {
    echo ""
    log "停止 WebSocket 桥接..."
    [[ -n "${TAIL_PID}" ]] && kill "${TAIL_PID}" 2>/dev/null || true
    if [[ -n "${PGID}" ]]; then
        kill -- "-${PGID}" 2>/dev/null || true
        sleep 1
        kill -9 -- "-${PGID}" 2>/dev/null || true
    fi
    pkill -9 -f "web_bridge_node" 2>/dev/null || true
    pkill -9 -f "tts_node" 2>/dev/null || true
    log "已退出"
}
trap cleanup INT TERM EXIT

source_if_exists() {
    local setup_file="$1" label="$2"
    if [[ ! -f "${setup_file}" ]]; then
        err "找不到 ${label}: ${setup_file}"
        exit 1
    fi
    set +u
    # shellcheck source=/dev/null
    source "${setup_file}"
    set -u
    ok "已 source ${label}: ${setup_file}"
}

check_prerequisites() {
    local missing=0
    for topic in /odom /localization; do
        if ! ros2 topic list 2>/dev/null | grep -Fxq "${topic}"; then
            warn "话题 ${topic} 不存在，请先确认导航链路已启动"
            missing=1
        fi
    done
    if ! ros2 action list 2>/dev/null | grep -Fxq "/navigate_to_pose"; then
        warn "Action /navigate_to_pose 不存在，请先确认 Nav2 已启动"
        missing=1
    fi
    if (( missing )); then
        warn "部分依赖未就绪，节点将在连接后自动重试"
    else
        ok "前置依赖检查通过"
    fi
}

check_websockets_lib() {
    if ! python3 -c "import websockets" 2>/dev/null; then
        warn "缺少 Python 库 websockets，正在安装..."
        pip3 install "websockets>=10.0" --quiet
        ok "websockets 安装完成"
    fi
}

# 实时跟踪日志并着色：[TX] 绿、[RX] 红、连接状态青色、其余白色
tail_colored() {
    tail -f "${LOG_FILE}" | while IFS= read -r line; do
        if [[ "${line}" == *'[TX]'* ]]; then
            echo -e "${GREEN}${line}${NC}"
        elif [[ "${line}" == *'[RX]'* ]]; then
            echo -e "${RED}${line}${NC}"
        elif [[ "${line}" == *'[WebBridge]'* ]]; then
            echo -e "${CYAN}${line}${NC}"
        else
            echo "${line}"
        fi
    done
}

main() {
    log "Go2 WebSocket 桥接启动"
    log "GO2_NAV_WS=${GO2_NAV_WS}"
    log "SERVER_URL=${SERVER_URL}"
    log "上行: /odom(${ODOM_HZ}Hz)  /localization(${NAV_STATUS_HZ}Hz)  /navigate_to_pose/_action/status"
    log "下行: /goal_pose  /initialpose  /tts_text"
    log "TTS:  设备=${TTS_ALSA_DEVICE}  语言=${TTS_LANGUAGE}  语速=${TTS_SPEED}"

    source_if_exists "${ROS_SETUP}" "ROS 2"
    source_if_exists "${GO2_NAV_WS}/install/setup.bash" "Go2_Nav 工作空间"

    check_websockets_lib
    check_prerequisites

    # 启动节点（后台，输出写入日志文件）
    : > "${LOG_FILE}"   # 清空旧日志
    setsid ros2 launch Go2_web_bridge web_bridge.launch.py \
        "server_url:=${SERVER_URL}" \
        "odom_publish_hz:=${ODOM_HZ}" \
        "nav_status_publish_hz:=${NAV_STATUS_HZ}" \
        "reconnect_delay_sec:=${RECONNECT_DELAY}" \
        "tts_alsa_device:=${TTS_ALSA_DEVICE}" \
        "tts_language:=${TTS_LANGUAGE}" \
        "tts_speed:=${TTS_SPEED}" \
        "tts_amplitude:=${TTS_AMPLITUDE}" \
        > "${LOG_FILE}" 2>&1 &

    PID=$!
    PGID=$(ps -o pgid= -p "${PID}" 2>/dev/null | tr -d ' ') || PGID="${PID}"
    ok "web_bridge_node 已启动 PID=${PID}  日志: ${LOG_FILE}"
    echo ""
    echo -e "${GREEN}■ 绿色 = 上行数据（机器人→服务器）${NC}   ${RED}■ 红色 = 下行数据（服务器→机器人）${NC}"
    echo -e "${CYAN}■ 青色 = 连接状态${NC}"
    echo "────────────────────────────────────────────────────────"

    # 等待日志文件被写入后开始 tail
    sleep 1
    tail_colored &
    TAIL_PID=$!

    wait "${PID}"
}

main "$@"
