#!/usr/bin/env bash
# Start Go2 MID360 + FAST-LIO2 + FAST-LIO-Localization + Nav2 input conversion chain.
#
# Startup order:
#   1. livox_ros_driver2 msg_MID360_launch.py
#   2. fast_lio mapping.launch.py  (提供 /Odometry + /cloud_registered (world帧) + /cloud_registered_body (body帧))
#   3. odom_tf_bridge odom_bridge.launch.py  (odom->base_link TF + /odom)
#   4. fast_lio_localization_ros2 localize_go2.launch.py  (map->odom TF，替代 HDL)
#   5. go2_pc2scan pc2scan.launch.py
#
# Common overrides:
#   LIVOX_WS=/home/unitree/ws_Livox \
#   FASTLIO_WS=/home/unitree/ws_fastlio2 \
#   GO2_NAV_WS=/home/unitree/Go2_Nav_ws \
#   FASTLIO_CONFIG=/home/unitree/ws_fastlio2/src/FAST_LIO_ROS2/config/mid360.yaml \
#   FASTLIO_LOC_PCD=/path/to/map.pcd \
#   bash go2_nav_start.sh

set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEFAULT_GO2_WS="$(cd "${SCRIPT_DIR}/../.." && pwd)"

ROS_DISTRO_NAME="${ROS_DISTRO_NAME:-foxy}"
ROS_SETUP="${ROS_SETUP:-/opt/ros/${ROS_DISTRO_NAME}/setup.bash}"

GO2_NAV_WS="${GO2_NAV_WS:-${DEFAULT_GO2_WS}}"
LIVOX_WS="${LIVOX_WS:-${HOME}/ws_Livox}"
FASTLIO_WS="${FASTLIO_WS:-${HOME}/ws_fastlio2}"
FASTLIO_CONFIG="${FASTLIO_CONFIG:-${FASTLIO_WS}/src/FAST_LIO_ROS2/config/mid360.yaml}"
FASTLIO_LOC_PCD="${FASTLIO_LOC_PCD:-${GO2_NAV_WS}/src/Go2_localization/PCD/MID360.pcd}"

RVIZ="${RVIZ:-false}"
WAIT_TIMEOUT="${WAIT_TIMEOUT:-30}"
STATUS_INTERVAL="${STATUS_INTERVAL:-2}"

LOG_DIR="${LOG_DIR:-/tmp/go2_nav_bringup}"
mkdir -p "${LOG_DIR}"

PIDS=()
PGIDS=()

RED='\033[0;31m'
YELLOW='\033[1;33m'
GREEN='\033[0;32m'
BOLD='\033[1m'
NC='\033[0m'

log() {
    echo -e "${BOLD}[$(date '+%H:%M:%S')]${NC} $*"
}

ok() {
    echo -e "${GREEN}[ OK $(date '+%H:%M:%S')]${NC} $*"
}

warn() {
    echo -e "${YELLOW}[WARN $(date '+%H:%M:%S')]${NC} $*"
}

err() {
    echo -e "${RED}[ERR  $(date '+%H:%M:%S')]${NC} $*" >&2
}

