#!/usr/bin/env bash
# Go2 局域网 Web 控制台启动脚本
#
# 启动两个服务：
#   1. rosbridge_websocket  (默认端口 9090)
#       将 ROS2 话题/服务通过 WebSocket 暴露给浏览器
#   2. vite dev server      (默认端口 5173，监听 0.0.0.0)
#       怡和小众 AMR 控制台前端
#
# 局域网访问方式：
#   浏览器打开 http://<机器狗局域网IP>:5173
#   登录页填入机器狗 IP 和 9090 端口连接 rosbridge
#
# 用法:
#   bash run_robot_web.sh
#   ROBOT_WEB_DIR=/path/to/web bash run_robot_web.sh

set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

ROS_DISTRO_NAME="${ROS_DISTRO_NAME:-foxy}"
ROS_SETUP="${ROS_SETUP:-/opt/ros/${ROS_DISTRO_NAME}/setup.bash}"

ROBOT_WEB_DIR="${ROBOT_WEB_DIR:-/home/unitree/unitree_ros2/qiaojie/robot_ros2_web}"
ROSBRIDGE_PORT="${ROSBRIDGE_PORT:-9090}"
WEB_DEV_PORT="${WEB_DEV_PORT:-5173}"

# Node 安装位置不一定在系统 PATH 里
NODE_BIN_DIR="${NODE_BIN_DIR:-${HOME}/.local/node/v20.19.1/bin}"
if [[ -d "${NODE_BIN_DIR}" ]]; then
    export PATH="${NODE_BIN_DIR}:${PATH}"
fi

LOG_DIR="${LOG_DIR:-/tmp/go2_nav_bringup}"
mkdir -p "${LOG_DIR}"
ROSBRIDGE_LOG="${LOG_DIR}/rosbridge.log"
WEB_LOG="${LOG_DIR}/robot_web.log"

RED='\033[0;31m'
YELLOW='\033[1;33m'
GREEN='\033[0;32m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m'

log()  { echo -e "${BOLD}[$(date '+%H:%M:%S')] [WEB]${NC} $*"; }
ok()   { echo -e "${GREEN}[ OK $(date '+%H:%M:%S')] [WEB]${NC} $*"; }
warn() { echo -e "${YELLOW}[WARN $(date '+%H:%M:%S')] [WEB]${NC} $*"; }
err()  { echo -e "${RED}[ERR  $(date '+%H:%M:%S')] [WEB]${NC} $*" >&2; }

ROSBRIDGE_PID=""
WEB_PID=""
ROSBRIDGE_PGID=""
WEB_PGID=""

cleanup() {
    echo ""
    log "停止 robot_web..."
    for pgid in "${ROSBRIDGE_PGID}" "${WEB_PGID}"; do
        [[ -z "${pgid}" ]] && continue
        kill -- "-${pgid}" 2>/dev/null || true
    done
    sleep 1
    for pgid in "${ROSBRIDGE_PGID}" "${WEB_PGID}"; do
        [[ -z "${pgid}" ]] && continue
        kill -9 -- "-${pgid}" 2>/dev/null || true
    done
    pkill -9 -f "rosbridge_websocket" 2>/dev/null || true
    pkill -9 -f "vite" 2>/dev/null || true
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
}

show_lan_ips() {
    echo ""
    echo -e "${CYAN}════════════════════════════════════════════${NC}"
    echo -e "${BOLD}局域网访问地址：${NC}"
    local ips
    ips=$(hostname -I 2>/dev/null || true)
    for ip in ${ips}; do
        # 跳过 docker/loopback 网段
        [[ "${ip}" == 172.17.* || "${ip}" == 127.* ]] && continue
        echo -e "  ${GREEN}http://${ip}:${WEB_DEV_PORT}${NC}"
    done
    echo ""
    echo -e "${BOLD}rosbridge WebSocket：${NC} ws://<同上 IP>:${ROSBRIDGE_PORT}"
    echo -e "${CYAN}════════════════════════════════════════════${NC}"
    echo ""
}

main() {
    log "Go2 Web 控制台启动"
    log "ROBOT_WEB_DIR=${ROBOT_WEB_DIR}"

    if [[ ! -d "${ROBOT_WEB_DIR}" ]]; then
        err "Web 前端目录不存在: ${ROBOT_WEB_DIR}"
        exit 1
    fi
    if [[ ! -f "${ROBOT_WEB_DIR}/package.json" ]]; then
        err "目录不是 npm 项目（缺 package.json）: ${ROBOT_WEB_DIR}"
        exit 1
    fi

    if ! command -v node >/dev/null 2>&1; then
        err "找不到 node 命令；NODE_BIN_DIR=${NODE_BIN_DIR}"
        exit 1
    fi
    if ! command -v npm >/dev/null 2>&1; then
        err "找不到 npm 命令"
        exit 1
    fi

    source_if_exists "${ROS_SETUP}" "ROS 2"

    # 阶段 1：rosbridge_websocket
    log "[1/2] 启动 rosbridge_websocket（端口 ${ROSBRIDGE_PORT}）..."
    : > "${ROSBRIDGE_LOG}"
    setsid ros2 run rosbridge_server rosbridge_websocket \
        --ros-args -p port:="${ROSBRIDGE_PORT}" \
        > "${ROSBRIDGE_LOG}" 2>&1 &
    ROSBRIDGE_PID=$!
    ROSBRIDGE_PGID=$(ps -o pgid= -p "${ROSBRIDGE_PID}" 2>/dev/null | tr -d ' ') \
        || ROSBRIDGE_PGID="${ROSBRIDGE_PID}"
    ok "rosbridge_websocket PID=${ROSBRIDGE_PID}  日志: ${ROSBRIDGE_LOG}"

    # 阶段 2：Vite dev server（npm run dev）
    log "[2/2] 启动 Vite 前端（端口 ${WEB_DEV_PORT}）..."
    : > "${WEB_LOG}"
    setsid bash -c "cd '${ROBOT_WEB_DIR}' && npm run dev -- --port ${WEB_DEV_PORT} --host 0.0.0.0" \
        > "${WEB_LOG}" 2>&1 &
    WEB_PID=$!
    WEB_PGID=$(ps -o pgid= -p "${WEB_PID}" 2>/dev/null | tr -d ' ') \
        || WEB_PGID="${WEB_PID}"
    ok "vite dev PID=${WEB_PID}  日志: ${WEB_LOG}"

    # 等待 vite 起来（最多 30s）
    local deadline=$(( $(date +%s) + 30 ))
    while (( $(date +%s) < deadline )); do
        if grep -q "ready in\|Local:" "${WEB_LOG}" 2>/dev/null; then
            ok "Vite dev server ready"
            break
        fi
        sleep 1
    done

    show_lan_ips
    log "服务持续运行中，按 Ctrl+C 停止"

    # 守护：任意一个进程退出则清理
    while true; do
        if ! kill -0 "${ROSBRIDGE_PID}" 2>/dev/null; then
            err "rosbridge_websocket 已退出，详见 ${ROSBRIDGE_LOG}"
            exit 1
        fi
        if ! kill -0 "${WEB_PID}" 2>/dev/null; then
            err "vite dev 已退出，详见 ${WEB_LOG}"
            exit 1
        fi
        sleep 5
    done
}

main "$@"
