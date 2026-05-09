# Go2 Nav Workspace — src

Go2 导航项目的 ROS 2 源码目录。在 Unitree Go2 机器狗上使用 Livox MID360 + FAST-LIO2 + fast_lio_localization_ros2 提供 Nav2 所需的完整数据流，并通过 Nav2 实现自主路径规划与运动控制，通过 Web 界面实现人机交互。

运行环境：Ubuntu 20.04 / ROS 2 Foxy / Unitree Go2 / Livox MID360 / Jetson Orin NX 16GB

---

## 数据流总览

```
MID360 LiDAR + IMU
        │
   FAST-LIO2 (LiDAR-IMU 紧耦合里程计)
        │
        ├─ /Odometry (BEST_EFFORT) ──> odom_tf_bridge ──> /odom + odom→base_link TF (RELIABLE)
        │
        ├─ /cloud_registered ──> fast_lio_localization_ros2
        │   ├─ pcd_publisher:        发布 /map3d（全局地图点云）
        │   ├─ global_localization:  ICP 地图匹配 → /map_to_odom（目标 1.5 Hz）
        │   └─ transform_fusion:     map→odom TF (100 Hz) + /localization
        │
        └─ /cloud_registered_body ──> go2_pc2scan
            ├─ cloud_filter_node:    高度/距离过滤 → /cloud_filtered
            └─ pointcloud_to_laserscan: 投影为 /scan（360°, 10 Hz）

/odom + /scan + map→odom TF
        │
     Nav2 (go2_nav2)
        ├─ map_server       → /map（静态占据栅格地图）
        ├─ planner_server   → 全局路径规划（NavFn A*）
        ├─ controller_server → DWB 局部控制器 → /cmd_vel
        ├─ recoveries_server → Spin / BackUp / Wait 恢复行为
        └─ bt_navigator     → 行为树（自定义 0.2 Hz 慢重规划）
                │
        go2_cmd_vel_bridge  → Go2 Sport API
        nav_tts_announcer   → /tts_text

/odom + /localization + Nav2 状态
        │
     Go2_web_bridge
        ├─ web_bridge_node   → 云端 WebSocket（上行位姿/状态，下行目标/TTS）
        ├─ tts_node          → edge-tts 中文语音合成 → ALSA 播放
        └─ rosbridge_websocket → 局域网 WebSocket
                │
        Vite Web 控制台 (http://<机器狗IP>:5173)
```

**TF 树：**
```
map ──(transform_fusion, 100 Hz)──> odom ──(odom_tf_bridge, 10 Hz)──> base_link
```

---

## 目录说明

### `Go2_bringup`

启动脚本集合，支持分步或全链路一键启动：

| 脚本 | 说明 |
|---|---|
| `go2_autostart.sh` | **全链路入口**：按顺序启动定位链路 → Nav2 → Web 控制台 → 云端桥接 |
| `go2_nav_start.sh` | 传感器定位链路：Livox → FAST-LIO2 → odom_tf_bridge → 定位 → go2_pc2scan |
| `run_nav2.sh` | Nav2 决策层 + cmd_vel 桥接 |
| `run_robot_web.sh` | 局域网 Web 控制台（rosbridge + Vite） |
| `run_web_bridge.sh` | 云端 WebSocket 桥接（默认关闭） |
| `check_nav2_ready.sh` | 7 项检查：话题/频率/TF/时间戳/质量/节点 |
| `build_map.sh` | 建图辅助脚本 |
| `go2-autostart.service` | systemd 开机自启服务 |

### `Go2_localization`

- `odom_tf_bridge`：FAST-LIO2 里程计格式转换与 TF 广播（camera_init/body → odom/base_link）
- `fast_lio_localization_ros2`：ICP 点云地图定位（产生 `map→odom` TF）
- `PCD/MID360_localization_filtered.pcd`：降采样后用于重定位的地图文件

### `Go2_perception`

- `pointcloud_to_laserscan`（go2_pc2scan）：点云高度/距离过滤 + 转 LaserScan
- `pcd_to_map`：离线 PCD → 2D 占据栅格地图工具

### `Go2_nav2`

- `config/`：完整 Nav2 参数（DWB 控制器、planner、costmap、行为树、cmd_vel 桥接）
- `launch/nav2_bringup.launch.py`：启动 map_server + planner + controller + bt_navigator
- `launch/cmd_vel_bridge.launch.py`：启动 cmd_vel → Go2 Sport API 桥接
- `src/go2_cmd_vel_bridge.cpp`：将 `/cmd_vel` 转换为 Go2 unitree_api 运动指令
- `scripts/nav_tts_announcer.py`：订阅 `/navigate_to_pose` 结果并播报 TTS