cleanup() {
    echo ""
    log "停止 Go2 导航启动链路..."

    # 第一轮：SIGTERM 各进程组
    for pgid in "${PGIDS[@]}"; do
        kill -- "-${pgid}" 2>/dev/null || true
    done

    # 等待最多 5 秒
    local deadline=$(( $(date +%s) + 5 ))
    while (( $(date +%s) < deadline )); do
        local alive=0
        for pid in "${PIDS[@]}"; do
            kill -0 "${pid}" 2>/dev/null && alive=1 && break
        done
        (( alive == 0 )) && break
        sleep 0.5
    done

    # 第二轮：SIGKILL 各进程组
    for pgid in "${PGIDS[@]}"; do
        kill -9 -- "-${pgid}" 2>/dev/null || true
    done

    # 兜底：按进程名强制清理 ros2 launch fork 出的子进程
    pkill -9 -f "livox_ros_driver2_node"  2>/dev/null || true
    pkill -9 -f "laser_mapping"           2>/dev/null || true
    pkill -9 -f "odom_tf_bridge_node"     2>/dev/null || true
    pkill -9 -f "pcd_publisher"           2>/dev/null || true
    pkill -9 -f "global_localization_ros2" 2>/dev/null || true
    pkill -9 -f "transform_fusion_ros2"   2>/dev/null || true
    pkill -9 -f "global_localization"     2>/dev/null || true
    pkill -9 -f "transform_fusion"        2>/dev/null || true
    pkill -9 -f "cloud_filter_node"       2>/dev/null || true
    pkill -9 -f "pointcloud_to_laserscan_node" 2>/dev/null || true
    pkill -9 -f "static_transform_publisher"   2>/dev/null || true

    wait 2>/dev/null || true
    log "已退出"
}
trap cleanup INT TERM EXIT

source_if_exists() {
    local setup_file="$1"
    local label="$2"

    if [[ ! -f "${setup_file}" ]]; then
        err "找不到 ${label}: ${setup_file}"
        exit 1
    fi

    # ROS setup scripts reference variables (e.g. AMENT_TRACE_SETUP_FILES) that
    # may be unset; temporarily disable -u to avoid spurious "unbound variable" errors.
    set +u
    # shellcheck source=/dev/null
    source "${setup_file}"
    set -u
    ok "已 source ${label}: ${setup_file}"
}

require_file() {
    local path="$1"
    local label="$2"

    if [[ ! -f "${path}" ]]; then
        err "找不到 ${label}: ${path}"
        exit 1
    fi
}

require_command() {
    local cmd="$1"

    if ! command -v "${cmd}" >/dev/null 2>&1; then
        err "找不到命令: ${cmd}"
        exit 1
    fi
}

wait_for_node() {
    local node_name="$1"
    local timeout="${2:-${WAIT_TIMEOUT}}"
    local start
    start="$(date +%s)"

    log "等待节点 ${node_name} ..."
    while true; do
        if ros2 node list 2>/dev/null | grep -Fxq "${node_name}"; then
            ok "节点已启动: ${node_name}"
            return 0
        fi

        if (( "$(date +%s)" - start >= timeout )); then
            err "等待节点超时: ${node_name}"
            return 1
        fi

        sleep "${STATUS_INTERVAL}"
    done
}

wait_for_topic() {
    local topic_name="$1"
    local timeout="${2:-${WAIT_TIMEOUT}}"
    local start
    start="$(date +%s)"

    log "等待话题 ${topic_name} ..."
    while true; do
        if ros2 topic list 2>/dev/null | grep -Fxq "${topic_name}"; then
            ok "话题已存在: ${topic_name}"
            return 0
        fi

        if (( "$(date +%s)" - start >= timeout )); then
            err "等待话题超时: ${topic_name}"
            return 1
        fi

        sleep "${STATUS_INTERVAL}"
    done
}

start_background() {
    local name="$1"
    local log_file="$2"
    shift 2

    log "启动 ${name}，日志: ${log_file}"
    # setsid 让子进程成为新进程组组长，方便后续整组 kill
    setsid "$@" >"${log_file}" 2>&1 &
    local pid=$!
    local pgid
    pgid=$(ps -o pgid= -p "${pid}" 2>/dev/null | tr -d ' ') || pgid="${pid}"
    PIDS+=("${pid}")
    PGIDS+=("${pgid}")
    ok "${name} 已启动，PID=${pid} PGID=${pgid}"
}

