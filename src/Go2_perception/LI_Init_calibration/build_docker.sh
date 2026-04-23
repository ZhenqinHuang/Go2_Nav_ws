#!/bin/bash
# 构建 LI-Init Docker 镜像（aarch64/Jetson）
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
IMAGE_NAME="liinit:humble-arm64"

# 检查源码是否存在
if [ ! -d "$SCRIPT_DIR/src/livox_ros_driver2" ] || [ ! -d "$SCRIPT_DIR/src/LiDAR_IMU_Init" ]; then
    echo "Error: src/livox_ros_driver2 or src/LiDAR_IMU_Init not found."
    echo "Please place source code under src/ before building."
    exit 1
fi

echo "[1/1] Building Docker image: $IMAGE_NAME"
docker build -t "$IMAGE_NAME" "$SCRIPT_DIR"

echo ""
echo "Build complete. Run calibration with:"
echo "  ./run_liinit.sh"
