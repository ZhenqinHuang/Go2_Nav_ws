#!/usr/bin/env bash
set -Eeuo pipefail

WORKSPACE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
exec "${WORKSPACE}/src/Go2_bringup/start_mapping.sh" "$@"
