# Go2 Bringup

Go2 导航链路的启动脚本目录，支持从传感器定位链路到完整自主导航（含 Web UI）的各级启动方式。

| 项目 | 内容 |
|---|---|
| 机器人 | Unitree Go2 |
| 计算平台 | Jetson Orin NX 16GB |
| 操作系统 | Ubuntu 20.04 |
| ROS 版本 | ROS 2 Foxy |
| 激光雷达 | Livox MID360 |

---

## 脚本总览

| 脚本 | 用途 | 推荐场景 |
|---|---|---|
| `go2_autostart.sh` | **全链路入口**：定位 + Nav2 + Web UI | 日常使用 |
| `go2_nav_start.sh` | 传感器定位链路（不含 Nav2） | 调试定位/感知 |
| `run_nav2.sh` | Nav2 决策层 + cmd_vel 桥接 | 单独启动 Nav2 |
| `run_robot_web.sh` | 局域网 Web 控制台（rosbridge + Vite） | 单独启动 Web UI |
| `run_web_bridge.sh` | 云端 WebSocket 桥接 | 远程监控/控制 |
| `check_nav2_ready.sh` | 数据链路健康检查 | 启动后验证 |
| `build_map.sh` | 建图辅助（启动 Livox + FAST-LIO2） | 首次建图 |
| `go2-autostart.service` | systemd 开机自启服务 | 生产部署 |

---

## go2_autostart.sh — 全链路入口（推荐）

按顺序启动全部服务：

```
阶段 1: go2_nav_start.sh  — 传感器定位链路（后台）
         └─ 等待 /scan + /map_to_odom 就绪
阶段 2: run_nav2.sh       — Nav2 决策层（后台）
         └─ 等待 /navigate_to_pose Action 就绪
阶段 3: run_web_bridge.sh — 云端 WebSocket（默认跳过，USE_WEB_BRIDGE=true 启用）
阶段 4: run_robot_web.sh  — 局域网 Web 控制台（默认开启）
         └─ TTS 播报"导航系统已经启动"
```

**最简启动：**

```bash
bash ~/Go2_Nav_ws/src/Go2_bringup/go2_autostart.sh
```

**指定地图：**

```bash
MAP_YAML=/home/nvidia/Go2_Nav_ws/maps/MID360_map.yaml \
bash /home/nvidia/Go2_Nav_ws/src/Go2_bringup/go2_autostart.sh
```

**全参数示例（实机路径）：**

```bash
MAP_YAML=/home/nvidia/Go2_Nav_ws/maps/MID360_map.yaml \
FASTLIO_LOC_PCD=/home/nvidia/Go2_Nav_ws/src/Go2_localization/PCD/MID360_localization_filtered.pcd \
USE_WEB_BRIDGE=true \
SERVER_URL="ws://your-server:30100/ws/source?token=xxx&source_id=dog_001" \
bash /home/nvidia/Go2_Nav_ws/src/Go2_bringup/go2_autostart.sh
```

**环境变量：**

| 变量 | 默认值 | 说明 |
|---|---|---|
| `MAP_YAML` | `~/Go2_Nav_ws/maps/MID360_map.yaml` | Nav2 地图文件路径（必填） |
| `FASTLIO_LOC_PCD` | `Go2_localization/PCD/MID360_localization_filtered.pcd` | 定位用 PCD 地图 |
| `USE_WEB_BRIDGE` | `false` | 是否启动云端 WebSocket 桥接 |
| `USE_ROBOT_WEB` | `true` | 是否启动局域网 Web 控制台 |
| `SERVER_URL` | 默认服务器 URL | 云端 WebSocket 地址 |
| `USE_RVIZ` | `false` | 是否启动 RViz2 |
| `WAIT_TIMEOUT` | `60` | 话题等待超时秒数 |
| `NAV2_SKIP_BUILD` | `1` | 设为 1 跳过 colcon build |

日志保存到 `/tmp/go2_nav_bringup/`（各模块独立日志文件）。

---

## go2_nav_start.sh — 传感器定位链路

按顺序拉起并检查 Nav2 所需的完整前置数据链路：

| 步骤 | 模块 | 等待条件 |
|---|---|---|
| 1 | Livox MID360 驱动 | `/livox/lidar`、`/livox/imu` 出现 |
| 2 | FAST-LIO2 | `/Odometry`、`/cloud_registered`、`/cloud_registered_body` 出现 |
| 3 | odom_tf_bridge | `/odom` 出现 |
| 4 | fast_lio_localization_ros2 | `/map_to_odom` 出现（ICP 初次匹配完成） |
| 5 | go2_pc2scan | `/cloud_filtered`、`/scan` 出现 |

链路就绪后自动打印节点列表、话题列表和各关键话题频率。

```bash
bash ~/Go2_Nav_ws/src/Go2_bringup/go2_nav_start.sh
```

**环境变量：**

