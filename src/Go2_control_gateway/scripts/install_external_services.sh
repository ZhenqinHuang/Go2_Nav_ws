#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PACKAGE_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
WORKSPACE_DIR="$(cd "${PACKAGE_DIR}/../.." && pwd)"

set +u
source /opt/ros/foxy/setup.bash
set -u

cd "${WORKSPACE_DIR}"
colcon build --packages-select go2_control_gateway

# A zero command is sent before replacing the sender service. The internal
# gateway watchdog remains armed if ROS is unavailable.
set +u
source "${WORKSPACE_DIR}/install/setup.bash"
set -u
ros2 topic pub --once /go2/manual_cmd_vel geometry_msgs/msg/Twist '{}' || true

sudo install -m 0644 \
  "${PACKAGE_DIR}/systemd/go2-motion-sender.service" \
  /etc/systemd/system/go2-motion-sender.service
sudo systemctl daemon-reload
sudo systemctl enable --now go2-motion-sender.service
sudo systemctl --no-pager --full status go2-motion-sender.service

echo "[gateway] installed external UDP sender only"
echo "[gateway] Web console is managed by src/Go2_web_console/scripts/install_web_console.sh"
