#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=go2_env.sh
source "${SCRIPT_DIR}/go2_env.sh"
go2_load_environment

MAP_PCD="${MAP_PCD:-${GO2_WORKSPACE}/maps/MID360.pcd}"
MAP_YAML="${MAP_YAML:-${GO2_WORKSPACE}/maps/MID360_map.yaml}"
CONTROLLER="${CONTROLLER:-dwb}"
RVIZ="${RVIZ:-false}"
FASTLIO_CONFIG="${FASTLIO_CONFIG:-${FASTLIO_WORKSPACE}/src/FAST_LIO_ROS2/config/mid360.yaml}"
LOG_DIR="${LOG_DIR:-${HOME}/.local/state/go2-navigation/navigation}"
mkdir -p "${LOG_DIR}"

case "${CONTROLLER}" in
  dwb|rpp) ;;
  *) echo "[navigation] CONTROLLER must be dwb or rpp" >&2; exit 10 ;;
esac

set +e
"${SCRIPT_DIR}/check_system.sh" --stage preflight
preflight_status=$?
set -e
if (( preflight_status != 0 && preflight_status != 20 )); then
  exit "${preflight_status}"
fi
if (( preflight_status == 20 )); then
  echo "[navigation] control network unavailable: perception is allowed, motion remains blocked" >&2
fi

declare -a PIDS=()
cleanup() {
  trap - INT TERM EXIT
  for pid in "${PIDS[@]:-}"; do
    [[ -z "${pid}" ]] || kill -TERM "-${pid}" 2>/dev/null || true
  done
}
trap cleanup INT TERM EXIT

start_group() {
  local name="$1"
  shift
  setsid "$@" >"${LOG_DIR}/${name}.log" 2>&1 &
  PIDS+=("$!")
}

wait_graph() {
  local kind="$1" name="$2" timeout_sec="${3:-30}"
  timeout "${timeout_sec}" bash -c \
    'until ros2 "$1" list 2>/dev/null | grep -Fxq -- "$2"; do sleep 0.25; done' \
    _ "${kind}" "${name}"
}

wait_tf() {
  local parent="$1" child="$2" timeout_sec="${3:-20}"
  timeout "${timeout_sec}" bash -c \
    'until timeout 2 ros2 run tf2_ros tf2_echo "$1" "$2" 2>/dev/null | grep -qi translation; do sleep 0.25; done' \
    _ "${parent}" "${child}"
}

if ! ros2 topic list 2>/dev/null | grep -Fxq /livox/lidar; then
  start_group livox_ros_driver2 \
    ros2 launch livox_ros_driver2 msg_MID360s_launch.py
  wait_graph topic /livox/lidar 30
fi

start_group fast_lio \
  ros2 launch fast_lio mapping.launch.py \
  "config_path:=$(dirname "${FASTLIO_CONFIG}")" \
  "config_file:=$(basename "${FASTLIO_CONFIG}")" rviz:=false
wait_graph topic /Odometry 30
wait_graph topic /cloud_registered 30
wait_graph topic /cloud_registered_body 30

start_group odom_tf_bridge \
  ros2 launch odom_tf_bridge odom_bridge.launch.py base_frame:=base_link
wait_graph topic /odom 20

start_group fast_lio_localization_ros2 \
  ros2 launch fast_lio_localization_ros2 localize_go2.launch.py \
  "map:=${MAP_PCD}" rviz:=false
wait_graph topic /map_to_odom 40

start_group go2_pc2scan ros2 launch go2_pc2scan pc2scan.launch.py
wait_graph topic /scan 20
wait_tf map base_link 20

if systemctl is-active --quiet go2-motion-sender.service; then
  echo "[navigation] UDP motion sender is active"
else
  echo "[navigation] go2-motion-sender.service is offline; Nav2 will remain motion-blocked" >&2
fi

start_group go2_nav2 \
  ros2 launch go2_nav2 nav2_bringup.launch.py \
  "map:=${MAP_YAML}" "controller:=${CONTROLLER}" \
  use_sim_time:=false "use_rviz:=${RVIZ}"
wait_graph action /navigate_to_pose 60

echo "[navigation] stack started; run scripts/check_system.sh before sending a goal"
wait
