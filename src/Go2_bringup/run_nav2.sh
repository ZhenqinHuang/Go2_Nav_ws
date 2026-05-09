#!/usr/bin/env bash
# 启动 Go2 Nav2 决策层 + cmd_vel 执行桥接
# 前置条件：go2_nav_start.sh 已启动（FastLIO 定位链路运行中，/map_to_odom 和 /scan 已发布）
#
# 用法:
#   MAP_YAML=/path/to/maps.yaml bash run_nav2.sh
#
# 环境变量:
#   MAP_YAML            地图 yaml 路径（必填）
#   USE_RVIZ            是否启动 RViz（默认 false，无显示器时自动关闭）
#   USE_SIM_TIME        是否使用仿真时钟（默认 false）
#   UNITREE_ROS2_WS     unitree_ros2 工作空间路径（默认 ~/unitree_ros2）
#   NAV2_SKIP_BUILD     设为 1 跳过 colcon build

set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
GO2_NAV_WS="$(cd "${SCRIPT_DIR}/../.." && pwd)"

ROS_DISTRO_NAME="${ROS_DISTRO_NAME:-foxy}"
UNITREE_ROS2_WS="${UNITREE_ROS2_WS:-${HOME}/unitree_ros2}"
MAP_YAML="${MAP_YAML:-}"
USE_RVIZ="${USE_RVIZ:-false}"
USE_SIM_TIME="${USE_SIM_TIME:-false}"
# 本地控制器：dwb (默认，Go2 实测可用) 或 rpp (Regulated Pure Pursuit)
CONTROLLER="${CONTROLLER:-dwb}"

usage() {
  echo "用法: MAP_YAML=/path/to/maps.yaml bash $(basename "$0")"
  echo ""
  echo "环境变量:"
  echo "  MAP_YAML            地图 yaml 路径（必填）"
  echo "  USE_RVIZ            启动 RViz（默认 false）"
  echo "  USE_SIM_TIME        仿真时钟（默认 false）"
  echo "  UNITREE_ROS2_WS     unitree_ros2 工作空间（默认 ~/unitree_ros2）"
  echo "  NAV2_SKIP_BUILD     设为 1 跳过 colcon build"
}

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
  usage; exit 0
fi

if [[ -z "${MAP_YAML}" ]]; then
  echo "[go2_nav2] ERROR: MAP_YAML 未设置。示例: MAP_YAML=/path/to/maps.yaml bash $0"
  exit 1
fi

if [[ ! -f "${MAP_YAML}" ]]; then
  echo "[go2_nav2] ERROR: 地图文件不存在: ${MAP_YAML}"
  exit 1
fi

set +u
source "/opt/ros/${ROS_DISTRO_NAME}/setup.bash"
# unitree_api 消息包在 unitree_ros2 工作空间，构建时需要
if [[ -f "${UNITREE_ROS2_WS}/install/setup.bash" ]]; then
  source "${UNITREE_ROS2_WS}/install/setup.bash"
else
  echo "[go2_nav2] WARN: ${UNITREE_ROS2_WS}/install/setup.bash 不存在，unitree_api 可能不可用"
fi
# Unitree 专用 DDS 环境（设置 RMW_IMPLEMENTATION 和 CYCLONEDDS_URI）
if [[ -f "${UNITREE_ROS2_WS}/setup.sh" ]]; then
  source "${UNITREE_ROS2_WS}/setup.sh"
elif [[ -f "${HOME}/unitree_ros2/setup.sh" ]]; then
  source "${HOME}/unitree_ros2/setup.sh"
fi
set -u

if [[ "${NAV2_SKIP_BUILD:-0}" != "1" ]]; then
  echo "[go2_nav2] colcon build --packages-select go2_nav2 ..."
  cd "${GO2_NAV_WS}"
  colcon build --packages-select go2_nav2
fi

set +u
source "${GO2_NAV_WS}/install/setup.bash"
set -u

if ! ros2 pkg prefix go2_nav2 >/dev/null 2>&1; then
  echo "[go2_nav2] ERROR: go2_nav2 包未找到，构建可能失败"
  exit 1
fi

if [[ "${USE_RVIZ}" == "true" && -z "${DISPLAY:-}" ]]; then
  echo "[go2_nav2] DISPLAY 未设置，自动关闭 RViz"
  USE_RVIZ="false"
fi

echo "[go2_nav2] 清理残留进程..."
pkill -f "ros2 launch go2_nav2" >/dev/null 2>&1 || true
pkill -f "go2_cmd_vel_bridge_node" >/dev/null 2>&1 || true
pkill -f "/opt/ros/${ROS_DISTRO_NAME}/lib/nav2_map_server/map_server" >/dev/null 2>&1 || true
pkill -f "/opt/ros/${ROS_DISTRO_NAME}/lib/nav2_planner/planner_server" >/dev/null 2>&1 || true
pkill -f "/opt/ros/${ROS_DISTRO_NAME}/lib/nav2_controller/controller_server" >/dev/null 2>&1 || true
pkill -f "/opt/ros/${ROS_DISTRO_NAME}/lib/nav2_bt_navigator/bt_navigator" >/dev/null 2>&1 || true
pkill -f "/opt/ros/${ROS_DISTRO_NAME}/lib/nav2_recoveries/recoveries_server" >/dev/null 2>&1 || true
pkill -f "/opt/ros/${ROS_DISTRO_NAME}/lib/nav2_lifecycle_manager/lifecycle_manager" >/dev/null 2>&1 || true

# 启动 cmd_vel 执行桥接（后台运行，Nav2 的 /cmd_vel -> Go2 sport API）
echo "[go2_nav2] 启动 cmd_vel 执行桥接..."
ros2 launch go2_nav2 cmd_vel_bridge.launch.py >/tmp/go2_cmd_vel_bridge.log 2>&1 &
CMD_VEL_BRIDGE_PID=$!
echo "[go2_nav2] cmd_vel bridge PID=${CMD_VEL_BRIDGE_PID}，日志: /tmp/go2_cmd_vel_bridge.log"

echo "[go2_nav2] 启动 Nav2 决策层"
echo "[go2_nav2] map=${MAP_YAML}  use_sim_time=${USE_SIM_TIME}  use_rviz=${USE_RVIZ}  controller=${CONTROLLER}"

exec ros2 launch go2_nav2 nav2_bringup.launch.py \
  "map:=${MAP_YAML}" \
  "use_sim_time:=${USE_SIM_TIME}" \
  "use_rviz:=${USE_RVIZ}" \
  "controller:=${CONTROLLER}"

