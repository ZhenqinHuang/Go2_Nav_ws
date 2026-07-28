#!/usr/bin/env bash
# Keyboard -> /go2/manual_cmd_vel -> external UDP sender -> internal gateway.
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WORKSPACE_DIR="$(cd "${SCRIPT_DIR}/../.." && pwd)"
ROS_DISTRO_NAME="${ROS_DISTRO_NAME:-foxy}"
SENDER_PID=""

cleanup() {
  bash "${SCRIPT_DIR}/go2_gateway_disarm.sh" 2>/dev/null || true
  if [[ -n "${SENDER_PID}" ]]; then
    kill "${SENDER_PID}" 2>/dev/null || true
  fi
}
trap cleanup INT TERM EXIT

set +u
source "/opt/ros/${ROS_DISTRO_NAME}/setup.bash"
set -u

if [[ "${NAV2_SKIP_BUILD:-0}" != "1" ]]; then
  cd "${WORKSPACE_DIR}"
  colcon build --packages-select go2_nav2 go2_control_gateway
fi

set +u
source "${WORKSPACE_DIR}/install/setup.bash"
set -u

pkill -f "go2_cmd_vel_udp_sender" >/dev/null 2>&1 || true
pkill -f "go2_cmd_vel_keyboard_node" >/dev/null 2>&1 || true
ros2 launch go2_control_gateway udp_sender.launch.py \
  >/tmp/go2_cmd_vel_gateway.log 2>&1 &
SENDER_PID=$!
sleep 1

echo "[keyboard_teleop] 先检查环境并在另一终端运行 go2_gateway_arm.sh"
echo "[keyboard_teleop] 键盘命令通过内载原生 SDK 网关执行"
ros2 run go2_nav2 go2_cmd_vel_keyboard_node \
  --ros-args \
  -p cmd_vel_topic:=/go2/manual_cmd_vel \
  -p max_vx:=0.35 \
  -p max_vy:=0.0 \
  -p max_vyaw:=0.8
