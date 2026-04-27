# Go2 Nav Workspace

宇树 Go2 机器狗自主导航项目。在 Jetson Orin NX 16GB 上，使用 Livox MID360 + FAST-LIO2 + fast_lio_localization_ros2 为 Nav2 提供完整的感知与定位数据流。

| 项目 | 内容 |
|---|---|
| 机器人 | Unitree Go2 |
| 激光雷达 | Livox MID360（倾斜安装 13°） |
| 计算平台 | Jetson Orin NX 16GB |
| 操作系统 | Ubuntu 20.04 |
| ROS 版本 | ROS 2 Foxy |
| 里程计 | FAST-LIO2（LiDAR-IMU 紧耦合） |
| 重定位 | fast_lio_localization_ros2（ICP 点云匹配） |
| 导航框架 | Nav2 |

---

## 整体数据流

```
MID360 LiDAR + IMU
        │
   FAST-LIO2 (LiDAR-IMU 紧耦合里程计)
        │
        ├─ /Odometry ──────────────────> odom_tf_bridge
        │   (camera_init → body, BEST_EFFORT)         │
        │                               /odom + odom→base_link TF (RELIABLE)
        │
        ├─ /cloud_registered ──────────> fast_lio_localization_ros2
        │   (world 帧，camera_init)     ├─ pcd_publisher  → /map3d
        │                               ├─ global_localization (ICP) → /map_to_odom
        │                               └─ transform_fusion → map→odom TF + /localization
        │
        └─ /cloud_registered_body ─────> go2_pc2scan
                                        ├─ cloud_filter_node → /cloud_filtered
                                        └─ pointcloud_to_laserscan → /scan
```

## TF 树

```
map ──(transform_fusion, 100 Hz)──> odom ──(odom_tf_bridge, 10 Hz)──> base_link
```

- `odom → base_link`：odom_tf_bridge 广播，来自 FAST-LIO2 高频里程计（10 Hz）
- `map → odom`：transform_fusion 广播，来自 ICP 重定位结果（0.5 Hz 更新，100 Hz 广播）

## 时间链路

```
主机系统时钟（NTP 同步）
        │
  Livox 驱动使用系统时间为点云打时间戳
  /livox/lidar.header.stamp
        │
  FAST-LIO2 透传 → /Odometry.stamp, /cloud_registered.stamp, /cloud_registered_body.stamp
        │
  各节点透传 → /odom.stamp, /cloud_filtered.stamp, /scan.stamp
```

> **注意**：MID360 的 PTP 硬件时间同步当前不可用，统一使用主机系统时钟。所有消息时间戳来自同一时钟源，TF 查询一致性可保证。建议保持主机系统时钟通过 NTP 同步到准确时间。

---

## Nav2 接口

| 话题 / TF | 消息类型 | 频率 | QoS | 来源 |
|---|---|---|---|---|
| `/odom` | `nav_msgs/Odometry` | 10 Hz | RELIABLE | odom_tf_bridge |
| `odom → base_link` | TF | 10 Hz | — | odom_tf_bridge |
| `map → odom` | TF | 100 Hz | — | transform_fusion |
| `/localization` | `nav_msgs/Odometry` | 100 Hz | RELIABLE | transform_fusion |
| `/scan` | `sensor_msgs/LaserScan` | 10 Hz | RELIABLE | go2_pc2scan |

---

## 模块目录

| 目录 | 说明 |
|---|---|
| `src/Go2_bringup` | 启动脚本：`go2_nav_start.sh`、`time_sync_start.sh`、`check_nav2_ready.sh` |
| `src/Go2_localization` | 定位模块：odom_tf_bridge + fast_lio_localization_ros2 |
| `src/Go2_perception` | 感知模块：go2_pc2scan（点云过滤 + LaserScan 转换） |
| `src/Go2_time_sync` | 时间同步：PTP Master 向 MID360 提供精确时间 |
| `src/Go2_Slam` | 建图说明（FAST-LIO2 离线建图） |

