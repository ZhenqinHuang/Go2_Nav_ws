#!/usr/bin/env bash
# Verify the MID360 software preparation without requiring the LiDAR hardware.

set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
GO2_NAV_WS="${GO2_NAV_WS:-$(cd "${SCRIPT_DIR}/../.." && pwd)}"
LIVOX_SDK_DIR="${LIVOX_SDK_DIR:-${HOME}/Livox-SDK2}"
LIVOX_WS="${LIVOX_WS:-${HOME}/ws_Livox}"
FASTLIO_WS="${FASTLIO_WS:-${HOME}/ws_fastlio2}"

LIVOX_SDK_COMMIT="f5d9375f84efe2b15bc0a052d3e18482ed13adf4"
LIVOX_DRIVER_COMMIT="13eb05e4e6dd7a765b934d0c5fd6236676a57b49"
FASTLIO_COMMIT="2fffc570a25d0df172720bac034fbdb6a13d2162"

failures=0
pending=0

pass() { printf '[PASS] %s\n' "$*"; }
fail() { printf '[FAIL] %s\n' "$*" >&2; failures=$((failures + 1)); }
pend() { printf '[PENDING] %s\n' "$*"; pending=$((pending + 1)); }

check_command() {
    local label="$1"
    shift
    if "$@" >/dev/null 2>&1; then
        pass "${label}"
    else
        fail "${label}"
    fi
}

check_revision() {
    local label="$1"
    local repo="$2"
    local expected="$3"
    local actual=""
    if [[ -d "${repo}/.git" ]]; then
        actual="$(git -C "${repo}" rev-parse HEAD 2>/dev/null || true)"
    fi
    if [[ "${actual}" == "${expected}" ]]; then
        pass "${label}: ${actual}"
    else
        fail "${label}: expected ${expected}, got ${actual:-missing}"
    fi
}

source_setup() {
    local setup_file="$1"
    [[ -f "${setup_file}" ]] || return 1
    set +u
    # shellcheck source=/dev/null
    source "${setup_file}"
    set -u
}

check_revision "Livox-SDK2 revision" "${LIVOX_SDK_DIR}" "${LIVOX_SDK_COMMIT}"
check_revision "livox_ros_driver2 revision" \
    "${LIVOX_WS}/src/livox_ros_driver2" "${LIVOX_DRIVER_COMMIT}"
check_revision "FAST_LIO_ROS2 revision" \
    "${FASTLIO_WS}/src/FAST_LIO_ROS2" "${FASTLIO_COMMIT}"

if git -C "${FASTLIO_WS}/src/FAST_LIO_ROS2" submodule status --recursive \
    2>/dev/null | grep -q '^-'; then
    fail "FAST_LIO_ROS2 submodules initialized"
else
    pass "FAST_LIO_ROS2 submodules initialized"
fi

check_command "Livox SDK shared library installed" \
    bash -lc "ldconfig -p | grep -q liblivox_lidar_sdk"
check_command "Livox SDK headers installed" \
    bash -lc "find /usr/local/include -maxdepth 2 -iname 'livox_lidar*' -print -quit | grep -q ."

if source_setup /opt/ros/foxy/setup.bash &&
   source_setup "${LIVOX_WS}/install/setup.bash" &&
   source_setup "${FASTLIO_WS}/install/setup.bash"; then
    check_command "ROS package livox_ros_driver2 visible" ros2 pkg prefix livox_ros_driver2
    check_command "ROS package fast_lio visible" ros2 pkg prefix fast_lio
else
    fail "ROS overlay setup files available"
fi

check_command "MID360 JSON parses" \
    python3 -m json.tool \
    "${LIVOX_WS}/src/livox_ros_driver2/config/MID360_config.json"
check_command "FAST-LIO YAML parses" \
    python3 -c \
    "import yaml; yaml.safe_load(open('${FASTLIO_WS}/src/FAST_LIO_ROS2/config/mid360.yaml'))"

if nmcli -t -f NAME connection show 2>/dev/null | grep -Fxq mid360-direct; then
    address="$(nmcli -g ipv4.addresses connection show mid360-direct)"
    never_default="$(nmcli -g ipv4.never-default connection show mid360-direct)"
    if [[ "${address}" == "192.168.1.5/24" && "${never_default}" == "yes" ]]; then
        pass "NetworkManager mid360-direct profile"
    else
        fail "NetworkManager mid360-direct profile values"
    fi
else
    fail "NetworkManager mid360-direct profile exists"
fi

if ip route show default | grep -q 'dev wlan0'; then
    pass "Default route remains on wlan0"
else
    fail "Default route remains on wlan0"
fi

carrier="$(cat /sys/class/net/eth0/carrier 2>/dev/null || printf '0')"
if [[ "${carrier}" == "1" ]]; then
    pass "eth0 carrier detected"
else
    pend "eth0 carrier and real MID360 data (hardware not connected)"
fi

printf '\nSummary: failures=%d pending=%d\n' "${failures}" "${pending}"
(( failures == 0 ))
