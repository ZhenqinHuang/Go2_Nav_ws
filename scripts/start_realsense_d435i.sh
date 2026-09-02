#!/usr/bin/env bash
set -eo pipefail

workspace="${LEAKAGE_WS:-/home/nvidia/leakage_location_ws}"
node="$workspace/install/realsense2_camera/lib/realsense2_camera/realsense2_camera_node"
log_file="${D435_LOG:-/home/nvidia/realsense_d435i.log}"

if pgrep -f "$node" >/dev/null; then
  echo "D435i node is already running"
  exit 0
fi

source /opt/ros/foxy/setup.bash
export LD_LIBRARY_PATH="$workspace/install/realsense2_camera/lib:$workspace/install/librealsense2/lib:$workspace/build/realsense2_camera_msgs:${LD_LIBRARY_PATH:-}"

nohup "$node" --ros-args \
  -r __node:=camera -r __ns:=/camera \
  -p enable_depth:=true -p enable_color:=true \
  -p align.enable:=true \
  -p enable_gyro:=false -p enable_accel:=false \
  -p depth_module.profile:=640x480x30 \
  -p rgb_camera.profile:=640x480x30 \
  >"$log_file" 2>&1 < /dev/null &

echo "D435i started with PID $!; log: $log_file"
