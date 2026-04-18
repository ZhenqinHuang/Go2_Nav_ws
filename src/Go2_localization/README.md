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
           (去畸变点云, frame_id=body)   (NDT 地图匹配)
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
│   └── map.pcd                    # 建图后放置于此（当前为空）
├── odom_tf_bridge/                # FAST-LIO2 里程计 → NAV2 适配桥
│   ├── config/odom_bridge_params.yaml
│   ├── launch/odom_bridge.launch.py
│   └── README.md
└── hdl-localization-ROS2/         # 点云地图重定位（NDT-OMP）
    └── hdl_localization/
        └── launch/
            ├── hdl_localization_go2.launch.py   # Go2 专用 ← 使用此文件
            └── hdl_localization_turtlebot.launch.py
```

---

## 子模块说明

### odom_tf_bridge

将 FAST-LIO2 输出的 `/Odometry`（`camera_init -> body`）转换为 NAV2 标准格式，广播 `odom -> base_link` TF。

详见 [odom_tf_bridge/README.md](odom_tf_bridge/README.md)

### hdl-localization-ROS2

基于 NDT-OMP 的点云地图定位。订阅 `/cloud_registered_body`（FAST-LIO2 去畸变点云），与预建 PCD 地图匹配，发布 `map -> odom` TF。

Go2 专用 launch 文件：[hdl_localization_go2.launch.py](hdl-localization-ROS2/hdl_localization/launch/hdl_localization_go2.launch.py)

### maps/

存放 PCD 格式的全局地图文件。地图由 FAST-LIO2 建图模式生成后保存至此目录。

---

## 快速开始

### 1. 编译

```bash
cd /home/wangzhenjie/Go2_Nav_ws
colcon build --packages-select odom_tf_bridge hdl_localization ndt_omp fast_gicp hdl_global_localization
source install/setup.bash
```

### 2. 准备地图

将 FAST-LIO2 建图生成的 PCD 文件放到：

```
src/Go2_localization/maps/map.pcd
```

### 3. 启动顺序

```bash
# 终端 1：FAST-LIO2（发布 /cloud_registered_body 和里程计）
ros2 launch fast_lio mapping_mid360.launch.py

# 终端 2：odom_tf_bridge（odom -> base_link TF）
ros2 launch odom_tf_bridge odom_bridge.launch.py

# 终端 3：hdl-localization（map -> odom TF）
ros2 launch hdl_localization hdl_localization_go2.launch.py \
    globalmap_pcd:=/home/wangzhenjie/Go2_Nav_ws/src/Go2_localization/maps/map.pcd
```

### 4. 验证 TF 树

```bash
ros2 run tf2_ros tf2_echo map base_link
ros2 run rqt_tf_tree rqt_tf_tree
```

---

## 参数调整

### 初始位姿（非地图原点启动时）

```bash
ros2 launch hdl_localization hdl_localization_go2.launch.py \
    globalmap_pcd:=.../map.pcd \
    init_pos_x:=1.5 \
    init_pos_y:=2.0 \
    init_ori_w:=0.707 \
    init_ori_z:=0.707
```

### 运行中手动重定位

通过 RViz 的 "2D Pose Estimate" 工具，或命令行：

```bash
ros2 topic pub /initialpose geometry_msgs/msg/PoseWithCovarianceStamped \
    "{header: {frame_id: map}, pose: {pose: {position: {x: 1.0, y: 2.0}, orientation: {w: 1.0}}}}" --once
```

### NDT 参数（hdl_localization_go2.launch.py）

| 参数 | 默认值 | 说明 |
|---|---|---|
| `ndt_resolution` | `0.5` | NDT 体素大小（m），越小精度越高但越慢 |
| `downsample_resolution` | `0.1` | 输入点云降采样分辨率（m） |
| `ndt_neighbor_search_method` | `DIRECT7` | 邻域搜索方式 |
| `cool_time_duration` | `2.0` | 冷启动等待时间（s） |

---

## 关键设计说明

### 为什么用 /cloud_registered_body

FAST-LIO2 的 `/cloud_registered_body` 经过 IMU 去畸变，补偿了扫描过程中的运动，比原始点云更适合地图匹配，定位精度更高。

### body -> base_link 静态 TF

`/cloud_registered_body` 的 `frame_id = "body"`，hdl-localization 需要将点云变换到 `base_link`。由于 `odom_bridge_params.yaml` 中 body 与 base_link 偏移为零，launch 文件发布一个 identity 静态 TF 完成对齐。

### 里程计预测（enable_robot_odometry_prediction）

hdl-localization 利用 `odom -> base_link` TF 做帧间运动预测，作为 NDT 匹配的初始猜测，显著减少迭代次数，提升实时性。

### TF 广播来源

| TF | 广播者 |
|---|---|
| `camera_init -> body` | FAST-LIO2 自身 |
| `odom -> base_link` | odom_tf_bridge |
| `body -> base_link` | hdl_localization_go2.launch.py（静态，identity） |
| `map -> odom` | hdl-localization |

---

## 常见问题

**Q：hdl-localization 报 `point cloud cannot be transformed into target frame`**
- 确认 `body -> base_link` 静态 TF 已发布：`ros2 run tf2_ros tf2_echo body base_link`
- 确认 FAST-LIO2 正在发布 `/cloud_registered_body`：`ros2 topic hz /cloud_registered_body`

**Q：`map -> odom` TF 不更新**
- 确认地图文件路径正确，节点启动时会打印加载信息
- 检查 NDT 匹配是否收敛：`ros2 topic echo /status`（fitness score 应 < 1.0）
- 尝试通过 RViz 手动给定初始位姿

**Q：定位漂移或跳变**
- 增大 `cool_time_duration` 让初始匹配更稳定
- 检查地图质量（点云密度、覆盖范围）
- 调小 `ndt_resolution`（如 0.3）提升精度，但会增加计算量