| 变量 | 默认值 | 说明 |
|---|---|---|
| `LIVOX_WS` | `~/ws_Livox` | Livox 驱动工作空间路径 |
| `FASTLIO_WS` | `~/ws_fastlio2` | FAST-LIO2 工作空间路径 |
| `GO2_NAV_WS` | 脚本所在上两级目录 | 本项目工作空间路径 |
| `FASTLIO_CONFIG` | `~/ws_fastlio2/.../mid360.yaml` | FAST-LIO2 配置文件路径 |
| `FASTLIO_LOC_PCD` | `Go2_localization/PCD/MID360_localization_filtered.pcd` | 定位用 PCD 地图文件 |
| `RVIZ` | `false` | 是否同步启动 RViz2 |
| `WAIT_TIMEOUT` | `30` | 每步等待超时时间（秒） |

---

## run_nav2.sh — Nav2 决策层

启动 Nav2（map_server + planner + controller + bt_navigator）和 cmd_vel 桥接。

```bash
MAP_YAML=~/Go2_Nav_ws/maps/MID360_map.yaml \
bash ~/Go2_Nav_ws/src/Go2_bringup/run_nav2.sh
```

**环境变量：**

| 变量 | 默认值 | 说明 |
|---|---|---|
| `MAP_YAML` | 无（必填） | 地图 yaml 文件路径 |
| `USE_RVIZ` | `false` | 是否启动 RViz2 |
| `CONTROLLER` | `dwb` | 局部控制器：`dwb`（实测可用）或 `rpp`（实验性） |
| `NAV2_SKIP_BUILD` | `0` | 设为 1 跳过 colcon build |

---

## run_robot_web.sh — 局域网 Web 控制台

启动 rosbridge_websocket（端口 9090）和 Vite dev server（端口 5173），实现浏览器直连机器人 ROS2 话题。

```bash
bash ~/Go2_Nav_ws/src/Go2_bringup/run_robot_web.sh
```

启动后通过局域网 IP 访问：`http://<机器狗IP>:5173`

**环境变量：**

| 变量 | 默认值 | 说明 |
|---|---|---|
| `ROBOT_WEB_DIR` | `~/unitree_ros2/qiaojie/robot_ros2_web` | Web 前端目录 |
| `ROSBRIDGE_PORT` | `9090` | rosbridge WebSocket 端口 |
| `WEB_DEV_PORT` | `5173` | Vite 前端端口 |
| `NODE_BIN_DIR` | `~/.local/node/v20.19.1/bin` | Node.js 可执行文件目录 |

---

## run_web_bridge.sh — 云端 WebSocket 桥接

将机器人位姿和导航状态上报到云端服务器，并接收服务器下发的导航目标点。

```bash
bash ~/Go2_Nav_ws/src/Go2_bringup/run_web_bridge.sh
```

**上行**（Robot → Server）：`/odom`（2 Hz）、`/localization`（1 Hz）、导航状态（变化时立即上报）

**下行**（Server → Robot）：`/goal_pose`（导航目标）、`/initialpose`（重定位）、`/tts_text`（语音）

**环境变量：**

| 变量 | 默认值 | 说明 |
|---|---|---|
| `SERVER_URL` | `ws://121.40.212.85:30100/...` | 云端 WebSocket 服务器地址 |
| `ODOM_HZ` | `2.0` | 位姿上报频率（Hz） |
| `NAV_STATUS_HZ` | `1.0` | 导航状态轮询频率（Hz，状态变化时立即上报） |
| `RECONNECT_DELAY` | `5.0` | 断线重连间隔（秒） |
| `TTS_ALSA_DEVICE` | `plughw:Device,0` | ALSA 音频设备 |
| `TTS_VOICE` | `zh-CN-XiaoxiaoNeural` | edge-tts 语音模型 |

---

## check_nav2_ready.sh

检查当前数据链路是否满足 Nav2 启动要求，包含 7 项检查：

| 检查项 | 内容 |
|---|---|
| 1. 必要话题 | `/odom`、`/scan`、`/cloud_registered`、`/cloud_registered_body`、`/livox/lidar`、`/livox/imu`、`/Odometry`、`/map_to_odom` |
| 2. 话题频率 | `/scan` ≥ 8 Hz，`/odom` ≥ 8 Hz，`/cloud_registered` ≥ 8 Hz，`/cloud_registered_body` ≥ 8 Hz，`/map_to_odom` ≥ 1.0 Hz |
| 3. TF 完整性 | `odom→base_link`，`map→odom`，`map→base_link` |
| 4. 时间戳新鲜度 | `/odom`、`/cloud_registered`、`/cloud_registered_body`、`/scan` 时间戳 age ≤ 1 s |
| 5. `/scan` 质量 | `frame_id = base_link`，角度覆盖正常 |
| 6. `/odom` 质量 | `frame_id = odom`，`child_frame_id = base_link`，协方差非全零 |
| 7. 关键节点 | 所有必要节点均存活 |

