#!/usr/bin/env bash
# Regression check for the ROS 2 Foxy service callback signature.

set -Eeuo pipefail

SOURCE_FILE="${1:-${HOME}/ws_fastlio2/src/FAST_LIO_ROS2/src/laserMapping.cpp}"
EXPECTED='void map_save_callback(std_srvs::srv::Trigger::Request::SharedPtr req, std_srvs::srv::Trigger::Response::SharedPtr res)'

[[ -f "${SOURCE_FILE}" ]] || {
    printf 'source file not found: %s\n' "${SOURCE_FILE}" >&2
    exit 2
}

if grep -Fq "${EXPECTED}" "${SOURCE_FILE}"; then
    printf 'Foxy-compatible map_save callback found\n'
    exit 0
fi

printf 'Foxy-compatible map_save callback missing\n' >&2
grep -n 'void map_save_callback' "${SOURCE_FILE}" >&2 || true
exit 1
