#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=go2_env.sh
source "${SCRIPT_DIR}/go2_env.sh"
go2_load_environment

# Publish zero before stopping process groups. The gateway watchdog remains the
# final stop mechanism if ROS is degraded.
ros2 topic pub --once /go2/manual_cmd_vel geometry_msgs/msg/Twist \
  '{linear: {x: 0.0, y: 0.0, z: 0.0}, angular: {x: 0.0, y: 0.0, z: 0.0}}' \
  >/dev/null 2>&1 || true

sudo systemctl stop go2-navigation.service go2-mapping.service 2>/dev/null || true

for pattern in \
  '/bt_navigator' '/controller_server' '/planner_server' '/map_server' \
  '/waypoint_follower' '/recoveries_server' '/pointcloud_to_laserscan_node' \
  '/global_localization' '/transform_fusion' '/odom_tf_bridge_node' \
  '/fastlio_mapping'; do
  pkill -TERM -f -- "${pattern}" 2>/dev/null || true
done

echo "[stop] navigation and mapping processes requested to stop"
echo "[stop] Web/PTP services were preserved for read-only diagnostics"