print_status() {
    echo ""
    log "最终状态检查"

    echo -e "\n${BOLD}节点:${NC}"
    ros2 node list 2>/dev/null | grep -E \
        'livox_lidar_publisher|laser_mapping|fastlio|odom_tf_bridge|map_publisher|global_localization|transform_fusion|cloud_filter|pointcloud_to_laserscan' \
        || warn "未匹配到预期节点"

    echo -e "\n${BOLD}话题:${NC}"
    ros2 topic list 2>/dev/null | grep -E \
        '^/livox/lidar$|^/livox/imu$|^/Odometry$|^/cloud_registered$|^/cloud_registered_body$|^/odom$|^/map_to_odom$|^/localization$|^/cloud_filtered$|^/scan$' \
        || warn "未匹配到预期话题"

    echo -e "\n${BOLD}话题频率抽检，Ctrl+C 可中断:${NC}"
    for topic in /livox/lidar /Odometry /odom /map_to_odom /scan; do
        if ros2 topic list 2>/dev/null | grep -Fxq "${topic}"; then
            timeout 4s ros2 topic hz "${topic}" 2>/dev/null | sed "s/^/[${topic}] /" || true
        else
            warn "缺少话题: ${topic}"
        fi
    done
}

main() {
    log "Go2 导航链路启动"
    log "ROS=${ROS_DISTRO_NAME}, LIVOX_WS=${LIVOX_WS}, FASTLIO_WS=${FASTLIO_WS}, GO2_NAV_WS=${GO2_NAV_WS}"
    log "FASTLIO_CONFIG=${FASTLIO_CONFIG}"
    log "FASTLIO_LOC_PCD=${FASTLIO_LOC_PCD}"

    source_if_exists "${ROS_SETUP}" "ROS 2"
    source_if_exists "${LIVOX_WS}/install/setup.bash" "Livox 工作空间"
    source_if_exists "${FASTLIO_WS}/install/setup.bash" "FAST-LIO2 工作空间"
    source_if_exists "${GO2_NAV_WS}/install/setup.bash" "Go2_Nav 工作空间"

    require_command ros2
    require_command timeout
    require_file "${FASTLIO_CONFIG}" "FAST-LIO2 配置文件"
    require_file "${FASTLIO_LOC_PCD}" "定位地图 PCD 文件"

    local fastlio_config_path
    local fastlio_config_file
    fastlio_config_path="$(dirname "${FASTLIO_CONFIG}")"
    fastlio_config_file="$(basename "${FASTLIO_CONFIG}")"

    start_background \
        "Livox MID360" \
        "${LOG_DIR}/livox.log" \
        ros2 launch livox_ros_driver2 msg_MID360_launch.py

    wait_for_node "/livox_lidar_publisher"
    wait_for_topic "/livox/lidar"
    wait_for_topic "/livox/imu"

    start_background \
        "FAST-LIO2" \
        "${LOG_DIR}/fast_lio.log" \
        ros2 launch fast_lio mapping.launch.py \
            "config_path:=${fastlio_config_path}" \
            "config_file:=${fastlio_config_file}" \
            "rviz:=${RVIZ}"

    wait_for_topic "/Odometry"
    wait_for_topic "/cloud_registered"
    wait_for_topic "/cloud_registered_body"

    start_background \
        "odom_tf_bridge" \
        "${LOG_DIR}/odom_tf_bridge.log" \
        ros2 launch odom_tf_bridge odom_bridge.launch.py \
            "base_frame:=base_link"

    wait_for_topic "/odom"

    start_background \
        "fast_lio_localization" \
        "${LOG_DIR}/fast_lio_localization.log" \
        ros2 launch fast_lio_localization_ros2 localize_go2.launch.py \
            "map:=${FASTLIO_LOC_PCD}" \
            "rviz:=${RVIZ}"

    wait_for_topic "/map_to_odom"

    start_background \
        "go2_pc2scan" \
        "${LOG_DIR}/go2_pc2scan.log" \
        ros2 launch go2_pc2scan pc2scan.launch.py

    wait_for_topic "/cloud_filtered"
    wait_for_topic "/scan"

    print_status

    log "链路已启动，持续运行中。按 Ctrl+C 停止全部后台进程。"
    wait
}

main "$@"
