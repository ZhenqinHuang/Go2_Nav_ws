#!/usr/bin/env bash
# 键盘遥控 Go2：键盘 → /cmd_vel → go2_cmd_vel_bridge → Go2 sport API
# 用途：验证执行层（cmd_vel bridge）是否正常工作
#
# 前置条件：Go2 已上电并处于运动模式（DDS 可达）
#
# 操作说明：
#   w/s   前进/后退
#   a/d   左横移/右横移（Go2 实际不支持，bridge 会过滤）
#   q/e   左转/右转
#   空格  停止
#   +/-   加速/减速
#   Ctrl+C 退出

set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
GO2_NAV_WS="$(cd "${SCRIPT_DIR}/../.." && pwd)"

ROS_DISTRO_NAME="${ROS_DISTRO_NAME:-foxy}"
UNITREE_ROS2_WS="${UNITREE_ROS2_WS:-${HOME}/unitree_ros2}"

usage() {
  echo "用法: bash $(basename "$0")"
  echo ""
  echo "环境变量:"
  echo "  UNITREE_ROS2_WS   unitree_ros2 工作空间（默认 ~/unitree_ros2）"
  echo "  NAV2_SKIP_BUILD   设为 1 跳过 colcon build"
}

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
  usage; exit 0
fi

set +u
source "/opt/ros/${ROS_DISTRO_NAME}/setup.bash"
if [[ -f "${UNITREE_ROS2_WS}/install/setup.bash" ]]; then
  source "${UNITREE_ROS2_WS}/install/setup.bash"
else
  echo "[keyboard_teleop] WARN: ${UNITREE_ROS2_WS}/install/setup.bash 不存在"
fi
set -u

if [[ "${NAV2_SKIP_BUILD:-0}" != "1" ]]; then
  echo "[keyboard_teleop] colcon build --packages-select go2_nav2 ..."
  cd "${GO2_NAV_WS}"
  colcon build --packages-select go2_nav2
fi

set +u
source "${GO2_NAV_WS}/install/setup.bash"
set -u

if ! ros2 pkg prefix go2_nav2 >/dev/null 2>&1; then
  echo "[keyboard_teleop] ERROR: go2_nav2 包未找到，构建可能失败"
  exit 1
fi

echo "[keyboard_teleop] 清理残留进程..."
pkill -f "go2_cmd_vel_bridge_node" >/dev/null 2>&1 || true
pkill -f "go2_cmd_vel_keyboard_node" >/dev/null 2>&1 || true

# 后台启动 cmd_vel bridge（/cmd_vel → Go2 sport API）
echo "[keyboard_teleop] 启动 cmd_vel bridge..."
ros2 run go2_nav2 go2_cmd_vel_bridge_node \
  --ros-args \
  -p cmd_vel_topic:=/cmd_vel \
  -p max_vx:=0.35 \
  -p max_vy:=0.0 \
  -p max_vyaw:=0.8 \
  -p stand_up_on_motion:=true \
  -p cmd_timeout_sec:=0.5 \
  >/tmp/go2_cmd_vel_bridge.log 2>&1 &
BRIDGE_PID=$!
echo "[keyboard_teleop] bridge PID=${BRIDGE_PID}，日志: /tmp/go2_cmd_vel_bridge.log"

# 等 bridge 节点注册到 ROS graph
sleep 1

echo "[keyboard_teleop] 启动键盘控制（在此终端操作）..."
exec ros2 run go2_nav2 go2_cmd_vel_keyboard_node \
  --ros-args \
  -p cmd_vel_topic:=/cmd_vel \
  -p max_vx:=0.35 \
  -p max_vy:=0.0 \
  -p max_vyaw:=0.8
