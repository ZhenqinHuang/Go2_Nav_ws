#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PACKAGE_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
BUILD_DIR="$(mktemp -d /tmp/go2-cmd-gateway-build.XXXXXX)"

cleanup() {
  rm -rf -- "${BUILD_DIR}"
}
trap cleanup EXIT

echo "[internal-deploy] Building native Unitree SDK gateway..."
cmake -S "${PACKAGE_DIR}/internal_gateway" \
  -B "${BUILD_DIR}" \
  -DGO2_GATEWAY_BUILD_SDK=ON \
  -DCMAKE_BUILD_TYPE=Release
cmake --build "${BUILD_DIR}" -j2

echo "[internal-deploy] Stopping old service through its fail-closed path..."
sudo systemctl stop go2-cmd-gateway.service 2>/dev/null || true
sudo install -m 0755 "${BUILD_DIR}/go2_cmd_gateway" /usr/local/bin/go2_cmd_gateway
sudo install -d -m 0755 /etc/go2-cmd-gateway
sudo install -m 0644 \
  "${PACKAGE_DIR}/config/internal_gateway.env" \
  /etc/go2-cmd-gateway/gateway.env
sudo install -m 0644 \
  "${PACKAGE_DIR}/systemd/go2-cmd-gateway.service" \
  /etc/systemd/system/go2-cmd-gateway.service

sudo systemctl daemon-reload
sudo systemctl enable --now go2-cmd-gateway.service
sudo systemctl --no-pager --full status go2-cmd-gateway.service
echo "[internal-deploy] Installed. Service startup state is always LOCKED."
