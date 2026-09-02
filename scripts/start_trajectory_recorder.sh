#!/usr/bin/env bash
set -eo pipefail

workspace="${LEAKAGE_WS:-/home/nvidia/leakage_location_ws}"
module_path="$workspace/src/leakage_bringup"

if pgrep -f 'leakage_bringup.trajectory_recorder' >/dev/null; then
  echo "trajectory recorder is already running"
  exit 0
fi

source /opt/ros/foxy/setup.bash
export PYTHONPATH="$module_path:${PYTHONPATH:-}"
nohup python3 -m leakage_bringup.trajectory_recorder > /home/nvidia/leakage_trajectory.log 2>&1 < /dev/null &
echo "trajectory recorder started with PID $!"
