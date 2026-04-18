# go2_pc2scan — 点云转激光扫描

将 **FAST-LIO2** 输出的三维点云转换为二维 `/scan`，供 **NAV2** 导航使用。

| 项目 | 内容 |
|---|---|
| 应用场景 | Go2 机器狗在约 **70 平米**室内店铺自主导航 |
| 激光雷达 | Livox **MID360**，倾斜安装 **45°** |
| 运行平台 | **Jetson Orin NX 8GB** |
| ROS 版本 | **ROS 2 Humble** |

---

## 目录结构

```
go2_pc2scan/
├── CMakeLists.txt
├── package.xml
├── README.md                          ← 本文件
├── config/
│   ├── cloud_filter_params.yaml       # 高度/距离过滤节点参数
│   └── pc2scan_params.yaml            # LaserScan 转换参数
├── go2_pc2scan/
│   ├── __init__.py
│   └── cloud_filter_node.py           # 核心：三维点云裁剪节点
└── launch/
    └── pc2scan.launch.py              # 一键启动两个节点
```

---

## 系统架构

```
                ┌─────────────────────────────┐
                │         FAST-LIO2           │
                │  (LiDAR-IMU 状态估计 & 建图) │
                └──────────────┬──────────────┘
                               │ /cloud_registered_body
                               │ (PointCloud2, body坐标系,
                               │  已将倾斜45°外参融合)
                               ▼
                ┌─────────────────────────────┐
                │      cloud_filter_node       │
                │  · 高度切片 z∈[-0.25, +0.40] │
                │  · 水平距离过滤 [0.25, 12.0] │
                │  · 体素降采样 0.05 m         │
                └──────────────┬──────────────┘
                               │ /cloud_filtered
                               │ (PointCloud2, 导航切片层)
                               ▼
                ┌─────────────────────────────┐
                │  pointcloud_to_laserscan     │
                │   (官方 ROS2 包)             │
                │  · 360° 投影到 2D 平面       │
                │  · 角分辨率 1°               │
                │  · 频率 10 Hz                │
                └──────────────┬──────────────┘
                               │ /scan
                               │ (LaserScan, 360°, 0.25~12 m)
                               ▼
                ┌─────────────────────────────┐
                │           NAV2              │
                │  (costmap / amcl / planner)  │
                └─────────────────────────────┘
```

---

## 高度切片策略

MID360 的外参旋转矩阵已在 FAST-LIO2 中处理，`/cloud_registered_body` 已对齐 body（IMU）坐标系（z 轴竖直向上）。Go2 站立时，body 原点离地约 **0.35 m**。

```
    相对地面高度       相对body原点(z轴)
    ─────────────      ───────────────────────────
    2.50 m 天花板
                       z = +2.15 m
    0.75 m ────────── z_max = +0.40 m ← 切片上限（过滤天花板/机身背部）
                           │
                       导航切片层
                       (桌腿/货架/展柜/人腿)
                           │
    0.10 m ────────── z_min = -0.25 m ← 切片下限（过滤地面反射点）
    0.00 m 地面
                       z = -0.35 m
```

### 店铺场景覆盖的障碍物类型

| 障碍物 | 离地高度 | 是否检测 |
|---|---|---|
| 桌腿 / 椅腿 | 0.05 ~ 0.70 m | ✅ |
| 货架立柱 | 0.05 ~ 0.70 m | ✅ |
| 玻璃展柜 | 0.05 ~ 0.70 m | ✅ |
| 门框 / 门槛 | 0 ~ 0.70 m | ✅ |
| 人腿（动态障碍） | 0.10 ~ 0.70 m | ✅ |
| 地面反射噪点 | ~0 m | ❌ （已过滤） |
| 桌面 / 货架板面 | >0.75 m | ❌ （切片外） |
| 天花板 | >1.50 m | ❌ （切片外） |

---

## 安装依赖

```bash
# 安装官方 pointcloud_to_laserscan （ROS2 Humble）
sudo apt install ros-humble-pointcloud-to-laserscan
```

---

## 编译

```bash
cd /home/wangzhenjie/Go2_Nav_ws
colcon build --packages-select go2_pc2scan
source install/setup.bash
```

---

## 启动

### 方式一：单独启动本包（需 FAST-LIO2 已运行）

```bash
ros2 launch go2_pc2scan pc2scan.launch.py
```

### 方式二：传入自定义参数

