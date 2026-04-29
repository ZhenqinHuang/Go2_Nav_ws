# Go2_perception

Go2 机器狗感知模块，负责将 FAST-LIO2 输出的 3D 点云处理为 Nav2 所需的 2D 感知数据，以及将 PCD 地图文件转换为占据栅格地图。

---

## 子包概览

| 子包 | 说明 |
|---|---|
| `pointcloud_to_laserscan` | 实时点云过滤 + LaserScan 转换（go2_pc2scan） |
| `pcd_to_map` | 离线 PCD → 2D 占据栅格地图转换 |

---

## pointcloud_to_laserscan（go2_pc2scan）

### 功能

将 FAST-LIO2 实时输出的 body 坐标系点云（`/cloud_registered_body`）处理为 Nav2 可用的 `/scan`（`sensor_msgs/LaserScan`）。

### 数据流

```
/cloud_registered_body (BEST_EFFORT)
        │
   cloud_filter_node（Python）
   ├─ 高度切片：z ∈ [-0.30, 0.40] m（body 坐标系）
   ├─ 水平距离过滤：[0.25, 12.0] m
   ├─ 体素降采样：0.05 m
   └─ frame_id 重命名：body → base_link
        │
   /cloud_filtered (RELIABLE)
        │
   pointcloud_to_laserscan_node（ROS 官方包）
        │
   /scan (RELIABLE, 10 Hz)
```

### 节点说明

**cloud_filter_node**（`go2_pc2scan/cloud_filter_node.py`）

| 参数 | 默认值 | 说明 |
|---|---|---|
| `cloud_in_topic` | `/cloud_registered_body` | 输入点云话题 |
| `cloud_out_topic` | `/cloud_filtered` | 输出点云话题 |
| `output_frame` | `base_link` | 输出坐标系（空字符串保留原始 frame） |
| `z_min` | `-0.30` | 高度下限（m），贴地约 5 cm |
| `z_max` | `0.40` | 高度上限（m），离地约 75 cm |
| `range_min` | `0.25` | 水平距离下限（m），过滤机体自身反射 |
| `range_max` | `12.0` | 水平距离上限（m） |
| `downsample_voxel` | `0.05` | 体素降采样大小（m），0 = 禁用 |

**pointcloud_to_laserscan_node**（ROS 官方包）

| 参数 | 值 | 说明 |
|---|---|---|
| `target_frame` | `base_link` | 投影坐标系 |
| `angle_min/max` | ±π | MID360 360° 全覆盖 |
| `angle_increment` | 0.01745 rad | ~1° 分辨率 |
| `scan_time` | 0.1 s | 10 Hz |
| `range_min/max` | 0.25 / 12.0 m | 与上游过滤一致 |

### 启动

```bash
# 默认参数启动
ros2 launch go2_pc2scan pc2scan.launch.py

# 自定义高度范围
ros2 launch go2_pc2scan pc2scan.launch.py z_min:=-0.20 z_max:=0.50
```

---

## pcd_to_map

### 功能

离线工具，将 FAST-LIO2 建图保存的 PCD 文件转换为 Nav2 所需的 2D 占据栅格地图（`.pgm` + `.yaml`）。

### 处理流程

```
MID360.pcd
    │
    ├─ 高度过滤（z ∈ [0.3, 2.0] m，世界坐标系绝对高度）
    ├─ 统计去噪（StatisticalOutlierRemoval）
    ├─ 投影到 XY 平面，按分辨率栅格化
    ├─ 障碍物判定（hit_threshold = 4）
    └─ 泛洪填充自由空间（从原点 (0,0) 扩散）
        │
MID360_map.pgm + MID360_map.yaml
```

### 关键参数

| 参数 | 默认值 | 说明 |
|---|---|---|
| `pcd_file` | `maps/MID360.pcd` | 输入 PCD 文件路径 |
| `output_path` | `maps/MID360_map` | 输出路径前缀（不含扩展名） |
| `resolution` | `0.05` m | 栅格分辨率，与 Nav2 代价地图一致 |
| `z_min` | `0.3` m | 高度下限，过滤地面反射 |
| `z_max` | `2.0` m | 高度上限，过滤天花板 |
| `padding` | `1.0` m | 地图边界填充 |
| `sor_mean_k` | `50` | 统计去噪邻居点数 |
| `sor_stddev` | `0.8` | 统计去噪标准差倍数 |
| `hit_threshold` | `4` | 判定为障碍物的最小点数 |

### 启动

```bash
# 使用默认配置（maps/MID360.pcd → maps/MID360_map.{pgm,yaml}）
ros2 launch pcd_to_map pcd_to_map.launch.py

# 指定自定义路径
ros2 launch pcd_to_map pcd_to_map.launch.py \
  pcd_file:=/path/to/your.pcd \
  output_path:=/path/to/output_map
```

生成的 `.pgm` 和 `.yaml` 文件可直接用于 Nav2 的 `map_server`：

```bash
ros2 run nav2_map_server map_server --ros-args \
  -p yaml_filename:=maps/MID360_map.yaml
```

---

## 与其他模块的关系

```
Go2_localization（fast_lio_localization_ros2）
    └─ pcd_publisher → /map3d（可视化用）

Go2_perception
    ├─ pointcloud_to_laserscan → /scan（Nav2 实时障碍物感知）
    └─ pcd_to_map → maps/*.{pgm,yaml}（Nav2 静态地图，离线生成）
```
