#!/usr/bin/env bash
set -Eeuo pipefail

EXIT_BASE=10
EXIT_CONTROL=20
EXIT_PERCEPTION=30
EXIT_LOCALIZATION=40
EXIT_NAV2=50

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=go2_env.sh
source "${SCRIPT_DIR}/go2_env.sh"
go2_load_environment

STAGE="all"
if [[ "${1:-}" == "--stage" ]]; then
  STAGE="${2:-all}"
fi

ok() { printf '[ OK ] %s\n' "$*"; }
bad() { printf '[FAIL] %s\n' "$*" >&2; }

has_address() {
  ip -o -4 addr show dev "$1" 2>/dev/null | grep -Fq " $2/"
}

route_uses() {
  ip route get "$1" 2>/dev/null | grep -Eq " dev $2( |$)"
}

check_base() {
  local failed=0
  local synchronized
  synchronized="$(timedatectl show -p NTPSynchronized --value 2>/dev/null || true)"
  [[ "${synchronized}" == "yes" ]] || {
    bad "host time is not NTP-synchronized (NTPSynchronized=${synchronized:-unknown})"
    failed=1
  }
  has_address wlan0 192.168.0.101 || { bad "wlan0 must own 192.168.0.101"; failed=1; }
  has_address eth1 192.168.1.5 || { bad "eth1 must own 192.168.1.5"; failed=1; }
  route_uses 192.168.1.158 eth1 || { bad "MID360S route must use eth1"; failed=1; }
  route_uses 1.1.1.1 wlan0 || { bad "default route must use wlan0"; failed=1; }
  python3 "${GO2_WORKSPACE}/scripts/map_bundle.py" validate \
    "${GO2_WORKSPACE}/maps" >/dev/null || {
      bad "canonical map bundle validation failed"
      failed=1
    }
  (( failed == 0 )) || return "${EXIT_BASE}"
  ok "time, management/radar network, and map bundle"
}

check_control() {
  local failed=0
  has_address eth0 192.168.123.5 || { bad "eth0 must own 192.168.123.5"; failed=1; }
  route_uses 192.168.123.18 eth0 || { bad "internal gateway route must use eth0"; failed=1; }
  route_uses 192.168.123.161 eth0 || { bad "Go2 route must use eth0"; failed=1; }
  systemctl is-active --quiet go2-motion-sender.service || {
    bad "go2-motion-sender.service is inactive"
    failed=1
  }
  local gateway_status
  gateway_status="$(
    timeout 4 ros2 topic echo --once /go2_cmd_vel_gateway/status 2>/dev/null || true
  )"
  grep -q '"gateway_link"[[:space:]]*:[[:space:]]*"online"' <<<"${gateway_status}" || {
    bad "gateway ACK link is not online"
    failed=1
  }
  grep -q '"estop_latched"[[:space:]]*:[[:space:]]*false' <<<"${gateway_status}" || {
    bad "estop_latched is true or gateway status is stale"
    failed=1
  }
  (( failed == 0 )) || return "${EXIT_CONTROL}"
  ok "control route, ACK, and emergency-stop state"
}

topic_fresh() {
  timeout 5 ros2 topic hz "$1" 2>/dev/null | grep -q "average rate"
}

tf_available() {
  timeout 6 bash -c \
    'until timeout 2 ros2 run tf2_ros tf2_echo "$1" "$2" 2>/dev/null | grep -qi translation; do sleep 0.25; done' \
    _ "$1" "$2"
}

check_perception() {
  local failed=0
  for topic in /Odometry /cloud_registered /cloud_registered_body /odom /scan; do
    topic_fresh "${topic}" || { bad "topic is missing or stale: ${topic}"; failed=1; }
  done
  (( failed == 0 )) || return "${EXIT_PERCEPTION}"
  ok "Livox, FAST-LIO2, odometry bridge, and scan topics"
}

check_localization() {
  topic_fresh /map_to_odom || {
    bad "/map_to_odom is missing or stale"
    return "${EXIT_LOCALIZATION}"
  }
  tf_available map base_link || {
      bad "TF check failed: tf2_echo map base_link"
      return "${EXIT_LOCALIZATION}"
    }
  ok "localization and map -> odom -> base_link TF"
}

check_nav2() {
  local failed=0 node
  for node in map_server planner_server controller_server recoveries_server bt_navigator waypoint_follower; do
    ros2 lifecycle get "/${node}" 2>/dev/null | grep -qi active || {
      bad "Nav2 lifecycle node is not active: ${node}"
      failed=1
    }
  done
  ros2 action list 2>/dev/null | grep -Fxq /navigate_to_pose || {
    bad "missing action /navigate_to_pose"
    failed=1
  }
  ros2 topic info /map 2>/dev/null | grep -Eq 'Publisher count: [1-9]' || {
    bad "/map has no publisher"
    failed=1
  }
  (( failed == 0 )) || return "${EXIT_NAV2}"
  ok "Nav2 lifecycle, map owner, and navigation action"
}

case "${STAGE}" in
  base) check_base ;;
  preflight) check_base && check_control ;;
  perception) check_perception ;;
  localization) check_localization ;;
  nav2) check_nav2 ;;
  runtime) check_perception && check_localization && check_nav2 && check_control ;;
  all) check_base && check_control && check_perception && check_localization && check_nav2 ;;
  *) bad "unknown stage: ${STAGE}"; exit 2 ;;
esac