---

## 快速开始

### 1. 依赖安装

```bash
# ROS 2 依赖
sudo apt install ros-foxy-tf-transformations ros-foxy-pointcloud-to-laserscan

# Python 依赖
pip3 install open3d "numpy<2" pyyaml

# PTP 时间同步
sudo apt install linuxptp ethtool
```

### 2. 编译

`src/Go2_perception/LI_Init_calibration` 是 ROS1 catkin 包，已通过 `COLCON_IGNORE` 跳过，直接整仓编译即可：

```bash
cd ~/Go2_Nav_ws
colcon build --symlink-install
source install/setup.bash
```

### 3. 建图（首次使用）

使用 FAST-LIO2 建图并保存 PCD 文件：

```bash
# 在 FAST-LIO2 工作空间中启动建图
ros2 launch fast_lio mapping.launch.py config_path:=... config_file:=mid360.yaml

# 建图完成后保存地图（FAST-LIO2 会在 PCD 目录生成地图）
cp /path/to/scans.pcd ~/Go2_Nav_ws/src/Go2_localization/PCD/MID360.pcd
```

### 4. 启动导航前置链路

```bash
# 启动完整数据链路
bash ~/Go2_Nav_ws/src/Go2_bringup/go2_nav_start.sh
```

自定义工作空间路径（实机 /home/unitree 环境）：

```bash
LIVOX_WS=/home/unitree/ws_Livox \
FASTLIO_WS=/home/unitree/ws_fastlio2 \
GO2_NAV_WS=/home/unitree/Go2_Nav_ws \
FASTLIO_CONFIG=/home/unitree/ws_fastlio2/src/FAST_LIO_ROS2/config/mid360.yaml \
FASTLIO_LOC_PCD=/home/unitree/Go2_Nav_ws/src/Go2_localization/PCD/MID360.pcd \
bash /home/unitree/Go2_Nav_ws/src/Go2_bringup/go2_nav_start.sh
```

### 5. 验证数据链路

```bash
# 一键检查：话题频率、TF 完整性、时间戳新鲜度
bash ~/Go2_Nav_ws/src/Go2_bringup/check_nav2_ready.sh
```

手动检查：

```bash
# TF 树
ros2 run tf2_ros tf2_echo map base_link

# 关键话题频率
ros2 topic hz /odom
ros2 topic hz /scan
ros2 topic hz /map_to_odom   # ICP 重定位，约 0.5 Hz

# 重定位位姿
ros2 topic echo /localization --once
```

### 6. 触发重定位

向 `/initialpose` 发布初始位姿（与 RViz2 的 "2D Pose Estimate" 按钮兼容）：

```bash
ros2 topic pub /initialpose geometry_msgs/msg/PoseWithCovarianceStamped \
  "{header: {frame_id: map}, pose: {pose: {position: {x: 0.0, y: 0.0}, orientation: {w: 1.0}}}}" --once
```

---

## 已完成

- MID360 + FAST-LIO2 SLAM 建图流程
- `odom_tf_bridge`：`/Odometry` (camera_init→body) → `/odom` (odom→base_link) + TF 广播
- `fast_lio_localization_ros2`：PCD 地图 ICP 重定位，发布 `map→odom` TF
- `go2_pc2scan`：点云高度过滤 + LaserScan 转换
- `go2_nav_start.sh`：一键有序启动全链路
- `check_nav2_ready.sh`：Nav2 前置链路完整性检查
- `Go2_time_sync`：PTP 时间同步（MID360 ↔ 主机）

## 待完成

- Nav2 完整配置（costmap、行为树、路径规划参数文件）
- Nav2 启动脚本 `nav2_start.sh`
正在完善 Go2 机器狗自主导航项目的重定位模块。所有代码和文档问题已修复并推送到 GitHub，等待明天实机测试验证。 