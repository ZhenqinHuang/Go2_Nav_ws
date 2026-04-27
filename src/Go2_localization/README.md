# Go2_localization

Go2 机器狗定位模块，基于 **FAST-LIO2 + fast_lio_localization_ros2** 实现 LiDAR-IMU 里程计与 PCD 地图点云重定位。

---

## 架构概览

```
MID360 LiDAR + IMU
        │
   FAST-LIO2 (LiDAR-IMU 紧耦合里程计)
        │  /Odometry (camera_init→body, BEST_EFFORT, 10 Hz)
        │  /cloud_registered_body (body 坐标系点云, BEST_EFFORT, 10 Hz)
        │
        ├─ /Odometry ──────────────> odom_tf_bridge
        │                            ├─ 重命名: camera_init→odom, body→base_link
        │                            ├─ 补充协方差默认值
        │                            ├─ 发布 /odom (RELIABLE, 10 Hz)
        │                            └─ 广播 TF: odom→base_link (10 Hz)
        │
        └─ /cloud_registered_body ─> fast_lio_localization_ros2
                                     ├─ pcd_publisher: 发布 /map3d (1 Hz, TRANSIENT_LOCAL)
                                     ├─ global_localization: ICP
                                      地图匹配 → /map_to_odom (0.5 Hz)
                                     └─ transform_fusion: map→odom TF (100 Hz) + /localization
```

**完整 TF 树：**
```
map ──(transform_fusion, 100 Hz)──> odom ──(odom_tf_bridge, 10 Hz)──> base_link
```

---

## 时间链路

```
MID360 硬件时钟 (PTP Slave 同步到主机)
  ↓ Livox 驱动提取硬件时间戳
/Odometry.header.stamp, /cloud_registered_body.header.stamp
  ↓ odom_tf_bridge 透传时间戳
/odom.header.stamp
  ↓ transform_fusion 使用 /odom 时间戳广播 TF
map→odom TF.header.stamp = /odom.stamp
```

所有 TF 的时间戳与里程计时间戳保持一致，避免 TF 查询时间不匹配错误。

---

## 坐标系关系

| FAST-LIO2 帧 | Nav2 帧 | 说明 |
|---|---|---|
| `camera_init` | `odom` | FAST-LIO2 起点帧，等价于里程计参考帧 |
| `body` | `base_link` | IMU/机体帧，Go2 偏差 < 5 cm，可视为等价 |
| (无，由地图匹配产生) | `map` | 全局地图帧，由 ICP 定位后产生 |

---

## 目录结构

```
Go2_localization/
├── README.md
├── PCD/
│   └── MID360.pcd                        # 全局地图（FAST-LIO2 建图结果）
├── odom_tf_bridge/                        # FAST-LIO2 里程计 → Nav2 适配桥
│   ├── config/odom_bridge_params.yaml     # 节点参数
│   ├── launch/odom_bridge.launch.py
│   └── README.md
└── fast_lio_localization_ros2/            # ICP 点云地图定位与全局重定位
    ├── launch/
    │   └── localize_go2.launch.py         # Go2 专用
    ├── scripts/
    │   ├── pcd_publisher.py              # 加载 PCD 文件并发布为 /map3d
    │   ├── global_localization_ros2.py   # ICP 重定位，发布 /map_to_odom
    │   └── transform_fusion_ros2.py      # 融合里程计与重定位，广播 map→odom TF
    └── PCD/
        └── MID360.pcd -> ../PCD/MID360.pcd  # 软链接
```

---

## 子模块说明

### odom_tf_bridge

将 FAST-LIO2 输出的 `/Odometry`（`camera_init → body`，BEST_EFFORT）转换为 Nav2 标准格式，广播 `odom → base_link` TF，发布 `/odom`（RELIABLE）。

协方差处理：FAST-LIO2 不填充协方差字段（全零），odom_tf_bridge 为 Nav2 补充默认值（位置 0.01 m²，姿态 0.005 rad²）。

### fast_lio_localization_ros2

三个节点协同工作，均通过 `localize_go2.launch.py` 启动：

#### pcd_publisher
- 加载 `PCD/MID360.pcd` 文件
- 发布 `/map3d`（frame_id = `map`，TRANSIENT_LOCAL，1 Hz）
- TRANSIENT_LOCAL 确保后启动的订阅者也能收到地图

#### global_localization
- 订阅 `/cloud_registered`（**world 坐标系**点云，frame_id=`camera_init`，BEST_EFFORT）
- 订阅 `/Odometry`（remapping 为 `/odom`，BEST_EFFORT）——直接使用 FAST-LIO2 原始里程计
- 订阅 `/map3d`（全局地图，RELIABLE）
- 用 open3d ICP 做多尺度点云匹配（5× 粗配 + 1× 精配）
- 发布 `/map_to_odom`（`map` → `odom` 的 4×4 变换，约 0.5 Hz）

> **为何必须用 `/cloud_registered` 而非 `/cloud_registered_body`**：ICP 的 target 是 map 帧子图，initial 是 T_map_to_odom。若 source（scan）在 world/odom 帧，ICP 结果直接就是 T_map_to_odom；若 source 在 body 帧，ICP 结果是 T_map_to_body，被错误存入 T_map_to_odom，随机器人移动持续漂移。`/cloud_registered` 由 FAST-LIO2 经 `RGBpointBodyToWorld` 变换后以 `frame_id="camera_init"` 发布，是真正的 world 帧。

