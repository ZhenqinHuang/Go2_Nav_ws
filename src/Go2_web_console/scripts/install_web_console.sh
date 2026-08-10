#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PACKAGE_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
WORKSPACE_DIR="$(cd "${PACKAGE_DIR}/../.." && pwd)"

bash "${PACKAGE_DIR}/scripts/build_frontend.sh"

set +u
source /opt/ros/foxy/setup.bash
source /home/nvidia/unitree_ros2/install/setup.bash
source /home/nvidia/Go2_Nav_ws/install/setup.bash
set -u

cd "${WORKSPACE_DIR}"
colcon build --packages-select go2_web_console

# Only Web services are stopped after their replacement build is ready.
sudo systemctl stop go2-console.service 2>/dev/null || true
sudo systemctl stop go2-console-rosbridge.service 2>/dev/null || true

sudo install -d -m 0755 /etc/go2-console
sudo install -m 0644 \
  "${PACKAGE_DIR}/config/cyclonedds_wlan0.xml" \
  /etc/go2-console/cyclonedds_wlan0.xml
if [[ ! -s /etc/go2-console/password.hash ]]; then
  TEMP_HASH="$(mktemp)"
  trap 'rm -f -- "${TEMP_HASH}"' EXIT
  set +u
  source "${WORKSPACE_DIR}/install/setup.bash"
  set -u
  ros2 run go2_web_console go2_set_console_password --output "${TEMP_HASH}"
  sudo install -m 0600 -o nvidia -g nvidia \
    "${TEMP_HASH}" /etc/go2-console/password.hash
fi

sudo install -m 0644 \
  "${PACKAGE_DIR}/systemd/go2-console.service" \
  /etc/systemd/system/go2-console.service
sudo install -m 0644 \
  "${PACKAGE_DIR}/systemd/go2-console-rosbridge.service" \
  /etc/systemd/system/go2-console-rosbridge.service
sudo systemctl daemon-reload
sudo systemctl enable --now go2-console-rosbridge.service
sudo systemctl enable --now go2-console.service
sudo systemctl --no-pager --full status go2-console-rosbridge.service
sudo systemctl --no-pager --full status go2-console.service

echo "[web-console] Ready at http://192.168.0.101:8080"
echo "[web-console] Motion gateway services were not changed."
