# Go2 Nav Workspace

宇树 Go2 机器狗完整自主导航项目。在 Jetson Orin NX 16GB 上，使用 Livox MID360 + FAST-LIO2 + fast_lio_localization_ros2 为 Nav2 提供完整的感知与定位数据流，并通过局域网 Web 控制台和云端 WebSocket 桥接实现远程任务下发。

| 项目 | 内容 |
|---|---|
| 机器人 | Unitree Go2 |
| 激光雷达 | Livox MID360（倾斜安装 13°） |
| 计算平台 | Jetson Orin NX 16GB |
| 操作系统 | Ubuntu 20.04 |
| ROS 版本 | ROS 2 Foxy |
| 里程计 | FAST-LIO2（LiDAR-IMU 紧耦合） |
| 重定位 | fast_lio_localization_ros2（ICP 点云匹配） |
| 导航框架 | Nav2（DWB 局部控制器） |
| 交互界面 | 局域网 Web 控制台 + 云端 WebSocket 桥接 |

MID360 在 Jetson 上的安装、接线、验证与故障恢复，请先阅读
[《MID360 直连 Jetson 技术手册》](docs/MID360_Jetson_Foxy_技术手册.md)。
本次实际部署证据见
[《MID360 安装记录（2026-07-23）》](docs/mid360/安装记录_2026-07-23.md)。

Go2 与 Jetson 的直连网络、CycloneDDS 环境、Sport API 控制权冲突及实机验证状态，
请阅读
[《Go2 直连 Jetson 控制验证记录（2026-07-23）》](docs/go2/控制验证记录_2026-07-23.md)。

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

/odom + /scan + map→odom TF
        │
     Nav2 (go2_nav2)
        ├─ map_server      → /map（2D 占据栅格地图）
        ├─ planner_server  → 全局路径规划（NavFn）
        ├─ controller_server → 局部控制（DWB）→ /cmd_vel
        ├─ recoveries_server → 恢复行为（Spin/BackUp/Wait）
        └─ bt_navigator    → 行为树决策
                │
        go2_cmd_vel_bridge
                │
        Go2 Sport API（机体运动控制）

