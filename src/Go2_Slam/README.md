# Go2_Slam — SLAM 建图

Go2 机器狗使用 FAST-LIO2 进行 LiDAR-IMU 紧耦合 SLAM 建图的说明。建图产生的 PCD 文件供 `fast_lio_localization_ros2` 重定位使用。

---

## 建图流程

FAST-LIO2 以 **在线建图** 模式运行：边运动边构建全局点云地图，结束后将地图保存为 PCD 文件。

```
MID360 LiDAR + IMU
        │
   FAST-LIO2 (LiDAR-IMU 紧耦合 SLAM)
        │
        ├─ /Odometry            实时里程计
        ├─ /cloud_registered_body  body 坐标系下实时点云
        └─ PCD 文件              建图结束后保存（用于后续重定位）
```

---

## 前置条件

### 工作空间

FAST-LIO2 独立于本仓库编译，位于 `~/ws_fastlio2`：

```bash
# FAST-LIO2 工作空间
cd ~/ws_fastlio2
colcon build
source install/setup.bash
```

### LiDAR-IMU 标定

建图前必须完成 MID360 与 IMU 的外参标定，参考 `Go2_perception/LI_Init_calibration`。

标定结果写入 FAST-LIO2 的配置文件：

```
~/ws_fastlio2/src/FAST_LIO_ROS2/config/mid360.yaml
```

---

## 建图步骤

### 1. 启动 Livox MID360 驱动

```bash
source ~/ws_Livox/install/setup.bash
ros2 launch livox_ros_driver2 msg_MID360_launch.py
```

### 2. 启动 FAST-LIO2 建图

```bash
source ~/ws_fastlio2/install/setup.bash
ros2 launch fast_lio mapping.launch.py \
  config_path:=~/ws_fastlio2/src/FAST_LIO_ROS2/config \
  config_file:=mid360.yaml \
  rviz:=true
```

### 3. 控制机器人遍历目标区域

操控 Go2 缓慢、均匀地遍历需要导航的区域：

- 移动速度建议 < 0.3 m/s（保证点云质量）
- 确保所有区域都有足够的 LiDAR 扫描覆盖
- 避免快速旋转（IMU 易饱和）

### 4. 保存地图

FAST-LIO2 在节点关闭时自动将点云地图保存为 PCD 文件（路径在 `mid360.yaml` 的 `pcd_save_en` 和 `map_file_path` 中配置）。

将生成的 PCD 文件复制到本仓库：

```bash
cp /path/to/scans.pcd ~/Go2_Nav_ws/src/Go2_localization/PCD/MID360.pcd
```

### 5. 验证地图

使用 CloudCompare 或 Open3D 可视化确认地图质量：

```python
import open3d as o3d
pcd = o3d.io.read_point_cloud("MID360.pcd")
o3d.visualization.draw_geometries([pcd])
```

---

## 配置文件关键参数（mid360.yaml）

| 参数 | 说明 |
|---|---|
| `lidar_type` | 雷达类型，MID360 对应数值 `1`（Livox 系列） |
| `blind` | 近距盲区（m），建议 0.5 |
| `det_range` | 最大检测距离（m） |
| `point_filter_num` | 点云降采倍率（越大越快但精度降低） |
| `pcd_save_en` | 是否保存 PCD，true 时建图结束自动保存 |
| `map_file_path` | PCD 保存路径 |

---

## 建图质量检查

建图完成后，检查以下指标：

```bash
# 查看地图点数（正常 50 万~500 万点）
python3 -c "
import open3d as o3d
pcd = o3d.io.read_point_cloud('~/Go2_Nav_ws/src/Go2_localization/PCD/MID360.pcd')
print(f'点数: {len(pcd.points)}')
"

# 查看里程计轨迹是否连续（RViz2 中观察）
ros2 topic echo /Odometry --once
```

地图质量要求：
- 点云均匀覆盖导航区域（无大片空洞）
- 墙壁、障碍物边缘清晰（无明显双影/重影）
- 点数建议 > 10 万（保证 ICP 匹配精度）

---

## 注意事项

- 建图与导航使用同一个 FAST-LIO2 配置文件，外参参数必须与实际安装一致
- 地图坐标系为 `camera_init`（FAST-LIO2 起点），导航时 `map` 帧与 `camera_init` 等价
- 若导航环境发生较大变化（移动家具、改建），需重新建图
