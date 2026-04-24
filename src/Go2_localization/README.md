# Go2_localization

Go2 机器狗定位模块，基于 **FAST-LIO2 + hdl-localization** 实现 LiDAR-IMU 里程计与点云地图重定位。

---

## 架构概览

```
MID360 LiDAR + IMU
        │
   FAST-LIO2 (LiDAR-IMU 紧耦合里程计)
        │
        ├─ /Odometry ──────────────> odom_tf_bridge ──> odom -> base_link TF
        │
        └─ /cloud_registered_body ─> hdl-localization ──> map -> odom TF
           (去畸变点云, frame_id=body)   (NDT 地图匹配 + 全局重定位)
```

**TF 树：**
```
map ──(hdl-localization)──> odom ──(odom_tf_bridge)──> base_link
```

- `odom -> base_link`：FAST-LIO2 + odom_tf_bridge 维护，高频连续
- `map -> odom`：hdl-localization 维护，基于 PCD 地图匹配，修正累积漂移

---

## 目录结构

```
Go2_localization/
├── README.md
├── maps/                          # 地图文件目录（PCD 格式）
├── PCD/
│   └── MID360.pcd                 # 默认全局地图（MID360 建图结果）
├── odom_tf_bridge/                # FAST-LIO2 里程计 → NAV2 适配桥
│   ├── config/odom_bridge_params.yaml
│   ├── launch/odom_bridge.launch.py
│   └── README.md
└── hdl-localization/              # 点云地图重定位（NDT-OMP + 全局定位）
    ├── hdl_localization/
    │   ├── launch/hdl_localization_go2.launch.py   # Go2 专用 ← 使用此文件
    │   └── config/hdl_go2_params.yaml
    ├── hdl_global_localization/   # 全局重定位子包（BBS/RANSAC）
    ├── fast_gicp/
    └── ndt_omp/
```

---

## 子模块说明

### odom_tf_bridge

将 FAST-LIO2 输出的 `/Odometry`（`camera_init -> body`）转换为 NAV2 标准格式，广播 `odom -> base_link` TF。

详见 [odom_tf_bridge/README.md](odom_tf_bridge/README.md)

### hdl-localization

基于 NDT-OMP 的点云地图定位，包含四个 ROS2 包：

- `hdl_localization`：主定位节点，NDT 匹配 + UKF 位姿估计
- `hdl_global_localization`：全局重定位（BBS/RANSAC/FPFH），用于初始位姿未知时的自动定位
- `ndt_omp`：NDT OpenMP 并行加速库
- `fast_gicp`：快速 GICP/VGICP 库

`hdl_localization_go2.launch.py` 会同时启动 `hdl_global_localization` 和 `hdl_localization` 两个容器，无需单独启动全局定位节点。

---

## 快速开始

### 1. 编译

```bash
cd /home/unitree/Go2_Nav_ws
colcon build --packages-select ndt_omp fast_gicp hdl_global_localization hdl_localization odom_tf_bridge
source install/setup.bash
```

> 首次编译若遇到 `hdl_global_localization` 报空头文件错误，先单独编译它再编译其余包：
> ```bash
> colcon build --packages-select hdl_global_localization
> colcon build --packages-select ndt_omp fast_gicp hdl_localization
> ```

### 2. 准备地图

将 FAST-LIO2 建图生成的 PCD 文件放到：

```
src/Go2_localization/PCD/MID360.pcd
```

### 3. 启动（推荐：一键脚本）

```bash
bash src/Go2_bringup/go2_nav_start.sh
```

脚本会按顺序启动：Livox → FAST-LIO2 → hdl-localization（含全局定位）→ odom_tf_bridge → go2_pc2scan，并等待每步就绪后再继续。

### 4. 手动分步启动

```bash
# 终端 1：FAST-LIO2
ros2 launch fast_lio mapping.launch.py config_path:=... config_file:=mid360.yaml

# 终端 2：hdl-localization + hdl_global_localization（合并在同一 launch）
ros2 launch hdl_localization hdl_localization_go2.launch.py \
    globalmap_pcd:=/home/unitree/Go2_Nav_ws/src/Go2_localization/PCD/MID360.pcd

# 终端 3：odom_tf_bridge
ros2 launch odom_tf_bridge odom_bridge.launch.py
```

### 5. 验证

```bash
# 检查 TF 树是否完整
ros2 run tf2_ros tf2_echo map base_link

# 检查定位输出
ros2 topic hz /hdl_pose

# 检查 NDT 匹配质量（fitness_score 应 < 1.0）
ros2 topic echo /status
```

---

## 参数说明

主要参数在 `hdl-localization/hdl_localization/config/hdl_go2_params.yaml`：

| 参数 | 值 | 说明 |
|---|---|---|
| `reg_method` | `NDT_OMP` | 匹配算法 |
| `ndt_resolution` | `0.5` | NDT 体素大小（m） |
| `downsample_resolution` | `0.2` | 输入点云降采样（m） |
| `enable_robot_odometry_prediction` | `true` | 利用 odom TF 做帧间预测 |
| `use_imu` | `false` | 关闭 IMU（FAST-LIO2 已融合） |
| `use_global_localization` | `true` | 启用全局重定位服务 |
| `cool_time_duration` | `2.0` | 冷启动等待时间（s） |

全局地图降采样分辨率（`GlobalmapServerNodelet`）在 launch 文件中内联设置为 `0.1`。

### 运行中手动重定位

触发全局重定位服务：

```bash
ros2 service call /relocalize std_srvs/srv/Empty
```

或通过 RViz 的 "2D Pose Estimate" 工具直接给定初始位姿。

---

## 关键设计说明

### 为什么用 /cloud_registered_body

FAST-LIO2 的 `/cloud_registered_body` 经过 IMU 去畸变，补偿了扫描过程中的运动，比原始点云更适合地图匹配。

### hdl_global_localization 集成

`use_global_localization: true` 时，`HdlLocalizationNodelet` 启动会等待全局定位服务就绪。`hdl_localization_go2.launch.py` 已将 `hdl_global_localization` 容器集成在内，两者同步启动，无需手动管理依赖顺序。

### 里程计预测

hdl-localization 利用 `odom -> base_link` TF 做帧间运动预测，作为 NDT 匹配的初始猜测，减少迭代次数，提升实时性。

### TF 广播来源

| TF | 广播者 |
|---|---|
| `camera_init -> body` | FAST-LIO2 |
| `odom -> base_link` | odom_tf_bridge |
| `map -> odom` | hdl-localization |

---

## 常见问题

**Q：`point cloud cannot be transformed into target frame`**
- 确认 `odom -> base_link` TF 已发布：`ros2 run tf2_ros tf2_echo odom base_link`
- 确认 FAST-LIO2 正在发布 `/cloud_registered_body`：`ros2 topic hz /cloud_registered_body`

**Q：`map -> odom` TF 不更新 / 节点卡在等待服务**
- 确认 `hdl_global_localization` 节点已启动（使用新版 launch 文件会自动启动）
- 确认地图文件路径正确，节点启动时会打印加载路径

**Q：定位漂移或跳变**
- 增大 `cool_time_duration` 让初始匹配更稳定
- 调小 `ndt_resolution`（如 `0.3`）提升精度，但会增加计算量
- 调用 `/relocalize` 服务触发全局重定位重置位姿
