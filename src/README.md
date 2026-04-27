# Go2 Nav Workspace — src

Go2 导航项目的 ROS 2 源码目录。在 Unitree Go2 机器狗上使用 Livox MID360 + FAST-LIO2 + fast_lio_localization_ros2 提供 Nav2 所需的完整数据流。

运行环境：Ubuntu 20.04 / ROS 2 Foxy / Unitree Go2 / Livox MID360 / Jetson Orin NX 16GB

---

## 数据流总览

```
MID360 LiDAR + IMU
        │
   FAST-LIO2 (LiDAR-IMU 紧耦合里程计)
        │
        ├─ /Odometry (BEST_EFFORT) ──> odom_tf_bridge ──> /odom + odom→base_link TF (RELIABLE)
        │
        ├─ /cloud_registered_body ──> fast_lio_localization_ros2
        │   ├─ pcd_publisher:        发布 /map3d（全局地图点云）
        │   ├─ global_localization:  ICP 地图匹配 → /map_to_odom（0.5 Hz）
        │   └─ transform_fusion:     map→odom TF (100 Hz) + /localization
        │
        └─ /cloud_registered_body ──> go2_pc2scan
            ├─ cloud_filter_node:    高度/距离过滤 → /cloud_filtered
            └─ pointcloud_to_laserscan: 投影为 /scan（360°, 10 Hz）
```

**TF 树：**
```
map ──(transform_fusion, 100 Hz)──> odom ──(odom_tf_bridge, 10 Hz)──> base_link
```

---

## 完成情况

已完成：

- MID360 + FAST-LIO2 SLAM 建图流程
- `odom_tf_bridge`：FAST-LIO2 `/Odometry` (camera_init→body) → `/odom` (odom→base_link) + TF 广播
- `fast_lio_localization_ros2`：基于 PCD 地图的 ICP 重定位，广播 `map→odom` TF
- `go2_pc2scan`：`/cloud_registered_body` 高度过滤后转换为 `/scan`
- `go2_nav_start.sh`：一键启动完整数据链路
- `check_nav2_ready.sh`：Nav2 前置链路完整性检查脚本
- `Go2_time_sync`：PTP 时间同步（MID360 ↔ 主机）

待完成：

- Nav2 完整导航配置（costmap、行为树、路径规划参数）
- Nav2 启动脚本

---

## 目录说明

### `Go2_bringup`

- `go2_nav_start.sh`：一键有序启动全链路（Livox → FAST-LIO2 → odom_tf_bridge → fast_lio_localization → go2_pc2scan）
- `time_sync_start.sh`：启动 PTP 时间同步（需 sudo）
- `check_nav2_ready.sh`：检查所有 Nav2 前置条件（话题频率、TF 树、时间戳）

### `Go2_localization`

- `odom_tf_bridge`：FAST-LIO2 里程计格式转换与 TF 广播（camera_init/body → odom/base_link）
- `fast_lio_localization_ros2`：ICP 点云地图定位与全局重定位（产生 `map→odom` TF）
- `PCD/MID360.pcd`：默认全局地图文件

### `Go2_perception`

- `go2_pc2scan`（`pointcloud_to_laserscan`）：点云高度/距离过滤 + 转 LaserScan

### `Go2_time_sync`

PTP 时间同步工具（当前 MID360 PTP 不可用，暂不使用）。统一使用主机系统时钟，建议通过 NTP 保持系统时间准确。

### `Go2_Slam`

FAST-LIO2 建图说明（离线建图，产生供重定位使用的 PCD 地图文件）。

---

## 依赖安装

```bash
# ROS 2 依赖
sudo apt install ros-foxy-tf-transformations ros-foxy-pointcloud-to-laserscan

# Python 点云处理
pip3 install open3d "numpy<2"
```

---

## 启动方式

```bash
# 启动完整导航链路
bash /home/wangzhenjie/Go2_Nav_ws/src/Go2_bringup/go2_nav_start.sh

# 验证数据链路
bash /home/wangzhenjie/Go2_Nav_ws/src/Go2_bringup/check_nav2_ready.sh
```

---

## Nav2 接口

当前链路向 Nav2 提供的标准接口：

| 话题 / TF | 消息类型 | 频率 | QoS |
|---|---|---|---|
| `/odom` | `nav_msgs/Odometry` | 10 Hz | RELIABLE |
| `odom → base_link` | TF | 10 Hz | — |
| `map → odom` | TF | 100 Hz | — |
| `/localization` | `nav_msgs/Odometry` | 100 Hz | RELIABLE |
| `/scan` | `sensor_msgs/LaserScan` | 10 Hz | RELIABLE |

---

## 注意事项

- 首次运行前需先用 FAST-LIO2 建图，将地图保存为 PCD 放到 `Go2_localization/PCD/MID360.pcd`
- MID360 安装外参须与 FAST-LIO2 的 `mid360.yaml` 保持一致
- 重定位触发：向 `/initialpose` 发布 `geometry_msgs/PoseWithCovarianceStamped`（与 RViz2 的 "2D Pose Estimate" 按钮兼容）
- `transform_fusion` 和 `global_localization` 通过 remapping 直接订阅 FAST-LIO2 的 `/Odometry`（原始 camera_init→body），而非 odom_tf_bridge 的 `/odom`，这是有意设计——两者坐标系等价（camera_init≡odom, body≡base_link），直接使用原始数据避免一次转换
