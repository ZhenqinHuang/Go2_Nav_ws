# Go2 Bringup

Go2 导航链路的一键启动脚本目录。

| 项目 | 内容 |
|---|---|
| 机器人 | Unitree Go2 |
| 计算平台 | Jetson Orin NX 16GB |
| 操作系统 | Ubuntu 20.04 |
| ROS 版本 | ROS 2 Foxy |
| 激光雷达 | Livox MID360 |

---

## 脚本说明

### `go2_nav_start.sh`

按顺序拉起并检查 Nav2 所需的完整前置数据链路：

| 步骤 | 模块 | 等待条件 |
|---|---|---|
| 1 | Livox MID360 驱动 | `/livox/lidar`、`/livox/imu` 出现 |
| 2 | FAST-LIO2 | `/Odometry`、`/cloud_registered`、`/cloud_registered_body` 出现 |
| 3 | odom_tf_bridge | `/odom` 出现 |
| 4 | fast_lio_localization_ros2 | `/map_to_odom` 出现（ICP 初次匹配完成） |
| 5 | go2_pc2scan | `/cloud_filtered`、`/scan` 出现 |

链路就绪后自动打印节点列表、话题列表和各关键话题频率。

**默认启动（开发机路径）：**

```bash
bash /home/wangzhenjie/Go2_Nav_ws/src/Go2_bringup/go2_nav_start.sh
```

**实机路径（Go2 机载 /home/unitree）：**

```bash
LIVOX_WS=/home/unitree/ws_Livox \
FASTLIO_WS=/home/unitree/ws_fastlio2 \
GO2_NAV_WS=/home/unitree/Go2_Nav_ws \
FASTLIO_CONFIG=/home/unitree/ws_fastlio2/src/FAST_LIO_ROS2/config/mid360.yaml \
FASTLIO_LOC_PCD=/home/unitree/Go2_Nav_ws/src/Go2_localization/PCD/MID360.pcd \
bash /home/unitree/Go2_Nav_ws/src/Go2_bringup/go2_nav_start.sh
```

**环境变量说明：**

| 变量 | 默认值 | 说明 |
|---|---|---|
| `LIVOX_WS` | `~/ws_Livox` | Livox 驱动工作空间路径 |
| `FASTLIO_WS` | `~/ws_fastlio2` | FAST-LIO2 工作空间路径 |
| `GO2_NAV_WS` | 脚本所在上两级目录 | 本项目工作空间路径 |
| `FASTLIO_CONFIG` | `~/ws_fastlio2/.../mid360.yaml` | FAST-LIO2 配置文件路径 |
| `FASTLIO_LOC_PCD` | `Go2_localization/PCD/MID360.pcd` | 定位用 PCD 地图文件路径 |
| `RVIZ` | `false` | 是否同步启动 RViz2 |
| `WAIT_TIMEOUT` | `30` | 每步等待超时时间（秒） |

日志默认保存到 `/tmp/go2_nav_bringup/`（每个模块独立 log 文件）。

---

### `time_sync_start.sh`

原用于启动 Go2 主机与 MID360 的 PTP 时间同步。

> **当前状态**：MID360 PTP 时间同步不可用，该脚本暂停使用。系统统一采用主机系统时钟，MID360 Livox 驱动直接使用系统时间为点云打时间戳。建议通过 NTP（`sudo ntpdate ntp.aliyun.com`）保持主机时钟准确，避免时间戳漂移导致 TF 查询失败。

---

### `check_nav2_ready.sh`

检查当前数据链路是否满足 Nav2 启动要求，包含 7 项检查：

| 检查项 | 内容 |
|---|---|
| 1. 必要话题 | `/odom`、`/scan`、`/cloud_registered`、`/cloud_registered_body`、`/livox/lidar`、`/livox/imu`、`/Odometry`、`/map_to_odom` |
| 2. 话题频率 | `/scan` ≥ 8 Hz，`/odom` ≥ 8 Hz，`/cloud_registered` ≥ 8 Hz（ICP 输入），`/cloud_registered_body` ≥ 8 Hz（点云滤波输入），`/map_to_odom` ≥ 0.3 Hz |
| 3. TF 完整性 | `odom→base_link`，`map→odom`，`map→base_link` |
| 4. 时间戳新鲜度 | `/odom`、`/cloud_registered`、`/cloud_registered_body`、`/scan` 时间戳 age ≤ 1 s |
| 5. `/scan` 质量 | `frame_id = base_link`，角度覆盖正常 |
| 6. `/odom` 质量 | `frame_id = odom`，`child_frame_id = base_link`，协方差非全零 |
| 7. 关键节点 | 所有必要节点均存活 |

```bash
bash /home/wangzhenjie/Go2_Nav_ws/src/Go2_bringup/check_nav2_ready.sh
```

全部通过后退出码为 0，有失败项则退出码为 1。

---

## 推荐启动顺序

```bash
# 终端 1：导航前置链路
bash /home/wangzhenjie/Go2_Nav_ws/src/Go2_bringup/go2_nav_start.sh

# 终端 2：链路验证
bash /home/wangzhenjie/Go2_Nav_ws/src/Go2_bringup/check_nav2_ready.sh
```

---

## 常见问题

**Q：某步等待超时（如 `/map_to_odom` 不出现）**
- 查看对应日志：`cat /tmp/go2_nav_bringup/fast_lio_localization.log`
- 确认 PCD 地图文件存在：`ls ~/Go2_Nav_ws/src/Go2_localization/PCD/MID360.pcd`
- 确认 open3d 已安装：`python3 -c "import open3d"`
- ICP 初次匹配需要几秒到十几秒，耐心等待

**Q：`/odom` 话题存在但 TF 不可达**
- 确认 odom_tf_bridge 正在运行：`ros2 node list | grep odom_tf_bridge`
- 检查 FAST-LIO2 是否正常：`ros2 topic hz /Odometry`

**Q：脚本报找不到 ROS 2 工作空间**
- 通过环境变量指定正确路径（见环境变量表格）
- 默认 ROS 版本为 Foxy，若有变更可设置 `ROS_DISTRO_NAME=<distro>`
