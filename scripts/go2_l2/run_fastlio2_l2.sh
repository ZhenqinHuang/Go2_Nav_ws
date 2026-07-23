#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
CONFIG_DIR="${SCRIPT_DIR}/config"
PROBE="${SCRIPT_DIR}/l2_input_probe.py"
UNITREE_INTERFACE="${UNITREE_INTERFACE:-eth0}"
PROBE_DURATION="${PROBE_DURATION:-6}"
RVIZ="${RVIZ:-false}"

PROBE_ONLY=false
SKIP_PROBE=false

usage() {
    echo "Usage: $0 [--probe-only] [--skip-probe]"
    echo
    echo "Environment:"
    echo "  UNITREE_INTERFACE  Robot network interface (default: eth0)"
    echo "  PROBE_DURATION     Input validation duration in seconds (default: 6)"
    echo "  RVIZ               Pass true to launch RViz (default: false)"
}

while (($#)); do
    case "$1" in
        --probe-only)
            PROBE_ONLY=true
            ;;
        --skip-probe)
            SKIP_PROBE=true
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        *)
            echo "Unknown argument: $1" >&2
            usage >&2
            exit 2
            ;;
    esac
    shift
done

require_file() {
    if [[ ! -f "$1" ]]; then
        echo "Required file not found: $1" >&2
        exit 1
    fi
}

require_file "/home/nvidia/unitree_ros2/setup.sh"
require_file "/home/nvidia/ws_Livox/install/setup.bash"
require_file "/home/nvidia/ws_fastlio2/install/setup.bash"
require_file "${CONFIG_DIR}/go2_l2.yaml"
require_file "${PROBE}"

export UNITREE_INTERFACE
# shellcheck source=/dev/null
source "/home/nvidia/unitree_ros2/setup.sh"
# FAST_LIO_ROS2 links against livox_ros_driver2 message types even though the
# L2 input path itself uses sensor_msgs/PointCloud2.
# shellcheck source=/dev/null
source "/home/nvidia/ws_Livox/install/setup.bash"
# shellcheck source=/dev/null
source "/home/nvidia/ws_fastlio2/install/setup.bash"

if [[ "${SKIP_PROBE}" != true ]]; then
    python3 "${PROBE}" \
        --duration "${PROBE_DURATION}" \
        --report "/tmp/go2_l2_input_report.json"
fi

if [[ "${PROBE_ONLY}" == true ]]; then
    exit 0
fi

exec ros2 launch fast_lio mapping.launch.py \
    config_path:="${CONFIG_DIR}" \
    config_file:=go2_l2.yaml \
    rviz:="${RVIZ}"
