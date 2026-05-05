#!/usr/bin/env bash
# Go2 一键启动脚本：传感器定位链路 + Nav2 + WebSocket 桥接
#
# 启动顺序:
#   1. go2_nav_start.sh  — Livox + FastLIO + 定位 + scan 转换（后台）
#   2. run_nav2.sh       — Nav2 决策层 + cmd_vel 桥接（后台，等待 /scan 就绪）
#   3. run_web_bridge.sh — WebSocket 桥接（后台，等待 /navigate_to_pose 就绪）
#
# 环境变量（所有子脚本的环境变量均可透传）:
#   MAP_YAML            地图 yaml 路径（必填）
#   FASTLIO_LOC_PCD     定位地图 PCD（默认值见 go2_nav_start.sh）
#   SERVER_URL          WebSocket 服务器 URL（默认值见 run_web_bridge.sh）
#   NAV2_SKIP_BUILD     设为 1 跳过 colcon build
#   USE_RVIZ            是否启动 RViz（默认 false）
#
# 用法:
#   MAP_YAML=/path/to/maps.yaml bash go2_autostart.sh
#   MAP_YAML=/path/to/maps.yaml SERVER_URL=ws://... bash go2_autostart.sh

set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# ── 颜色 ────────────────────────────────────────────────────────────────────
RED='\033[0;31m'
YELLOW='\033[1;33m'
GREEN='\033[0;32m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m'

log()  { echo -e "${BOLD}[$(date '+%H:%M:%S')] [AUTOSTART]${NC} $*"; }
ok()   { echo -e "${GREEN}[ OK $(date '+%H:%M:%S')] [AUTOSTART]${NC} $*"; }
warn() { echo -e "${YELLOW}[WARN $(date '+%H:%M:%S')] [AUTOSTART]${NC} $*"; }
err()  { echo -e "${RED}[ERR  $(date '+%H:%M:%S')] [AUTOSTART]${NC} $*" >&2; }

# ── 参数校验 ─────────────────────────────────────────────────────────────────
MAP_YAML="${MAP_YAML:-}"

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
    echo "用法: MAP_YAML=/path/to/maps.yaml bash $(basename "$0")"
    echo ""
    echo "环境变量:"
    echo "  MAP_YAML            地图 yaml 路径（必填）"
    echo "  FASTLIO_LOC_PCD     定位地图 PCD 路径"
    echo "  SERVER_URL          WebSocket 服务器 URL"
    echo "  NAV2_SKIP_BUILD     设为 1 跳过 colcon build（默认 0）"
    echo "  USE_RVIZ            启动 RViz（默认 false）"
    echo "  WAIT_TIMEOUT        节点/话题等待超时秒数（默认 60）"
    exit 0
fi

if [[ -z "${MAP_YAML}" ]]; then
    err "MAP_YAML 未设置。示例: MAP_YAML=/path/to/maps.yaml bash $0"
    exit 1
fi

if [[ ! -f "${MAP_YAML}" ]]; then
    err "地图文件不存在: ${MAP_YAML}"
    exit 1
fi

# ── 子进程管理 ───────────────────────────────────────────────────────────────
CHILD_PIDS=()

cleanup() {
    echo ""
    log "收到退出信号，停止所有子进程..."
    for pid in "${CHILD_PIDS[@]}"; do
        if kill -0 "${pid}" 2>/dev/null; then
            kill -TERM "${pid}" 2>/dev/null || true
        fi
    done

    local deadline=$(( $(date +%s) + 8 ))
    while (( $(date +%s) < deadline )); do
        local alive=0
        for pid in "${CHILD_PIDS[@]}"; do
            kill -0 "${pid}" 2>/dev/null && alive=1 && break
        done
        (( alive == 0 )) && break
        sleep 0.5
    done

    for pid in "${CHILD_PIDS[@]}"; do
        kill -9 "${pid}" 2>/dev/null || true
    done

    log "所有子进程已停止"
}
trap cleanup INT TERM EXIT

# ── 等待话题 ─────────────────────────────────────────────────────────────────
WAIT_TIMEOUT="${WAIT_TIMEOUT:-60}"
STATUS_INTERVAL=2

wait_for_topic() {
    local topic="$1"
    local timeout="${2:-${WAIT_TIMEOUT}}"
    local start
    start="$(date +%s)"
    log "等待话题 ${topic} ..."
    while true; do
        if ros2 topic list 2>/dev/null | grep -Fxq "${topic}"; then
            ok "话题就绪: ${topic}"
            return 0
        fi
        if (( "$(date +%s)" - start >= timeout )); then
            err "等待话题超时: ${topic}（${timeout}s）"
            return 1
        fi
        sleep "${STATUS_INTERVAL}"
    done
}

