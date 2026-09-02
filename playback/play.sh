#!/usr/bin/env bash
set -eo pipefail

session_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if ! command -v ros2 >/dev/null 2>&1; then
  source /opt/ros/foxy/setup.bash
fi
command -v rviz2 >/dev/null 2>&1 || {
  echo "rviz2 not found; install/source ROS2 Foxy desktop first" >&2
  exit 1
}

rviz2 -d "$session_dir/leakage.rviz" &
rviz_pid=$!
trap 'kill "$rviz_pid" 2>/dev/null || true' EXIT INT TERM
sleep 3
ros2 bag play "$session_dir"