```bash
bash ~/Go2_Nav_ws/src/Go2_bringup/check_nav2_ready.sh
```

全部通过后退出码为 0，有失败项则退出码为 1。

---

## go2-autostart.service — 开机自启

```bash
# 安装 systemd 服务
sudo cp ~/Go2_Nav_ws/src/Go2_bringup/go2-autostart.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable go2-autostart.service
sudo systemctl start go2-autostart.service

# 查看状态
sudo systemctl status go2-autostart.service

# 查看日志
journalctl -u go2-autostart.service -f
```

---

## 推荐启动顺序

```bash
# 方式一：全链路一键启动（日常使用）
MAP_YAML=~/Go2_Nav_ws/maps/MID360_map.yaml \
bash ~/Go2_Nav_ws/src/Go2_bringup/go2_autostart.sh

# 方式二：分步调试
# 终端 1：定位链路
bash ~/Go2_Nav_ws/src/Go2_bringup/go2_nav_start.sh

# 终端 2：验证定位链路
bash ~/Go2_Nav_ws/src/Go2_bringup/check_nav2_ready.sh

# 终端 3：Nav2
MAP_YAML=~/Go2_Nav_ws/maps/MID360_map.yaml \
bash ~/Go2_Nav_ws/src/Go2_bringup/run_nav2.sh
```

---

## 日志文件位置

| 日志文件 | 对应服务 |
|---|---|
| `/tmp/go2_nav_bringup/livox.log` | Livox MID360 驱动 |
| `/tmp/go2_nav_bringup/fast_lio.log` | FAST-LIO2 |
| `/tmp/go2_nav_bringup/odom_tf_bridge.log` | odom_tf_bridge |
| `/tmp/go2_nav_bringup/fast_lio_localization.log` | fast_lio_localization_ros2 |
| `/tmp/go2_nav_bringup/go2_pc2scan.log` | go2_pc2scan |
| `/tmp/go2_nav_bringup/rosbridge.log` | rosbridge_websocket |
| `/tmp/go2_nav_bringup/robot_web.log` | Vite dev server |
| `/tmp/go2_nav_bringup/web_bridge.log` | 云端 WebSocket 桥接 |
| `/tmp/go2_cmd_vel_bridge.log` | cmd_vel 桥接 |

---

## 常见问题

**Q：某步等待超时（如 `/map_to_odom` 不出现）**
- 查看对应日志：`cat /tmp/go2_nav_bringup/fast_lio_localization.log`
- 确认定位 PCD 地图文件存在：`ls ~/Go2_Nav_ws/src/Go2_localization/PCD/MID360_localization_filtered.pcd`
- 确认 open3d 已安装：`python3 -c "import open3d"`
- ICP 初次匹配需要几秒到十几秒，耐心等待

**Q：`/odom` 话题存在但 TF 不可达**
- 确认 odom_tf_bridge 正在运行：`ros2 node list | grep odom_tf_bridge`
- 检查 FAST-LIO2 是否正常：`ros2 topic hz /Odometry`

**Q：脚本报找不到 ROS 2 工作空间**
- 通过环境变量指定正确路径（见环境变量表格）
- 默认 ROS 版本为 Foxy，若有变更可设置 `ROS_DISTRO_NAME=<distro>`

**Q：Web 控制台无法访问**
- 确认 rosbridge_websocket 已启动：`ros2 node list | grep rosbridge`

## 新底盘控制网关

正常 Nav2 启动现在默认使用外载—内载 UDP sender：

```bash
GO2_CONTROL_BACKEND=udp \
MAP_YAML=/path/to/map.yaml \
bash run_nav2.sh
```

人工检查、授权和停止：

```bash
bash go2_gateway_status.sh
bash go2_gateway_arm.sh
bash go2_gateway_disarm.sh
```

`go2_gateway_disarm.sh` 应在关闭导航、停止服务或关机前执行。原外载直连 DDS
bridge 只作为诊断回退：

```bash
GO2_CONTROL_BACKEND=direct-dds \
MAP_YAML=/path/to/map.yaml \
bash run_nav2.sh
```

Web 不再让浏览器直接访问 ROS，而是由认证后端提供固定 API。默认访问地址为
`http://192.168.0.101:8080`。完整说明见
[`docs/go2-control-network-and-console.md`](../../docs/go2-control-network-and-console.md)。
- 检查防火墙是否放行 5173 和 9090 端口
- 查看日志：`cat /tmp/go2_nav_bringup/rosbridge.log`

**Q：Nav2 规划失败，机器人不动**
- 确认 `/map_to_odom` TF 持续更新：`ros2 topic hz /map_to_odom`
- 检查 2D 地图质量：通过 RViz2 查看 `/map` 话题
- 确认目标点位于地图空白区域（非黑色障碍）
