#!/usr/bin/env bash
set -eo pipefail

source /opt/ros/foxy/setup.bash

required_topics=(
  /livox/lidar
  /livox/imu
  /Odometry
  /fastlio_path
  /camera/color/image_raw
  /camera/color/camera_info
  /camera/aligned_depth_to_color/image_raw
)

available="$(ros2 topic list)"
missing=0
for topic in "${required_topics[@]}"; do
  if ! grep -Fxq "$topic" <<<"$available"; then
    echo "missing topic: $topic" >&2
    missing=1
  fi
done

if (( missing )); then
  exit 1
fi

workspace="${LEAKAGE_WS:-/home/nvidia/leakage_location_ws}"
PYTHONPATH="$workspace/src/leakage_bringup:${PYTHONPATH:-}" \
  python3 -m leakage_bringup.wait_for_topics
