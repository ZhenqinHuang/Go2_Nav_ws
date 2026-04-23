#!/bin/bash
# 启动 LI-Init 标定容器（ROS1 Noetic）
# 容器内直接连接 MID360 硬件，无需宿主机转发
set -e

IMAGE_NAME="liinit:humble-arm64"
RESULT_DIR="$(cd "$(dirname "$0")" && pwd)/results"
mkdir -p "$RESULT_DIR"

if ! docker image inspect "$IMAGE_NAME" &>/dev/null; then
    echo "Image not found. Run ./build_docker.sh first."
    exit 1
fi

echo "Starting LI-Init container (ROS1 Noetic)..."
echo ""
echo "Inside the container, run in order:"
echo ""
echo "  # 终端1：启动 roscore"
echo "  roscore"
echo ""
echo "  # 终端2：启动 MID360 驱动（CustomMsg 格式）"
echo "  roslaunch livox_ros_driver2 msg_MID360.launch"
echo ""
echo "  # 终端3：启动 LI-Init 标定"
echo "  roslaunch lidar_imu_init livox_mid360.launch rviz:=false"
echo ""
echo "  控制 GO2 做激励运动（平移+旋转），等待收敛输出结果"
echo ""

docker run -it --rm \
    --network host \
    --privileged \
    -v "$RESULT_DIR":/results \
    "$IMAGE_NAME" \
    bash
