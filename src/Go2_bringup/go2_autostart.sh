#!/usr/bin/env bash
# Go2 一键启动脚本：传感器定位链路 + Nav2 + 局域网 Web UI（可选云端桥接）
#
# 启动顺序:
#   1. go2_nav_start.sh   — Livox + FastLIO + 定位 + scan 转换（后台）
#   2. run_nav2.sh        — Nav2 决策层 + cmd_vel 桥接（后台，等待 /scan 就绪）
#   3. run_web_bridge.sh  — 云端 WebSocket 桥接（默认关闭，服务器没开时跳过）
#   4. run_robot_web.sh   — 局域网 Web 控制台（rosbridge + Vite，默认开启）
#
# 环境变量（所有子脚本的环境变量均可透传）:
#   MAP_YAML            地图 yaml 路径（必填）
#   FASTLIO_LOC_PCD     定位地图 PCD（默认值见 go2_nav_start.sh）
#   SERVER_URL          WebSocket 服务器 URL（默认值见 run_web_bridge.sh）
#   NAV2_SKIP_BUILD     设为 1 跳过 colcon build
#   USE_RVIZ            是否启动 RViz（默认 false）
#   USE_WEB_BRIDGE      是否连云端 WebSocket（默认 false，服务器开后设 true）
#   USE_ROBOT_WEB       是否启动局域网 Web UI（默认 true，设 false 跳过）
#   ROBOT_WEB_DIR       Web 前端目录（默认见 run_robot_web.sh）
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
# 默认值：直接 bash go2_autostart.sh 即可，不用每次前面加 MAP_YAML=...
# 需要换地图时仍可通过环境变量覆盖：MAP_YAML=/path/to/other.yaml bash go2_autostart.sh
GO2_NAV_WS="$(cd "${SCRIPT_DIR}/../.." && pwd)"
MAP_YAML="${MAP_YAML:-${GO2_NAV_WS}/maps/MID360_map.yaml}"

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
    echo "用法: MAP_YAML=/path/to/maps.yaml bash $(basename "$0")"
    echo ""
    echo "环境变量:"
    echo "  MAP_YAML            地图 yaml 路径（必填）"
    echo "  FASTLIO_LOC_PCD     定位地图 PCD 路径"
    echo "  SERVER_URL          WebSocket 服务器 URL"
    echo "  NAV2_SKIP_BUILD     设为 1 跳过 colcon build（默认 1）"
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
    # 先发 SIGTERM，再等待
    for pid in "${CHILD_PIDS[@]:-}"; do
        [[ -z "${pid}" ]] && continue
        kill -TERM "${pid}" 2>/dev/null || true
    done

    local deadline=$(( $(date +%s) + 10 ))
    while (( $(date +%s) < deadline )); do
        local alive=0
        for pid in "${CHILD_PIDS[@]:-}"; do
            [[ -z "${pid}" ]] && continue
            kill -0 "${pid}" 2>/dev/null && alive=1 && break
        done
        (( alive == 0 )) && break
        sleep 0.5
    done

    # 超时后强制 SIGKILL
    for pid in "${CHILD_PIDS[@]:-}"; do
        [[ -z "${pid}" ]] && continue
        kill -9 "${pid}" 2>/dev/null || true
    done

    wait 2>/dev/null || true
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

    # ── 阶段 3：云端 WebSocket 桥接（默认关闭）───────────────────────────────
    # 服务器没开时设 false 跳过，避免反复重连刷屏。
    # 需要时显式启用：USE_WEB_BRIDGE=true bash go2_autostart.sh
    USE_WEB_BRIDGE="${USE_WEB_BRIDGE:-false}"
    WEB_PID=""
    if [[ "${USE_WEB_BRIDGE,,}" == "true" || "${USE_WEB_BRIDGE}" == "1" ]]; then
        log "[3/4] 启动云端 WebSocket 桥接（run_web_bridge.sh）..."
        bash "${SCRIPT_DIR}/run_web_bridge.sh" &
        WEB_PID=$!
        CHILD_PIDS+=("${WEB_PID}")
        ok "run_web_bridge.sh 已在后台启动，PID=${WEB_PID}"
    else
        log "[3/4] 跳过云端 WebSocket 桥接（USE_WEB_BRIDGE=${USE_WEB_BRIDGE}）"
    fi

    # ── 阶段 4：局域网 Web 控制台（rosbridge + Vite）────────────────────────
    USE_ROBOT_WEB="${USE_ROBOT_WEB:-true}"
    ROBOT_WEB_PID=""
    if [[ "${USE_ROBOT_WEB,,}" == "true" || "${USE_ROBOT_WEB}" == "1" ]]; then
        log "[4/4] 启动局域网 Web 控制台（run_robot_web.sh）..."
        bash "${SCRIPT_DIR}/run_robot_web.sh" &
        ROBOT_WEB_PID=$!
        CHILD_PIDS+=("${ROBOT_WEB_PID}")
        ok "run_robot_web.sh 已在后台启动，PID=${ROBOT_WEB_PID}"
    else
        log "[4/4] 跳过局域网 Web 控制台（USE_ROBOT_WEB=${USE_ROBOT_WEB}）"
    fi

    echo ""
    log "════════════════════════════════════════════════"
    ok "所有服务已启动，按 Ctrl+C 停止全部进程"
    log "日志目录: /tmp/go2_nav_bringup/"
    log "  传感器链路:   /tmp/go2_nav_bringup/livox.log, fast_lio.log, ..."
    [[ -n "${WEB_PID}" ]] && log "  云 WebSocket: /tmp/go2_nav_bringup/web_bridge.log"
    [[ -n "${ROBOT_WEB_PID}" ]] && log "  局域网 Web:   /tmp/go2_nav_bringup/rosbridge.log, robot_web.log"
    log "════════════════════════════════════════════════"

    # 等待 /tts_text 话题就绪后播报启动完成（最多等 60s）
    # 话题出现后再等 5s，让 tts_node 的 DDS 订阅关系完全建立，避免消息丢失
    local tts_deadline=$(( $(date +%s) + 60 ))
    while (( $(date +%s) < tts_deadline )); do
        if ros2 topic list 2>/dev/null | grep -Fxq "/tts_text"; then
            log "检测到 /tts_text，等待订阅者就绪..."
            sleep 5
            ros2 topic pub --once /tts_text std_msgs/msg/String \
                "{data: '导航系统已经启动'}" 2>/dev/null || true
            ok "TTS 播报已发送"
            break
        fi
        sleep 2
    done

    # 等待子进程，任意一个退出则报警并清理
    local exit_pid
    while true; do
        for pid in "${NAV_START_PID}" "${NAV2_PID}" "${WEB_PID}" "${ROBOT_WEB_PID}"; do
            [[ -z "${pid}" ]] && continue
            if ! kill -0 "${pid}" 2>/dev/null; then
                exit_pid="${pid}"
                break 2
            fi
        done
        sleep 2
    done
    err "子进程 PID=${exit_pid} 已意外退出，正在关闭所有服务..."
}

main "$@"