**ICP 参数（localize_go2.launch.py）：**

| 参数 | 值 | 说明 |
|---|---|---|
| `map_voxel_size` | 0.2 m | 地图体素大小 |
| `scan_voxel_size` | 0.1 m | 扫描体素大小 |
| `fov` | 6.28 (360°) | MID360 全视角 |
| `fov_far` | 15.0 m | 地图裁剪距离（仅保留近处地图点用于 ICP） |
| `freq_localization` | 0.5 Hz | 重定位频率 |
| `localization_th` | 0.997 | ICP 拟合度阈值（99.7% 点对应） |

#### transform_fusion
- 订阅 `/odom`（来自 odom_tf_bridge，RELIABLE）——不 remap，QoS 必须匹配
- 订阅 `/map_to_odom`（ICP 结果，RELIABLE）
- 以 100 Hz 高频广播 `map→odom` TF（时间戳跟随 `/odom`）
- 计算 `T_map→base_link = T_map→odom × T_odom→base_link` 并发布 `/localization`

> **QoS 说明**：transform_fusion 用 RELIABLE QoS 订阅 `/odom`，若 remap 到 FAST-LIO2 的 `/Odometry`（BEST_EFFORT），ROS 2 QoS 不兼容，消息完全收不到。因此 transform_fusion 直接订阅 odom_tf_bridge 的 `/odom`（RELIABLE）。global_localization 则用 BEST_EFFORT 订阅 `/Odometry`，两者来源不同但数据等价（camera_init ≡ odom，body ≡ base_link）。

---

## 依赖安装

```bash
sudo apt install ros-foxy-tf-transformations
pip3 install open3d "numpy<2"
```

---

## 快速开始

### 1. 编译

```bash
cd ~/Go2_Nav_ws
colcon build --packages-select fast_lio_localization_ros2 odom_tf_bridge
source install/setup.bash
```

### 2. 准备地图

将 FAST-LIO2 建图生成的 PCD 文件放到：

```
src/Go2_localization/PCD/MID360.pcd
```

### 3. 启动（推荐：一键脚本）

```bash
bash src/Go2_bringup/go2_nav_start.sh
```

### 4. 手动分步启动

```bash
# 终端 1：FAST-LIO2
ros2 launch fast_lio mapping.launch.py config_path:=... config_file:=mid360.yaml rviz:=false

# 终端 2：odom_tf_bridge
ros2 launch odom_tf_bridge odom_bridge.launch.py

# 终端 3：fast_lio_localization（含 pcd_publisher、global_localization、transform_fusion）
ros2 launch fast_lio_localization_ros2 localize_go2.launch.py \
    map:=~/Go2_Nav_ws/src/Go2_localization/PCD/MID360.pcd rviz:=false
```

### 5. 验证

```bash
# TF 树完整性
ros2 run tf2_ros tf2_echo map base_link

# 重定位输出（应约 0.5 Hz）
ros2 topic hz /map_to_odom

# 融合后完整定位
ros2 topic hz /localization
ros2 topic echo /localization --once
```

---

## Nav2 接口

| 话题 / TF | 消息类型 | 频率 | QoS | 来源 |
|---|---|---|---|---|
| `/odom` | `nav_msgs/Odometry` | 10 Hz | RELIABLE | odom_tf_bridge |
| `odom → base_link` | TF | 10 Hz | — | odom_tf_bridge |
| `map → odom` | TF | 100 Hz | — | transform_fusion |
| `/localization` | `nav_msgs/Odometry` | 100 Hz | RELIABLE | transform_fusion |

---

## 重定位

向 `/initialpose` 发布初始位姿触发全局重定位（与 RViz2 的 "2D Pose Estimate" 按钮兼容）：

```bash
ros2 topic pub /initialpose geometry_msgs/msg/PoseWithCovarianceStamped \
  "{header: {frame_id: map}, pose: {pose: {position: {x: 0.0, y: 0.0}, orientation: {w: 1.0}}}}" --once
```

---

## 常见问题

**Q：`odom → base_link` TF 不存在**
- 确认 odom_tf_bridge 已启动：`ros2 node list | grep odom_tf_bridge`
- 确认 FAST-LIO2 正在发布：`ros2 topic hz /Odometry`

**Q：`map → odom` TF 不更新**
- 确认 `/map_to_odom` 有数据：`ros2 topic hz /map_to_odom`（应 ~0.5 Hz）
- 确认地图文件路径正确，pcd_publisher 启动时会打印加载路径
- 检查 ICP 拟合度：若环境变化大，可适当降低 `localization_th`（如 0.98）

**Q：open3d 导入报 numpy 版本错误**
- 执行 `pip3 install "numpy<2"` 降级 numpy

**Q：ICP 长时间无法收敛**
- 确认初始位姿大致正确（偏差 < 5 m）
- 降低 `localization_th` 阈值
- 确认地图 PCD 与当前环境一致（未发生大规模变化）
