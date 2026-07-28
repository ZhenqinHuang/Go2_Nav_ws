#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WORKSPACE_DIR="$(cd "${SCRIPT_DIR}/../.." && pwd)"

set +u
source /opt/ros/foxy/setup.bash
source "${WORKSPACE_DIR}/install/setup.bash"
set -u

timeout 3s ros2 topic echo \
  /go2_cmd_vel_gateway/status \
  std_msgs/msg/String \
  --once
