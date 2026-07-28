#!/usr/bin/env bash
# Start the authenticated same-origin Go2 LAN console.
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WORKSPACE_DIR="$(cd "${SCRIPT_DIR}/../.." && pwd)"
ROS_DISTRO_NAME="${ROS_DISTRO_NAME:-foxy}"
CONSOLE_BIND="${CONSOLE_BIND:-192.168.0.101}"
CONSOLE_PORT="${CONSOLE_PORT:-8080}"
PASSWORD_HASH_FILE="${PASSWORD_HASH_FILE:-/etc/go2-console/password.hash}"

set +u
source "/opt/ros/${ROS_DISTRO_NAME}/setup.bash"
if [[ -f /home/nvidia/unitree_ros2/install/setup.bash ]]; then
  source /home/nvidia/unitree_ros2/install/setup.bash
fi
if [[ -f /home/nvidia/unitree_ros2/setup.sh ]]; then
  source /home/nvidia/unitree_ros2/setup.sh
fi
source "${WORKSPACE_DIR}/install/setup.bash"
set -u

if [[ ! -s "${PASSWORD_HASH_FILE}" ]]; then
  echo "[go2_console] 缺少密码哈希: ${PASSWORD_HASH_FILE}" >&2
  echo "[go2_console] 请先运行 go2_set_console_password。" >&2
  exit 1
fi

echo "[go2_console] http://${CONSOLE_BIND}:${CONSOLE_PORT}"
exec ros2 run go2_control_gateway go2_console \
  --bind "${CONSOLE_BIND}" \
  --port "${CONSOLE_PORT}" \
  --password-hash-file "${PASSWORD_HASH_FILE}"