```bash
# 提高切片上限（店铺有高矮柜，障碍物更高）
ros2 launch go2_pc2scan pc2scan.launch.py z_max:=0.60

# 缩小检测范围（小隔间场景）
ros2 launch go2_pc2scan pc2scan.launch.py range_max:=8.0

# 禁用体素降采（CPU 充裕时提升精度）
ros2 launch go2_pc2scan pc2scan.launch.py downsample_voxel:=0.0
```

### 验证输出

```bash
# 检查中间点云话题频率（应约 10 Hz）
ros2 topic hz /cloud_filtered

# 检查最终激光扫描话题
ros2 topic echo /scan --no-arr | head -20

# 频率确认
ros2 topic hz /scan

# RViz2 可视化
rviz2
# → 添加 LaserScan，话题选 /scan，Fixed Frame 选 base_link
```

---

## 参数说明

### `config/cloud_filter_params.yaml` — 点云过滤节点

| 参数 | 默认值 | 说明 |
|---|---|---|
| `cloud_in_topic` | `/cloud_registered_body` | FAST-LIO2 的 body 坐标系点云输出 |
| `cloud_out_topic` | `/cloud_filtered` | 过滤后的输出话题 |
| `z_min` | `-0.25` m | 切片下限，body 坐标系 z 轴，负值=原点以下 |
| `z_max` | `+0.40` m | 切片上限，body 坐标系 z 轴 |
| `range_min` | `0.25` m | 最近水平距离，过滤机体自身反射 |
| `range_max` | `12.0` m | 最远水平距离，≥店铺最大对角线 |
| `downsample_voxel` | `0.05` m | 体素降采样大小（0 = 禁用） |

### `config/pc2scan_params.yaml` — LaserScan 转换节点

| 参数 | 默认值 | 说明 |
|---|---|---|
| `angle_min` | `-π` | 扫描起始角度（-180°） |
| `angle_max` | `+π` | 扫描结束角度（+180°） |
| `angle_increment` | `0.01745` | 角分辨率（1°），NAV2 推荐值 |
| `scan_time` | `0.1` | 单次扫描时间，匹配 MID360 的 10 Hz |
| `range_min` | `0.25` m | 最小有效距离 |
| `range_max` | `12.0` m | 最大有效距离 |
| `target_frame` | `""` | 留空 = 使用点云原始坐标系 |
| `use_inf` | `true` | 超出 range_max 的点用 inf 填充 |

### Launch 文件可用参数

| 参数 | 默认值 | 说明 |
|---|---|---|
| `cloud_in_topic` | `/cloud_registered_body` | 输入点云话题 |
| `z_min` | `-0.25` | 切片下限 |
| `z_max` | `0.40` | 切片上限 |
| `range_min` | `0.25` | 最小距离 |
| `range_max` | `12.0` | 最大距离 |
| `downsample_voxel` | `0.05` | 体素大小 |

---

## NAV2 集成

在 NAV2 的 `nav2_params.yaml` 中，将激光扫描话题指向 `/scan`：

```yaml
local_costmap:
  local_costmap:
    ros__parameters:
      obstacle_layer:
        observation_sources: scan
        scan:
          topic: /scan
          sensor_frame: base_link
          data_type: LaserScan
          max_obstacle_height: 2.0
          clearing: true
          marking: true

global_costmap:
  global_costmap:
    ros__parameters:
      obstacle_layer:
        observation_sources: scan
        scan:
          topic: /scan
          data_type: LaserScan
```

---

## 常见问题

**Q：`/scan` 话题没有任何数据输出**
1. 确认 FAST-LIO2 正常运行：`ros2 topic hz /cloud_registered_body`
2. 检查过滤节点是否有输出：`ros2 topic hz /cloud_filtered`
3. 确认已安装 `ros-humble-pointcloud-to-laserscan`

**Q：`/scan` 数据跳变或不稳定**
- 增大 `z_min`（如 `-0.20`），过滤更多地面噪点
- 减小 `range_max` 至店铺实际最大宽度

**Q：部分障碍物漏检**
- 增大 `z_max`（如 `0.60`），扩大切片上限
- 减小 `range_min`（如 `0.15`）以缩短盲区

**Q：Orin NX CPU 占用偏高**
- 增大 `downsample_voxel`（如 `0.10`）
- 同时在 FAST-LIO2 的 `mid360.yaml` 中增大 `point_filter_num`（如 `5`）

**Q：障碍物检测距离不够**
- 增大 `range_max`，同时确认 `det_range` 在 FAST-LIO2 配置中已相应扩大
