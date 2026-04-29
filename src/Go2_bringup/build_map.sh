#!/usr/bin/env bash
# 将 PCD 点云文件转换为 2D 占据栅格地图（.pgm + .yaml），并发布到 /map 话题。
#
# 用法：
#   bash build_map.sh
#
# 常用覆盖变量：
#   PCD_FILE=/path/to/your.pcd \
#   OUTPUT_PATH=/path/to/output_map \
#   GO2_NAV_WS=/home/unitree/Go2_Nav_ws \
#   bash build_map.sh

set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEFAULT_GO2_WS="$(cd "${SCRIPT_DIR}/../.." && pwd)"

ROS_DISTRO_NAME="${ROS_DISTRO_NAME:-foxy}"
ROS_SETUP="${ROS_SETUP:-/opt/ros/${ROS_DISTRO_NAME}/setup.bash}"

GO2_NAV_WS="${GO2_NAV_WS:-${DEFAULT_GO2_WS}}"
PCD_FILE="${PCD_FILE:-${GO2_NAV_WS}/maps/MID360.pcd}"
OUTPUT_PATH="${OUTPUT_PATH:-${GO2_NAV_WS}/maps/MID360_map}"

RED='\033[0;31m'
YELLOW='\033[1;33m'
GREEN='\033[0;32m'
BOLD='\033[1m'
NC='\033[0m'

log()  { echo -e "${BOLD}[$(date '+%H:%M:%S')]${NC} $*"; }
ok()   { echo -e "${GREEN}[ OK $(date '+%H:%M:%S')]${NC} $*"; }
warn() { echo -e "${YELLOW}[WARN $(date '+%H:%M:%S')]${NC} $*"; }
err()  { echo -e "${RED}[ERR  $(date '+%H:%M:%S')]${NC} $*" >&2; }

source_if_exists() {
    local setup_file="$1"
    local label="$2"
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

main() {
    log "PCD → 占据栅格地图转换"
    log "PCD_FILE    = ${PCD_FILE}"
    log "OUTPUT_PATH = ${OUTPUT_PATH}"
    log "GO2_NAV_WS  = ${GO2_NAV_WS}"

    # 检查输入文件
    if [[ ! -f "${PCD_FILE}" ]]; then
        err "PCD 文件不存在: ${PCD_FILE}"
        exit 1
    fi

    # 确保输出目录存在
    mkdir -p "$(dirname "${OUTPUT_PATH}")"

    # source 环境
    source_if_exists "${ROS_SETUP}" "ROS 2"
    source_if_exists "${GO2_NAV_WS}/install/setup.bash" "Go2_Nav 工作空间"

    log "启动 pcd_to_map 节点，转换完成后自动退出..."
    ros2 launch pcd_to_map pcd_to_map.launch.py \
        "pcd_file:=${PCD_FILE}" \
        "output_path:=${OUTPUT_PATH}"

    # 检查输出文件
    if [[ -f "${OUTPUT_PATH}.pgm" && -f "${OUTPUT_PATH}.yaml" ]]; then
        ok "地图已生成:"
        ok "  ${OUTPUT_PATH}.pgm"
        ok "  ${OUTPUT_PATH}.yaml"
    else
        warn "节点已退出，但未找到输出文件，请检查日志"
    fi
}

main "$@"
