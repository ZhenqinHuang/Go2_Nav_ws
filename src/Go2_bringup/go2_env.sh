#!/usr/bin/env bash
# Shared environment for canonical Go2 bringup scripts. Source this file.

GO2_WORKSPACE="${GO2_WORKSPACE:-/home/nvidia/Go2_Nav_ws}"
LIVOX_WORKSPACE="${LIVOX_WORKSPACE:-/home/nvidia/ws_Livox}"
FASTLIO_WORKSPACE="${FASTLIO_WORKSPACE:-/home/nvidia/ws_fastlio2}"
ROS_SETUP="${ROS_SETUP:-/opt/ros/foxy/setup.bash}"

go2_source_setup() {
  local setup_file="$1"
  [[ -f "${setup_file}" ]] || {
    echo "[bringup] missing setup: ${setup_file}" >&2
    return 1
  }
  set +u
  # shellcheck source=/dev/null
  source "${setup_file}"
  set -u
}

go2_load_environment() {
  go2_source_setup "${ROS_SETUP}"
  [[ ! -f /home/nvidia/unitree_ros2/install/setup.bash ]] || \
    go2_source_setup /home/nvidia/unitree_ros2/install/setup.bash
  go2_source_setup "${LIVOX_WORKSPACE}/install/setup.bash"
  go2_source_setup "${FASTLIO_WORKSPACE}/install/setup.bash"
  go2_source_setup "${GO2_WORKSPACE}/install/setup.bash"
}
