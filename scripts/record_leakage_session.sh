#!/usr/bin/env bash
set -eo pipefail

workspace="${LEAKAGE_WS:-/home/nvidia/leakage_location_ws}"
livox_setup="${LIVOX_SETUP:-/home/nvidia/ws_Livox/install/livox_ros_driver2/share/livox_ros_driver2/package.bash}"
topic_file="$workspace/config/record_topics.txt"
qos_file="$workspace/config/record_qos.yaml"
output_root="${1:-/home/nvidia/leakage_bags}"

source /opt/ros/foxy/setup.bash
source "$livox_setup"
bash "$workspace/scripts/hardware_preflight.sh"
mapfile -t topics < <(grep -Ev '^\s*(#|$)' "$topic_file" | tr -d '\r')
mkdir -p "$output_root"
output_dir="$output_root/leakage_$(date +%Y%m%d_%H%M%S)"

echo "recording to $output_dir"
exec ros2 bag record --storage sqlite3 \
  --qos-profile-overrides-path "$qos_file" \
  -o "$output_dir" "${topics[@]}"
