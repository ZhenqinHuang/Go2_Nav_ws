#!/usr/bin/env bash
set -eo pipefail

lidar_ip="${LIDAR_IP:-192.168.1.158}"
interface="$(ip route get "$lidar_ip" | awk '{for (i=1; i<=NF; i++) if ($i=="dev") {print $(i+1); exit}}')"
[[ -n "$interface" ]] || { echo "no route to LiDAR $lidar_ip" >&2; exit 1; }

echo "interface=$interface"
ip -brief address show "$interface"
ping -c 1 -W 1 "$lidar_ip" >/dev/null
echo "lidar_reachable=true"
ethtool -T "$interface" | sed -n '1,16p'
printf "ptp4l=%s\n" "$(command -v ptp4l)"
echo "ptp_processes:"
pgrep -af '[p]tp4l|[p]hc2sys' || true
timedatectl show -p NTPSynchronized -p NTP -p Timezone
