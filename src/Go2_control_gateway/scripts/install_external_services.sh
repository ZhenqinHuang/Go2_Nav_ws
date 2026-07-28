#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PACKAGE_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
WORKSPACE_DIR="$(cd "${PACKAGE_DIR}/../.." && pwd)"
BRINGUP_DIR="${WORKSPACE_DIR}/src/Go2_bringup"

# Stop motion before replacing any control-plane process.
bash "${BRINGUP_DIR}/go2_gateway_disarm.sh" || true
sudo systemctl stop go2-console.service 2>/dev/null || true

set +u
source /opt/ros/foxy/setup.bash
if [[ -f /home/nvidia/unitree_ros2/install/setup.bash ]]; then
  source /home/nvidia/unitree_ros2/install/setup.bash
fi
set -u

cd "${WORKSPACE_DIR}"
colcon build --packages-select go2_control_gateway

sudo install -d -m 0755 /etc/go2-console
if [[ ! -s /etc/go2-console/password.hash ]]; then
  TEMP_HASH="$(mktemp)"
  trap 'rm -f -- "${TEMP_HASH}"' EXIT
  set +u
  source "${WORKSPACE_DIR}/install/setup.bash"
  set -u
  ros2 run go2_control_gateway go2_set_console_password --output "${TEMP_HASH}"
  sudo install -m 0600 -o nvidia -g nvidia \
    "${TEMP_HASH}" /etc/go2-console/password.hash
fi

sudo install -m 0644 \
  "${PACKAGE_DIR}/systemd/go2-console.service" \
  /etc/systemd/system/go2-console.service
sudo systemctl daemon-reload
sudo systemctl enable --now go2-console.service
sudo systemctl --no-pager --full status go2-console.service

echo "[external-install] Console: http://192.168.0.101:8080"
