# Go2 Nav Workspace

Go2 导航项目的 ROS 2 源码区，在 Unitree Go2 机器狗上使用 Livox MID360 + FAST-LIO2 + hdl-localization 提供 Nav2 所需的完整数据流。

运行环境：Ubuntu 20.04 / ROS 2 Foxy / Unitree Go2 / Livox MID360

---

## 数据流总览

```
MID360 LiDAR + IMU
        │
   FAST-LIO2 (LiDAR-IMU 紧耦合里程计)
        │
        ├─ /Odometry ──────────────> odom_tf_bridge ──> /odom + odom->base_link TF
        │
        └─ /cloud_registered_body ─> go2_pc2scan ──────> /scan
                                   │
                                   └─> hdl-localization ─> map->odom TF
                                       (NDT 地图匹配 + 全局重定位)
```

**TF 树：**
```
map ──(hdl-localization)──> odom ──(odom_tf_bridge)──> base_link
```

---

## 完成情况

已完成：

- MID360 + FAST-LIO2 SLAM 建图流程
- `odom_tf_bridge`：FAST-LIO2 `/Odometry` → Nav2 `/odom` + `odom->base_link` TF
- `go2_pc2scan`：`/cloud_registered_body` 过滤后转换为 `/scan`
- `hdl-localization`：基于 PCD 地图的 NDT 定位，发布 `map->odom` TF，集成全局重定位（BBS/RANSAC）
- `go2_nav_start.sh`：一键启动完整链路（Livox → FAST-LIO2 → hdl-localization → odom_tf_bridge → go2_pc2scan）

待完成：

- Nav2 完整导航配置（costmap、行为树、路径规划参数）
- `/scan` 的 `frame_id` 与 Nav2 costmap 配置对齐验证

---

## 目录说明

### `Go2_bringup`

- `go2_nav_start.sh`：一键启动全链路，按顺序等待每步就绪
- `time_sync_start.sh`：NTP/PTP 时间同步辅助

### `Go2_localization`

- `odom_tf_bridge`：里程计格式转换与 TF 广播
- `hdl-localization`：NDT 点云地图定位（含 `hdl_global_localization`、`ndt_omp`、`fast_gicp`）
- `PCD/MID360.pcd`：默认全局地图文件

详见 [Go2_localization/README.md](Go2_localization/README.md)

### `Go2_perception`

- `go2_pc2scan`（`pointcloud_to_laserscan`）：点云过滤 + 转 LaserScan

### `Go2_time_sync`

MID360 与主机时间同步工具。

### `Go2_web_bridge`

Web 交互桥接，不属于导航主链路。

---

## 启动方式

```bash
# 可选：先同步时间
sudo bash /home/unitree/Go2_Nav_ws/src/Go2_bringup/time_sync_start.sh

# 启动完整导航链路
bash /home/unitree/Go2_Nav_ws/src/Go2_bringup/go2_nav_start.sh
```

自定义工作空间路径：

```bash
LIVOX_WS=/home/unitree/ws_Livox \
FASTLIO_WS=/home/unitree/ws_fastlio2 \
GO2_NAV_WS=/home/unitree/Go2_Nav_ws \
FASTLIO_CONFIG=/home/unitree/ws_fastlio2/src/FAST_LIO_ROS2/config/mid360.yaml \
HDL_GLOBALMAP_PCD=/home/unitree/Go2_Nav_ws/src/Go2_localization/PCD/MID360.pcd \
bash /home/unitree/Go2_Nav_ws/src/Go2_bringup/go2_nav_start.sh
```

---

## Nav2 接口

当前链路向 Nav2 提供：

| 话题/TF | 类型 | 来源 |
|---|---|---|
| `/odom` | `nav_msgs/Odometry` | odom_tf_bridge |
| `odom -> base_link` | TF | odom_tf_bridge |
| `map -> odom` | TF | hdl-localization |
| `/scan` | `sensor_msgs/LaserScan` | go2_pc2scan |

---

## 注意事项

- `go2_nav_start.sh` 会显式 source 三个工作空间（Livox、FAST-LIO2、Go2_Nav），避免环境变量顺序混乱
- MID360 安装外参须与 FAST-LIO2 的 `mid360.yaml` 保持一致，否则点云坐标系偏差会影响定位和扫描切片
- hdl-localization 启动时会等待 `hdl_global_localization` 服务就绪，两者已集成在同一 launch 文件中，无需单独启动