wait_for_action() {
    local action="$1"
    local timeout="${2:-${WAIT_TIMEOUT}}"
    local start
    start="$(date +%s)"
    log "等待 Action ${action} ..."
    while true; do
        if ros2 action list 2>/dev/null | grep -Fxq "${action}"; then
            ok "Action 就绪: ${action}"
            return 0
        fi
        if (( "$(date +%s)" - start >= timeout )); then
            warn "等待 Action 超时: ${action}（${timeout}s），继续启动 WebSocket 桥接"
            return 0
        fi
        sleep "${STATUS_INTERVAL}"
    done
}

# ── 主流程 ───────────────────────────────────────────────────────────────────
main() {
    log "════════════════════════════════════════════════"
    log "  Go2 全链路自动启动"
    log "  MAP_YAML=${MAP_YAML}"
    log "  脚本目录=${SCRIPT_DIR}"
    log "════════════════════════════════════════════════"

    # source ROS + Unitree DDS 环境，使本脚本的 ros2 命令（topic list/action list）
    # 与子进程使用相同的 RMW 和 CycloneDDS 配置，否则 wait_for_topic 永远看不到话题
    set +u
    source "/opt/ros/${ROS_DISTRO_NAME:-foxy}/setup.bash"
    if [[ -f "${HOME}/unitree_ros2/install/setup.bash" ]]; then
        source "${HOME}/unitree_ros2/install/setup.bash"
    fi
    if [[ -f "${HOME}/unitree_ros2/setup.sh" ]]; then
        source "${HOME}/unitree_ros2/setup.sh"
    fi
    set -u
    log "ROS 环境已加载，RMW=${RMW_IMPLEMENTATION:-默认}"

    # ── 阶段 1：传感器定位链路 ────────────────────────────────────────────────
    log "[1/3] 启动传感器定位链路（go2_nav_start.sh）..."
    NAV2_SKIP_BUILD="${NAV2_SKIP_BUILD:-1}" \
        bash "${SCRIPT_DIR}/go2_nav_start.sh" &
    NAV_START_PID=$!
    CHILD_PIDS+=("${NAV_START_PID}")
    ok "go2_nav_start.sh 已在后台启动，PID=${NAV_START_PID}"

    # 等待定位链路核心话题就绪后再启动 Nav2
    wait_for_topic "/scan"        "${WAIT_TIMEOUT}"
    wait_for_topic "/map_to_odom" "${WAIT_TIMEOUT}"

    # ── 阶段 2：Nav2 决策层 ───────────────────────────────────────────────────
    log "[2/3] 启动 Nav2 决策层（run_nav2.sh）..."
    MAP_YAML="${MAP_YAML}" \
    USE_RVIZ="${USE_RVIZ:-false}" \
    NAV2_SKIP_BUILD="${NAV2_SKIP_BUILD:-1}" \
        bash "${SCRIPT_DIR}/run_nav2.sh" &
    NAV2_PID=$!
    CHILD_PIDS+=("${NAV2_PID}")
    ok "run_nav2.sh 已在后台启动，PID=${NAV2_PID}"

    # 等待 Nav2 action 服务就绪
    wait_for_action "/navigate_to_pose" "${WAIT_TIMEOUT}"

    # ── 阶段 3：WebSocket 桥接 ────────────────────────────────────────────────
    log "[3/3] 启动 WebSocket 桥接（run_web_bridge.sh）..."
    bash "${SCRIPT_DIR}/run_web_bridge.sh" &
    WEB_PID=$!
    CHILD_PIDS+=("${WEB_PID}")
    ok "run_web_bridge.sh 已在后台启动，PID=${WEB_PID}"

    echo ""
    log "════════════════════════════════════════════════"
    ok "所有服务已启动，按 Ctrl+C 停止全部进程"
    log "日志目录: /tmp/go2_nav_bringup/"
    log "  传感器链路: /tmp/go2_nav_bringup/livox.log, fast_lio.log, ..."
    log "  WebSocket:  /tmp/go2_nav_bringup/web_bridge.log"
    log "════════════════════════════════════════════════"

    # 等待 TTS 节点就绪后播报启动完成提示
    sleep 5
    ros2 topic pub --once /tts_text std_msgs/msg/String \
        "data: '导航启动完毕，请你设置点位'" 2>/dev/null || true

    # 等待任意子进程退出时报警
    wait -n "${NAV_START_PID}" "${NAV2_PID}" "${WEB_PID}" 2>/dev/null || true
    err "某个子进程已意外退出，正在关闭所有服务..."
}

main "$@"
