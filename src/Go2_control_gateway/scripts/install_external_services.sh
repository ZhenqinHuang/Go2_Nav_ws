#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PACKAGE_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
WORKSPACE_DIR="$(cd "${PACKAGE_DIR}/../.." && pwd)"

set +u
source /opt/ros/foxy/setup.bash
if [[ -f /home/nvidia/unitree_ros2/install/setup.bash ]]; then
  source /home/nvidia/unitree_ros2/install/setup.bash
fi
set -u

if [[ "${GO2_SKIP_FRONTEND_BUILD:-0}" == "1" ]]; then
  WEB_DIR="${PACKAGE_DIR}/go2_control_gateway/web"
  if [[ ! -f "${WEB_DIR}/index.html" ]] || \
     ! find "${WEB_DIR}/assets" -maxdepth 1 -type f -name '*.js' -print -quit | grep -q .; then
    echo "[external-install] production bundle is incomplete: ${WEB_DIR}" >&2
    exit 1
  fi
  echo "[external-install] using the verified prebuilt frontend bundle"
else
  bash "${PACKAGE_DIR}/scripts/build_frontend.sh"
fi

cd "${WORKSPACE_DIR}"
colcon build --packages-select go2_control_gateway

# Stop motion only after the replacement build is ready.
set +u
source "${WORKSPACE_DIR}/install/setup.bash"
set -u
ros2 topic pub --once /go2/manual_cmd_vel geometry_msgs/msg/Twist '{}' || true
sudo systemctl stop go2-console.service 2>/dev/null || true
sudo systemctl stop go2-console-rosbridge.service 2>/dev/null || true

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
sudo install -m 0644 \
  "${PACKAGE_DIR}/systemd/go2-console-rosbridge.service" \
  /etc/systemd/system/go2-console-rosbridge.service
sudo systemctl daemon-reload
sudo systemctl enable --now go2-console-rosbridge.service
sudo systemctl enable --now go2-console.service
sudo systemctl --no-pager --full status go2-console-rosbridge.service
sudo systemctl --no-pager --full status go2-console.service

echo "[external-install] Console: http://192.168.0.101:8080"
