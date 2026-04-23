# Go2 Nav Workspace

本目录是 Go2 导航项目的 ROS 2 源码区，目标是在 Unitree Go2 机器狗上使用 Livox MID360 和 FAST-LIO2 提供 Nav2 所需的前置数据流。

目标运行环境：

- Ubuntu 20.04
- ROS 2 Foxy
- Unitree Go2
- Livox MID360
- FAST-LIO2
- Nav2

## 当前完成情况

已完成：

- 已完成 MID360 与 FAST-LIO2 的 SLAM 建图流程。
- Livox 驱动独立放在 `~/ws_Livox`，通过 `ros2 launch livox_ros_driver2 msg_MID360_launch.py` 启动。
- FAST-LIO2 独立放在 `~/ws_fastlio2`，通过 `ros2 launch fast_lio mapping.launch.py config_file:=.../mid360.yaml` 启动。
- 已整理 `Go2_bringup/go2_nav_start.sh`，以 shell 方式统一启动 Livox、FAST-LIO2、里程计桥接和点云转扫描链路。
- 已实现 `odom_tf_bridge`，将 FAST-LIO2 的 `/Odometry` 转成 Nav2 常用的 `/odom`，并发布 `odom -> base_link`。
- 已实现 `go2_pc2scan`，将 FAST-LIO2 的 `/cloud_registered_body` 过滤后转换为 `/scan`。
- 已保留 `Go2_time_sync` 时间同步工具，用于 NTP/PTP 辅助同步 MID360 与主机时间。

正在准备和验证：

- Nav2 前置数据流稳定性。
- `/odom`、`odom -> base_link`、`/scan` 与 Nav2 costmap 的接口一致性。
- MID360 安装外参与 FAST-LIO2 配置的一致性。当前安装图显示雷达中心约为 `X=163 mm, Y=0, Z=140 mm, 倾角13°`，应确保 FAST-LIO2 的 `mid360.yaml` 与实机安装一致。

## 目录说明

### `Go2_bringup`

统一启动脚本目录。

- `go2_nav_start.sh`：启动 Livox、FAST-LIO2、`odom_tf_bridge`、`go2_pc2scan`，并检查关键节点和话题。
- `time_sync_start.sh`：启动 NTP/PTP 时间同步辅助流程。

### `Go2_localization`

定位相关模块。

- `odom_tf_bridge`：将 FAST-LIO2 输出的 `/Odometry` 转换为 Nav2 使用的 `/odom`，并发布 `odom -> base_link`。
- `hdl-localization-ROS2`：预留给基于地图的定位链路，后续可用于发布 `map -> odom`。

### `Go2_perception`

感知相关模块。

- `pointcloud_to_laserscan`：将 FAST-LIO2 输出的 body 坐标系点云过滤并转换为 `/scan`。
- `LI_Init_calibration`：用于 LiDAR-IMU 外参初始化/标定相关工作。

### `Go2_time_sync`

时间同步模块，用于 Go2 主机和 MID360 之间的 NTP/PTP 同步辅助。

### `Go2_web_bridge`

Web 或上层交互桥接相关代码，当前不属于 Nav2 前置数据流主链路。

## 当前主启动方式

先启动时间同步：

```bash
sudo bash /home/wangzhenjie/Go2_Nav_ws/src/Go2_bringup/time_sync_start.sh
```

再启动 Nav2 前置数据流：

```bash
bash /home/wangzhenjie/Go2_Nav_ws/src/Go2_bringup/go2_nav_start.sh
```

如果在 `/home/unitree` 实机路径下运行：

```bash
LIVOX_WS=/home/unitree/ws_Livox \
FASTLIO_WS=/home/unitree/ws_fastlio2 \
GO2_NAV_WS=/home/unitree/Go2_Nav_ws \
FASTLIO_CONFIG=/home/unitree/ws_fastlio2/src/FAST_LIO_ROS2/config/mid360.yaml \
bash /home/unitree/Go2_Nav_ws/src/Go2_bringup/go2_nav_start.sh
```

## Nav2 预期输入

当前链路计划给 Nav2 提供：

- `/odom`：`nav_msgs/msg/Odometry`
- `odom -> base_link`：高频连续 TF
- `/scan`：`sensor_msgs/msg/LaserScan`

后续进入完整 Nav2 导航时，还需要补齐或确认：

- `map -> odom` 的来源，通常来自定位模块或 Nav2 AMCL/其他地图定位节点
- Nav2 costmap 中 `robot_base_frame`、`odom_frame`、`global_frame` 的配置
- `/scan` 的 `frame_id` 是否为 `base_link`
- 地图文件、Nav2 参数文件和行为树配置

## 注意事项

- 当前项目不在本机环境编译验证，实机目标为 Ubuntu 20.04 + ROS 2 Foxy。
- `go2_nav_start.sh` 会显式 source Livox、FAST-LIO2 和本项目工作空间，避免多工作空间环境变量顺序混乱。
- FAST-LIO2 建图已经完成，但导航运行时仍需确认其里程计和点云输出频率稳定。
- MID360 安装角度、外参配置和 `/cloud_registered_body` 坐标方向必须保持一致，否则 `/scan` 的障碍物高度切片会不可靠。