/odom + /localization + /navigate_to_pose/_action/status
        │
   Go2_web_bridge
        ├─ web_bridge_node  → 云端 WebSocket（上行位姿/导航状态，下行目标点/TTS）
        ├─ tts_node         → 中文 TTS 语音播报
        └─ rosbridge_websocket → 局域网 WebSocket（浏览器 Web UI）
                │
        Vite Web 控制台 (http://<机器狗IP>:5173)
```

## TF 树

```
map ──(transform_fusion, 100 Hz)──> odom ──(odom_tf_bridge, 10 Hz)──> base_link
```

- `odom → base_link`：odom_tf_bridge 广播，来自 FAST-LIO2 高频里程计（10 Hz）
- `map → odom`：transform_fusion 广播，来自 ICP 重定位结果（目标 1.5 Hz 更新，100 Hz 广播）

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
| `/map` | `nav_msgs/OccupancyGrid` | latched | RELIABLE | map_server |
| `/cmd_vel` | `geometry_msgs/Twist` | — | RELIABLE | controller_server |

---

## 模块目录

| 目录 | 说明 |
|---|---|
| `src/Go2_bringup` | 启动脚本：`go2_autostart.sh`（全链路一键启动）、`go2_nav_start.sh`（定位链路）、`run_nav2.sh`（Nav2）、`run_robot_web.sh`（Web 控制台）、`run_web_bridge.sh`（云端桥接） |
| `src/Go2_localization` | 定位模块：odom_tf_bridge + fast_lio_localization_ros2 |
| `src/Go2_perception` | 感知模块：go2_pc2scan（点云过滤 + LaserScan 转换）、pcd_to_map（PCD → 2D 占据栅格地图） |
| `src/Go2_nav2` | Nav2 导航模块：完整参数配置、DWB 局部控制器、自定义行为树、cmd_vel → Go2 Sport API 桥接、TTS 播报 |
| `src/Go2_web_bridge` | 远程控制模块：云端 WebSocket 桥接 + 局域网 rosbridge |
| `src/Go2_time_sync` | 时间同步：PTP Master 向 MID360 提供精确时间（当前未启用） |
| `src/Go2_Slam` | 建图说明（FAST-LIO2 离线建图） |
| `maps/` | 预构建地图文件（MID360_map.pgm + MID360_map.yaml） |

---

## 快速开始

### 1. 依赖安装

```bash
# ROS 2 依赖
sudo apt install ros-foxy-tf-transformations ros-foxy-pointcloud-to-laserscan \
    ros-foxy-nav2-bringup ros-foxy-rosbridge-server

# Python 依赖
pip3 install open3d "numpy<2" pyyaml websockets edge-tts

# PTP 时间同步（可选）
sudo apt install linuxptp ethtool
```

### 2. 编译

```bash
cd ~/Go2_Nav_ws
colcon build --symlink-install
source install/setup.bash
```

### 3. 建图（首次使用）

```bash
# 启动 Livox 驱动
ros2 launch livox_ros_driver2 msg_MID360_launch.py

# 启动 FAST-LIO2 建图
ros2 launch fast_lio mapping.launch.py \
  config_path:=~/ws_fastlio2/src/FAST_LIO_ROS2/config \
  config_file:=mid360.yaml rviz:=true

# 建图完成后保存地图
cp /path/to/scans.pcd ~/Go2_Nav_ws/src/Go2_localization/PCD/MID360.pcd

# 转换 2D 占据栅格地图
ros2 launch pcd_to_map pcd_to_map.launch.py \
  pcd_file:=~/Go2_Nav_ws/src/Go2_localization/PCD/MID360.pcd \
  output_path:=~/Go2_Nav_ws/maps/MID360_map
```

### 4. 一键启动全链路（推荐）

```bash
# 最简方式（使用默认地图路径）
bash ~/Go2_Nav_ws/src/Go2_bringup/go2_autostart.sh

# 指定地图
MAP_YAML=~/Go2_Nav_ws/maps/MID360_map.yaml \
bash ~/Go2_Nav_ws/src/Go2_bringup/go2_autostart.sh
```

`go2_autostart.sh` 按顺序启动：
1. 传感器定位链路（Livox → FAST-LIO2 → 定位 → 点云转换）
2. Nav2 决策层（地图服务 + 路径规划 + 局部控制）
3. 局域网 Web 控制台（rosbridge + Vite，默认开启）
4. 云端 WebSocket 桥接（默认关闭，需 `USE_WEB_BRIDGE=true`）

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
ros2 topic hz /map_to_odom   # ICP 重定位，目标 1.5 Hz，建议 ≥ 1.0 Hz

# Nav2 Action 是否就绪
ros2 action list | grep navigate_to_pose
```

### 6. 发送导航目标

**方式一：RViz2 点击目标点**（通过 RViz2 的 "Nav2 Goal" 按钮）

**方式二：Web 控制台**（浏览器访问 `http://<机器狗IP>:5173`）

**方式三：命令行**

```bash
ros2 action send_goal /navigate_to_pose nav2_msgs/action/NavigateToPose \
  "{pose: {header: {frame_id: map}, pose: {position: {x: 1.0, y: 0.5}, orientation: {w: 1.0}}}}"
```

### 7. 触发全局重定位

向 `/initialpose` 发布初始位姿（与 RViz2 的 "2D Pose Estimate" 按钮兼容）：

```bash
ros2 topic pub /initialpose geometry_msgs/msg/PoseWithCovarianceStamped \
  "{header: {frame_id: map}, pose: {pose: {position: {x: 0.0, y: 0.0}, orientation: {w: 1.0}}}}" --once
```

---

## 环境变量总览

| 变量 | 默认值 | 说明 |
|---|---|---|
| `MAP_YAML` | `~/Go2_Nav_ws/maps/MID360_map.yaml` | Nav2 地图文件路径 |
| `LIVOX_WS` | `~/ws_Livox` | Livox 驱动工作空间 |
| `FASTLIO_WS` | `~/ws_fastlio2` | FAST-LIO2 工作空间 |
| `FASTLIO_LOC_PCD` | `Go2_localization/PCD/MID360_localization_filtered.pcd` | 定位用 PCD 文件 |
| `USE_WEB_BRIDGE` | `false` | 是否启用云端 WebSocket 桥接 |
| `USE_ROBOT_WEB` | `true` | 是否启动局域网 Web 控制台 |
| `SERVER_URL` | `ws://121.40.212.85:30100/...` | 云端 WebSocket 服务器地址 |
| `RVIZ` | `false` | 是否同步启动 RViz2 |
| `WAIT_TIMEOUT` | `60` | 每步等待超时时间（秒） |
| `CONTROLLER` | `dwb` | Nav2 局部控制器（`dwb` 或 `rpp`） |

---

## 已完成功能

- [x] MID360 + FAST-LIO2 SLAM 建图流程
- [x] `odom_tf_bridge`：FAST-LIO2 `/Odometry` → `/odom` + `odom→base_link` TF
- [x] `fast_lio_localization_ros2`：PCD 地图 ICP 重定位，发布 `map→odom` TF
- [x] `go2_pc2scan`：点云高度过滤 + LaserScan 转换
- [x] `pcd_to_map`：PCD → 2D 占据栅格地图（`.pgm` + `.yaml`）
- [x] `go2_nav2`：完整 Nav2 配置（DWB 控制器 + 自定义行为树 + 代价地图）
- [x] `go2_cmd_vel_bridge`：Nav2 `/cmd_vel` → Go2 Sport API 桥接
- [x] `nav_tts_announcer`：导航完成 TTS 语音播报
- [x] `go2_autostart.sh`：全链路一键启动（定位 + Nav2 + Web UI）
- [x] `check_nav2_ready.sh`：Nav2 前置链路完整性检查
- [x] `Go2_web_bridge`：云端 WebSocket 桥接（位姿上报 + 目标点下发）
- [x] 局域网 Web 控制台（rosbridge + Vite 前端）
- [x] `Go2_time_sync`：PTP 时间同步工具（当前未启用）
