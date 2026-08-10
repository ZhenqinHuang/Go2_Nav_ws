#!/usr/bin/env bash
set -Eeuo pipefail

WORKSPACE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
INSTALL_SERVICES=false
[[ "${1:-}" != "--services" ]] || INSTALL_SERVICES=true

set +u
source /opt/ros/foxy/setup.bash
set -u

cd "${WORKSPACE}"
python3 scripts/map_bundle.py validate maps
rosdep install --from-paths src --ignore-src -r -y
colcon build --symlink-install

if [[ "${INSTALL_SERVICES}" == true ]]; then
  sudo install -m 0644 src/Go2_time_sync/config/ptp_sync.service \
    /etc/systemd/system/ptp_sync.service
  sudo install -m 0644 src/Go2_control_gateway/systemd/go2-motion-sender.service \
    /etc/systemd/system/go2-motion-sender.service
  sudo install -m 0644 src/Go2_web_console/systemd/go2-console.service \
    /etc/systemd/system/go2-console.service
  sudo install -m 0644 src/Go2_web_console/systemd/go2-console-rosbridge.service \
    /etc/systemd/system/go2-console-rosbridge.service
  sudo install -m 0644 src/Go2_bringup/systemd/go2-navigation.service \
    /etc/systemd/system/go2-navigation.service
  sudo install -m 0644 src/Go2_bringup/systemd/go2-mapping.service \
    /etc/systemd/system/go2-mapping.service
  sudo systemctl daemon-reload
  echo "[install] service templates installed but navigation/mapping were not started"
fi

echo "[install] source install/setup.bash"
echo "[install] run scripts/check_system.sh --stage base"