### `Go2_web_bridge`

- `Go2_web_bridge/web_bridge_node.py`：云端 WebSocket 桥接节点
- `Go2_web_bridge/tts_node.py`：中文 TTS 节点（edge-tts + ALSA）
- `launch/web_bridge.launch.py`：启动 web_bridge_node + tts_node
- `config/waypoints.yaml`：预设航点配置

### `Go2_time_sync`

PTP 时间同步工具（当前 MID360 PTP 不可用，暂不使用）。统一使用主机系统时钟，建议通过 NTP 保持准确。

### `Go2_Slam`

FAST-LIO2 建图说明，产生供重定位使用的 PCD 地图文件。

---

## 完成情况

✅ 全部完成：

- MID360 + FAST-LIO2 SLAM 建图流程
- `odom_tf_bridge`：FAST-LIO2 `/Odometry` → `/odom` + `odom→base_link` TF 广播
- `fast_lio_localization_ros2`：基于 PCD 地图的 ICP 重定位，广播 `map→odom` TF
- `go2_pc2scan`：`/cloud_registered_body` 高度过滤后转换为 `/scan`
- `pcd_to_map`：PCD → 2D 占据栅格地图（`.pgm` + `.yaml`）
- `go2_nav2`：完整 Nav2 配置 + DWB 局部控制器 + 自定义慢重规划行为树
- `go2_cmd_vel_bridge`：Nav2 `/cmd_vel` → Go2 Sport API 桥接
- `nav_tts_announcer`：导航完成中文 TTS 语音播报
- `Go2_web_bridge`：云端 WebSocket 桥接（位姿上报 + 目标点/初始位姿下发）
- `tts_node`：edge-tts 中文语音合成
- `go2_autostart.sh`：全链路一键启动（定位 + Nav2 + Web UI + 云端桥接）
- `check_nav2_ready.sh`：Nav2 前置链路 7 项完整性检查
- `Go2_time_sync`：PTP 时间同步工具

---

## 依赖安装

```bash
# ROS 2 依赖
sudo apt install ros-foxy-tf-transformations ros-foxy-pointcloud-to-laserscan \
    ros-foxy-nav2-bringup ros-foxy-rosbridge-server

# Python 依赖
pip3 install open3d "numpy<2" websockets edge-tts
```

---

## 启动方式

```bash
# 全链路一键启动（推荐）
MAP_YAML=~/Go2_Nav_ws/maps/MID360_map.yaml \
bash ~/Go2_Nav_ws/src/Go2_bringup/go2_autostart.sh

# 仅定位链路
bash ~/Go2_Nav_ws/src/Go2_bringup/go2_nav_start.sh

# 仅 Nav2
MAP_YAML=~/Go2_Nav_ws/maps/MID360_map.yaml \
bash ~/Go2_Nav_ws/src/Go2_bringup/run_nav2.sh

# 验证链路
bash ~/Go2_Nav_ws/src/Go2_bringup/check_nav2_ready.sh
```

---

## Nav2 接口

当前链路向 Nav2 提供的标准接口：

| 话题 / TF | 消息类型 | 频率 | QoS |
|---|---|---|---|
| `/odom` | `nav_msgs/Odometry` | 10 Hz | RELIABLE |
| `odom → base_link` | TF | 10 Hz | — |
| `map → odom` | TF | 100 Hz | — |
| `/localization` | `nav_msgs/Odometry` | 100 Hz | RELIABLE |
| `/scan` | `sensor_msgs/LaserScan` | 10 Hz | RELIABLE |

---

## 注意事项

- 首次运行前需先用 FAST-LIO2 建图，生成 PCD 文件并用 `pcd_to_map` 转换 2D 地图
- MID360 安装外参须与 FAST-LIO2 的 `mid360.yaml` 保持一致
- 重定位触发：向 `/initialpose` 发布 `geometry_msgs/PoseWithCovarianceStamped`
- `transform_fusion` 和 `global_localization` 通过 remapping 直接订阅 FAST-LIO2 的 `/Odometry`（camera_init→body），而非 odom_tf_bridge 的 `/odom`，两者坐标系等价（camera_init≡odom, body≡base_link）
- Nav2 使用 DWB 局部控制器，Go2 足形机器人参数已针对步态特性专项调优
