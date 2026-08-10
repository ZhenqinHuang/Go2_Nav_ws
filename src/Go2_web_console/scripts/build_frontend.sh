#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PACKAGE_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
FRONTEND_DIR="${PACKAGE_DIR}/frontend"
WEB_DIR="${PACKAGE_DIR}/go2_web_console/web"
NODE_BIN_DIR="${NODE_BIN_DIR:-${HOME}/.local/node/v20.19.1/bin}"

if [[ -d "${NODE_BIN_DIR}" ]]; then
  export PATH="${NODE_BIN_DIR}:${PATH}"
fi

if [[ ! -f "${FRONTEND_DIR}/package-lock.json" ]]; then
  echo "[frontend-build] missing package-lock.json" >&2
  exit 1
fi

bundle_complete() {
  [[ -f "${WEB_DIR}/index.html" ]] && \
    find "${WEB_DIR}/assets" -maxdepth 1 -type f -name '*.js' \
      -print -quit | grep -q .
}

if ! command -v npm >/dev/null 2>&1; then
  if bundle_complete; then
    echo "[frontend-build] npm unavailable; production bundle already present; skipping target build."
    exit 0
  fi
  echo "[frontend-build] npm is unavailable and production bundle is incomplete" >&2
  exit 1
fi

cd "${FRONTEND_DIR}"
npm ci
npm test -- --run
npm run build

if ! bundle_complete; then
  echo "[frontend-build] production bundle is incomplete: ${WEB_DIR}" >&2
  exit 1
fi

echo "[frontend-build] production assets ready in go2_web_console/web"
