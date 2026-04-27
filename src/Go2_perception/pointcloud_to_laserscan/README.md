# go2_pc2scan — 点云转激光扫描

将 **FAST-LIO2** 输出的三维点云转换为二维 `/scan`，供 **Nav2** 导航使用。

| 项目 | 内容 |
|---|---|
| 应用场景 | Go2 机器狗在约 **70 平米**室内店铺自主导航 |
| 激光雷达 | Livox **MID360**，倾斜安装 13° |
| 运行平台 | **Jetson Orin NX 16GB** |
| ROS 版本 | **ROS 2 Foxy** |

---

## 目录结构

```
go2_pc2scan/
├── CMakeLists.txt
├── package.xml
├── README.md
├── config/
│   ├── cloud_filter_params.yaml       # 高度/距离过滤参数
│   └── pc2scan_params.yaml            # LaserScan 转换参数
├── go2_pc2scan/
│   ├── __init__.py
│   └── cloud_filter_node.py           # 三维点云裁剪节点
└── launch/
    └── pc2scan.launch.py              # 启动两个节点
```

---

## 系统架构

```
FAST-LIO2
  /cloud_registered_body (PointCloud2, body 坐标系, BEST_EFFORT, 10 Hz)
          │
  cloud_filter_node
  · 高度切片 z ∈ [-0.30, +0.40] m（body 坐标系，z 轴向上）
  · 水平距离过滤 [0.25, 12.0] m
  · 体素降采样 0.05 m
  · 输出 frame_id 改为 base_link
          │ /cloud_filtered (PointCloud2, base_link, RELIABLE, 10 Hz)
          │
  pointcloud_to_laserscan（官方 ROS2 包）
  · 360° 投影到 2D 平面
  · 角分辨率 1°（0.01745 rad）
  · 频率 10 Hz
          │ /scan (LaserScan, base_link, 360°, 0.25~12 m)
          │
         Nav2
  (costmap / 路径规划)
```

---

## 高度切片策略

MID360 的外参已在 FAST-LIO2 中通过标定处理，`/cloud_registered_body` 在 body（IMU）坐标系下 z 轴竖直向上。Go2 站立时 body 原点离地约 **0.35 m**。

```
    相对地面高度       相对 body 原点（z 轴）
    ─────────────      ────────────────────────
    2.50 m 天花板
                       z = +2.15 m
    0.75 m ────────── z_max = +0.40 m ← 切片上限
                           │
                       导航切片层
                       (桌腿/货架/展柜/人腿)
                           │
    0.05 m ────────── z_min = -0.30 m ← 切片下限（过滤地面反射）
    0.00 m 地面
                       z = -0.35 m
```

### 店铺场景障碍物覆盖

| 障碍物 | 离地高度 | 是否检测 |
|---|---|---|
| 桌腿 / 椅腿 | 0.05 ~ 0.70 m | ✅ |
| 货架立柱 | 0.05 ~ 0.70 m | ✅ |
| 玻璃展柜 | 0.05 ~ 0.70 m | ✅ |
| 人腿（动态障碍） | 0.10 ~ 0.70 m | ✅ |
| 地面反射噪点 | ~0 m | ❌（已过滤） |
| 桌面 / 货架板面 | > 0.75 m | ❌（切片外） |
| 天花板 | > 1.50 m | ❌（切片外） |

---

## 安装依赖

```bash
sudo apt install ros-foxy-pointcloud-to-laserscan
```

---

## 编译

```bash
cd ~/Go2_Nav_ws
colcon build --packages-select go2_pc2scan
source install/setup.bash
```

---

## 启动

```bash
# 默认参数启动
ros2 launch go2_pc2scan pc2scan.launch.py

# 自定义参数
ros2 launch go2_pc2scan pc2scan.launch.py z_max:=0.60       # 提高切片上限
ros2 launch go2_pc2scan pc2scan.launch.py range_max:=8.0    # 缩小检测范围
ros2 launch go2_pc2scan pc2scan.launch.py downsample_voxel:=0.0  # 禁用降采样
```

### 验证输出

```bash
# 中间点云话题（应约 10 Hz）
ros2 topic hz /cloud_filtered

# 最终激光扫描
ros2 topic echo /scan --no-arr | head -20
ros2 topic hz /scan
```

---

## 参数说明

### `config/cloud_filter_params.yaml`

| 参数 | 默认值 | 说明 |
|---|---|---|
| `cloud_in_topic` | `/cloud_registered_body` | FAST-LIO2 body 坐标系点云输出 |
| `cloud_out_topic` | `/cloud_filtered` | 过滤后输出话题 |
| `output_frame` | `base_link` | 输出点云坐标系（body ≡ base_link） |
| `z_min` | `-0.30` m | 切片下限（body 坐标系 z 轴） |
| `z_max` | `+0.40` m | 切片上限 |
| `range_min` | `0.25` m | 最近水平距离，过滤机体自身反射 |
| `range_max` | `12.0` m | 最远水平距离 |
| `downsample_voxel` | `0.05` m | 体素降采样大小（0 = 禁用） |

### `config/pc2scan_params.yaml`

| 参数 | 默认值 | 说明 |
|---|---|---|
| `target_frame` | `base_link` | 输出 LaserScan 坐标系 |
| `angle_min` | `-π` | 扫描起始角度 |
| `angle_max` | `+π` | 扫描结束角度（MID360 360° 全覆盖） |
| `angle_increment` | `0.01745` rad | 角分辨率（约 1°） |
| `scan_time` | `0.1` s | 单次扫描时间（匹配 10 Hz） |
| `range_min` | `0.25` m | 最小有效距离 |
| `range_max` | `12.0` m | 最大有效距离 |
| `use_inf` | `true` | 超出 range_max 用 inf 填充 |

### Launch 文件可用参数

| 参数 | 默认值 |
|---|---|
| `z_min` | `-0.30` |
| `z_max` | `0.40` |
| `range_min` | `0.25` |
| `range_max` | `12.0` |
| `output_frame` | `base_link` |

---

## Nav2 集成

在 `nav2_params.yaml` 中配置 costmap 使用 `/scan`：

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

**Q：`/scan` 没有数据输出**
1. 确认 FAST-LIO2 正常：`ros2 topic hz /cloud_registered_body`
2. 检查过滤节点：`ros2 topic hz /cloud_filtered`
3. 确认已安装 `ros-foxy-pointcloud-to-laserscan`

**Q：`/scan` 数据跳变或不稳定**
- 增大 `z_min`（如 `-0.20`），过滤更多地面噪点
- 适当减小 `range_max`

**Q：部分障碍物漏检**
- 增大 `z_max`（如 `0.60`）
- 减小 `range_min`（如 `0.15`）以缩短盲区

**Q：Orin NX CPU 占用偏高**
- 增大 `downsample_voxel`（如 `0.10`）
- 在 FAST-LIO2 的 `mid360.yaml` 中增大 `point_filter_num`（如 `5`）
