#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=go2_env.sh
source "${SCRIPT_DIR}/go2_env.sh"
go2_load_environment

RVIZ="${RVIZ:-false}"
FASTLIO_CONFIG="${FASTLIO_CONFIG:-${FASTLIO_WORKSPACE}/src/FAST_LIO_ROS2/config/mid360.yaml}"
LOG_DIR="${LOG_DIR:-${HOME}/.local/state/go2-navigation/mapping}"
mkdir -p "${LOG_DIR}" "${GO2_WORKSPACE}/maps/staging"

"${SCRIPT_DIR}/check_system.sh" --stage base

STAMP="$(date +%Y%m%d_%H%M%S)"
SESSION_PCD="${GO2_WORKSPACE}/maps/staging/MID360_cli_${STAMP}.pcd"
SESSION_CONFIG="${LOG_DIR}/mid360_cli_${STAMP}.yaml"
python3 - "${FASTLIO_CONFIG}" "${SESSION_CONFIG}" "${SESSION_PCD}" <<'PY'
from pathlib import Path
import re
import sys

source, target, pcd = map(Path, sys.argv[1:])
text = source.read_text(encoding="utf-8")
text, count = re.subn(
    r"(?m)^\s*map_file_path\s*:.*$",
    lambda _: f'    map_file_path: "{pcd}"',
    text,
    count=1,
)
if count != 1:
    raise SystemExit("FAST-LIO config has no map_file_path")
target.write_text(text, encoding="utf-8")
PY

declare -a PIDS=()
cleanup() {
  trap - INT TERM EXIT
  for pid in "${PIDS[@]:-}"; do
    [[ -z "${pid}" ]] || kill -TERM "-${pid}" 2>/dev/null || true
  done
}
trap cleanup INT TERM EXIT

start_group() {
  local log_file="$1"
  shift
  setsid "$@" >"${log_file}" 2>&1 &
  PIDS+=("$!")
}

wait_topic() {
  local topic="$1" timeout_sec="${2:-30}"
  timeout "${timeout_sec}" bash -c \
    'until ros2 topic list 2>/dev/null | grep -Fxq -- "$1"; do sleep 0.25; done' \
    _ "${topic}"
}

if ! ros2 topic list 2>/dev/null | grep -Fxq /livox/lidar; then
  start_group "${LOG_DIR}/livox_${STAMP}.log" \
    ros2 launch livox_ros_driver2 msg_MID360s_launch.py
  wait_topic /livox/lidar 30
fi

start_group "${LOG_DIR}/fastlio_${STAMP}.log" \
  ros2 launch fast_lio mapping.launch.py \
  "config_path:=$(dirname "${SESSION_CONFIG}")" \
  "config_file:=$(basename "${SESSION_CONFIG}")" "rviz:=${RVIZ}"
wait_topic /cloud_registered 30
wait_topic /Odometry 30

echo "[mapping] ready; staged PCD target: ${SESSION_PCD}"
echo "[mapping] use the Web console to stop, convert, validate and promote a map bundle"
wait
