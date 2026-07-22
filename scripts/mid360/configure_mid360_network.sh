#!/usr/bin/env bash
# Configure Jetson eth0 as an isolated MID360 network.

set -Eeuo pipefail

PROFILE_NAME="${PROFILE_NAME:-mid360-direct}"
INTERFACE_NAME="${INTERFACE_NAME:-eth0}"
HOST_ADDRESS="${HOST_ADDRESS:-192.168.1.5/24}"

log() { printf '[MID360-NET] %s\n' "$*"; }
die() { printf '[MID360-NET][ERROR] %s\n' "$*" >&2; exit 1; }

[[ "${EUID}" -eq 0 ]] || die "请使用 sudo 运行此脚本"
command -v nmcli >/dev/null 2>&1 || die "找不到 nmcli"
[[ -d "/sys/class/net/${INTERFACE_NAME}" ]] ||
    die "网卡不存在: ${INTERFACE_NAME}"

default_route_before="$(ip route show default || true)"

if nmcli -t -f NAME connection show | grep -Fxq "${PROFILE_NAME}"; then
    log "更新连接 ${PROFILE_NAME}"
else
    log "创建连接 ${PROFILE_NAME}"
    nmcli connection add \
        type ethernet \
        ifname "${INTERFACE_NAME}" \
        con-name "${PROFILE_NAME}"
fi

nmcli connection modify "${PROFILE_NAME}" \
    connection.interface-name "${INTERFACE_NAME}" \
    connection.autoconnect yes \
    connection.autoconnect-priority 100 \
    ipv4.method manual \
    ipv4.addresses "${HOST_ADDRESS}" \
    ipv4.gateway "" \
    ipv4.dns "" \
    ipv4.never-default yes \
    ipv6.method disabled

carrier="$(cat "/sys/class/net/${INTERFACE_NAME}/carrier" 2>/dev/null || printf '0')"
if [[ "${carrier}" == "1" ]]; then
    nmcli connection up "${PROFILE_NAME}"
else
    log "${INTERFACE_NAME} 当前无网线载波；配置已保存，到货接线后会自动连接"
fi

default_route_after="$(ip route show default || true)"
if [[ "${default_route_before}" != "${default_route_after}" ]]; then
    die "默认路由发生变化，请从备份恢复并检查 NetworkManager"
fi

nmcli -f \
connection.id,connection.interface-name,connection.autoconnect,connection.autoconnect-priority,ipv4.method,ipv4.addresses,ipv4.gateway,ipv4.never-default \
    connection show "${PROFILE_NAME}"
log "默认路由保持不变: ${default_route_after}"
