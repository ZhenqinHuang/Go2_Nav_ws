FROM hub.rat.dev/arm64v8/ros:noetic-ros-base

ENV DEBIAN_FRONTEND=noninteractive
ENV ROS_DISTRO=noetic

# 换阿里云 apt 源
RUN sed -i 's|http://ports.ubuntu.com|http://mirrors.aliyun.com|g' /etc/apt/sources.list && \
    sed -i 's|http://archive.ubuntu.com|http://mirrors.aliyun.com|g' /etc/apt/sources.list

RUN apt-get update && apt-get install -y \
    cmake build-essential \
    ros-noetic-pcl-ros \
    ros-noetic-tf \
    ros-noetic-eigen-conversions \
    ros-noetic-nav-msgs \
    ros-noetic-geometry-msgs \
    libpcl-dev libeigen3-dev \
    libceres-dev \
    python3-catkin-tools \
    python-is-python3 \
    && rm -rf /var/lib/apt/lists/*

# 安装 Livox SDK
COPY sdk/lib/liblivox_lidar_sdk_shared.so /usr/local/lib/
COPY sdk/lib/liblivox_lidar_sdk_static.a /usr/local/lib/
COPY sdk/include/ /usr/local/include/
RUN ldconfig

# 建立 catkin workspace
RUN mkdir -p /liinit_ws/src
WORKDIR /liinit_ws/src

# COPY 源码
COPY src/livox_ros_driver2 ./livox_ros_driver2
COPY src/livox_ros_driver ./livox_ros_driver
COPY src/LiDAR_IMU_Init ./LiDAR_IMU_Init

# livox_ros_driver2 在 ROS1 下用 package_ROS1.xml
RUN cp /liinit_ws/src/livox_ros_driver2/package_ROS1.xml \
       /liinit_ws/src/livox_ros_driver2/package.xml

WORKDIR /liinit_ws

# 第一步：生成消息头文件（livox_ros_driver 只需消息，不编译节点）
RUN bash -c "source /opt/ros/noetic/setup.bash && \
    catkin_make -DCMAKE_BUILD_TYPE=Release -DROS_EDITION=ROS1 \
    lidar_imu_init_generate_messages livox_ros_driver_generate_messages 2>&1"

# 第二步：屏蔽 livox_ros_driver 节点编译，只编译 li_init 和 livox_ros_driver2
RUN touch /liinit_ws/src/livox_ros_driver/CATKIN_IGNORE && \
    bash -c "source /opt/ros/noetic/setup.bash && \
    catkin_make -DCMAKE_BUILD_TYPE=Release -DROS_EDITION=ROS1 2>&1"

COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

ENTRYPOINT ["/entrypoint.sh"]
CMD ["bash"]
