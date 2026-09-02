#!/usr/bin/env bash
set -eo pipefail

workspace="${LEAKAGE_WS:-/home/nvidia/leakage_location_ws}"
model="${LEAKAGE_MODEL:-$workspace/models/best.pt}"
calibration="${LEAKAGE_CALIBRATION:-/home/nvidia/fastlivo2_ws/config/common/calibration.yaml}"

source /opt/ros/foxy/setup.bash
source "$workspace/install/leakage_bringup/share/leakage_bringup/local_setup.bash"
source "$workspace/.venv-yolo/bin/activate"

exec python -m leakage_bringup.leakage_detector --ros-args \
  -p model_path:="$model" \
  -p calibration_file:="$calibration"
