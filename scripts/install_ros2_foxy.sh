#!/usr/bin/env bash
set -Eeuo pipefail

if [[ ${EUID} -ne 0 ]]; then
  echo "请使用 sudo bash $0 运行此脚本" >&2
  exit 1
fi

source /etc/os-release
if [[ ${ID:-} != ubuntu || ${VERSION_ID:-} != 20.04 ]]; then
  echo "ROS 2 Foxy 二进制包要求 Ubuntu 20.04；当前系统为 ${PRETTY_NAME:-未知}" >&2
  exit 1
fi

arch="$(dpkg --print-architecture)"
case "$arch" in
  amd64|arm64) ;;
  *) echo "不支持的架构：$arch" >&2; exit 1 ;;
esac

export DEBIAN_FRONTEND=noninteractive

apt-get update
apt-get install -y \
  software-properties-common curl gnupg2 lsb-release locales ca-certificates
add-apt-repository -y universe

locale-gen en_US en_US.UTF-8
update-locale LC_ALL=en_US.UTF-8 LANG=en_US.UTF-8

install -d -m 0755 /usr/share/keyrings
curl -fsSL https://raw.githubusercontent.com/ros/rosdistro/master/ros.key \
  -o /usr/share/keyrings/ros-archive-keyring.gpg
printf 'deb [arch=%s signed-by=/usr/share/keyrings/ros-archive-keyring.gpg] http://packages.ros.org/ros2/ubuntu focal main\n' "$arch" \
  > /etc/apt/sources.list.d/ros2.list

apt-get update
apt-get install -y \
  ros-foxy-desktop \
  ros-foxy-nav2-bringup \
  ros-foxy-pointcloud-to-laserscan \
  ros-foxy-rosbridge-server \
  ros-foxy-tf-transformations \
  python3-colcon-common-extensions \
  python3-rosdep \
  python3-vcstool \
  python3-pip \
  build-essential cmake git

cat > /etc/profile.d/ros2-foxy.sh <<'EOF'
if [ -f /opt/ros/foxy/setup.sh ]; then
  . /opt/ros/foxy/setup.sh
fi
EOF
chmod 0644 /etc/profile.d/ros2-foxy.sh

if [[ ! -f /etc/ros/rosdep/sources.list.d/20-default.list ]]; then
  rosdep init
fi

target_user="${SUDO_USER:-root}"
if [[ "$target_user" != root ]]; then
  sudo -H -u "$target_user" rosdep update --rosdistro foxy
else
  rosdep update --rosdistro foxy
fi

echo
echo "ROS 2 Foxy 安装完成："
# ros2 的 Python 模块路径由 ROS 环境脚本注入，验证前必须先加载。
source /opt/ros/foxy/setup.bash
ros2 --help >/dev/null
dpkg-query -W -f='${Package} ${Version}\n' ros-foxy-desktop
echo "新终端会自动加载 /opt/ros/foxy/setup.sh"
