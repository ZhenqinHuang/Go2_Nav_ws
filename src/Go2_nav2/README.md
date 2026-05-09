# Go2_nav2

Go2 机器狗 Nav2 导航模块，提供完整的路径规划、局部控制、代价地图配置及 cmd_vel → Go2 Sport API 桥接。

| 项目 | 内容 |
|---|---|
| 导航框架 | Nav2（ROS 2 Foxy） |
| 全局规划器 | NavFn A* |
| 局部控制器 | DWB（Dynamic Window Based，实测可用） |
| 备选控制器 | Regulated Pure Pursuit（实验性） |
| 行为树 | 自定义 0.2 Hz 慢重规划版本 |
| 硬件适配 | Unitree Go2 足形机器人步态特性专项调优 |

---

## 目录结构

```
Go2_nav2/
├── behavior_trees/
│   ├── navigate_slow_replan.xml          # 自定义 BT：0.2 Hz 重规划（主用）
│   └── navigate_w_replanning_and_recovery.xml  # Nav2 原版（备用）
├── config/
│   ├── map_server.yaml                   # map_server 参数
│   ├── planner_server.yaml               # NavFn A* + 全局代价地图
│   ├── controller_server.yaml            # DWB 局部控制器 + 局部代价地图
│   ├── controller_server_rpp.yaml        # RPP 局部控制器（实验性）
│   ├── behavior_server.yaml              # 恢复行为（Spin/BackUp/Wait）
│   ├── bt_navigator.yaml                 # bt_navigator 参数
│   └── cmd_vel_bridge_params.yaml        # go2_cmd_vel_bridge 参数
├── launch/
│   ├── nav2_bringup.launch.py            # 主 launch：map_server + Nav2 + TTS
│   └── cmd_vel_bridge.launch.py          # cmd_vel → Go2 Sport API 桥接
├── scripts/
│   └── nav_tts_announcer.py              # 导航完成中文 TTS 播报
├── src/
│   └── go2_cmd_vel_bridge.cpp            # cmd_vel 桥接节点主逻辑
├── rviz/
│   └── nav2.rviz                         # RViz2 配置（可选）
├── CMakeLists.txt
└── package.xml
```

---

## 模块说明

### nav2_bringup.launch.py

按以下顺序启动 Nav2 全栈：

1. **map_server** — 加载 `.yaml` 地图文件，发布 `/map`（静态占据栅格地图）
2. **planner_server** — NavFn A* 全局规划器，4 Hz 规划频率
3. **controller_server** — DWB 局部控制器，20 Hz 控制频率
4. **recoveries_server** — 恢复行为（Spin / BackUp / Wait）
5. **bt_navigator** — 行为树决策器，使用自定义 `navigate_slow_replan.xml`
6. **lifecycle_manager_map** — 立即激活 map_server（等待 `/map` 就绪）
7. **lifecycle_manager_navigation** — 延迟 **8 秒**激活规划/控制栈（等待 FastLIO 发布 `map→odom` TF）
8. **nav_tts_announcer** — 订阅导航结果，成功时播报"导航成功，已到达目标位置"

**关键设计说明**：`lifecycle_manager_navigation` 延迟 8 秒启动是为了给 `fast_lio_localization_ros2` 留足时间完成首次 ICP 匹配并发布 `map→odom` TF，避免 costmap 激活超时。实测 FastLIO 定位通常在 3–5 秒内就绪，8 秒是留有余量的平衡点。

### cmd_vel_bridge.launch.py

启动 `go2_cmd_vel_bridge` 节点，将 Nav2 输出的 `/cmd_vel`（`geometry_msgs/Twist`）转换为 Unitree Go2 Sport API 运动指令。

---

## 行为树：navigate_slow_replan.xml

```xml
<!-- 0.2 Hz 重规划：每 5 秒更新一次全局路径 -->
<RateController hz="0.2">
  <ComputePathToPose .../>
</RateController>
```

**设计原因：** Nav2 默认 1 Hz 重规划与 ICP 定位 ~1.5 Hz 更新节律接近，每次 ICP 修正 `map→odom` 后 BT 立即生成新路径，导致 DWB 持续跟着路径方向变化而摆头。降低到 0.2 Hz 后，路径在 5 秒窗口内保持稳定，DWB 不会频繁收到方向变化的新路径，行走更平滑。

**恢复行为序列（最多 6 次重试）：**
1. 尝试规划（失败时清空全局代价地图）
2. 尝试跟随路径（失败时清空局部代价地图）
3. 清空双侧代价地图 → 原地旋转 90° → 等待 5 秒

---

## 参数配置

### DWB 控制器关键参数（controller_server.yaml）

| 参数 | 值 | 说明 |
|---|---|---|
| `controller_frequency` | 20.0 Hz | Orin NX 单核稳定工作点（25 Hz 会触发控制循环超时） |
| `max_vel_x` | 0.60 m/s | 前进最大速度 |
| `max_vel_theta` | 1.4 rad/s | 最大角速度 |
| `min_speed_theta` | 0.15 rad/s | 低于 0.1 rad/s Go2 步态无法转动，设 0.15 保证能转 |
| `vx_samples` × `vtheta_samples` | 20 × 24 = 480 条 | Orin NX 单核 20 Hz 下稳跑的甜区（25×30=750 会超时） |
| `sim_time` | 1.6 s | DWB 轨迹预测时间（0.35 m/s × 1.6s ≈ 0.56 m） |
| `xy_goal_tolerance` | 0.25 m | ±10 cm 步态抖动 + map→odom 平滑过程需要的容差 |
| `yaw_goal_tolerance` | 0.18 rad (~10°) | 平衡精度与步态死区 |
| `trans_stopped_velocity` | 0.25 m/s | Go2 低速 vx 在 0.05–0.15 波动，高阈值让 DWB 果断进入 RotateToGoal |
| `RotateToGoal.slowing_factor` | 1.5 | 从原版 5.0 降低；Go2 步态死区 ~0.1 rad/s，5 倍减速后无法转动 |
| `Oscillation.x_only_threshold` | 0.10 | 避免低速旋转被误判为振荡 |

**机器人 footprint（矩形）：**
```
[[0.35, 0.18], [0.35, -0.18], [-0.35, -0.18], [-0.35, 0.18]]
```
- 纵向 ±0.35 m，横向 ±0.18 m（覆盖步态摆动 ±5 cm 缓冲）
- 0.6 m 宽走廊中央仍剩 0.24 m 自由空间，Go2 可稳定通过

**局部代价地图（local_costmap）：**

| 参数 | 值 | 说明 |
|---|---|---|
| `rolling_window` | True | 以机器人为中心的滚动窗口 |
| `width` × `height` | 5 × 5 m | 前后左右各 2.5 m 覆盖 |
| `resolution` | 0.05 m | 与全局地图一致 |
| `obstacle_max_range` | 2.5 m | 激光扫描标记障碍的最大距离 |
| `inflation_radius` | 0.22 m | 比 footprint 半宽略大，0.8 m 走廊中央保持低代价 |
| `cost_scaling_factor` | 5.0 | 代价快速衰减：墙边 0.05 m 内高代价，之外迅速归零 |

### NavFn 全局规划器关键参数（planner_server.yaml）

| 参数 | 值 | 说明 |
|---|---|---|
| `expected_planner_frequency` | 4.0 Hz | 动态环境下全局路径每 0.25 s 更新一次 |
| `use_astar` | true | A* 比 Dijkstra 更快，减少 NavFn 在大地图上的 CPU 占用 |
| `tolerance` | 0.2 m | 目标点周围 0.2 m 内若有障碍则规划到最近可达点 |
| `allow_unknown` | true | 允许规划穿过未知区域（地图边缘） |

---

## go2_cmd_vel_bridge

将 Nav2 输出的 `/cmd_vel` 转换为 Unitree Go2 Sport API 运动指令。

### 关键功能

| 功能 | 说明 |
|---|---|
| **速度限幅** | `max_vx = 0.60 m/s`，`max_vy = 0.0`（Go2 不支持横向移动），`max_vyaw = 1.4 rad/s` |
| **超时停车** | 超过 0.6 s 未收到 `/cmd_vel` 则发送零速（防止失控） |
| **死区过滤** | `|v| < 0.03 m/s` 视为零速，避免微小抖动驱动机器人 |
| **自动站立** | 收到非零运动指令时自动发送 StandUp，稳定 0.6 s 后开始移动 |
| **角速度平滑** | EMA 滤波（α=0.85），过滤角速度尖峰，保持行走平稳 |
| **定位保护** | `/map_to_odom` 超过 1.5 s 未更新则暂停运动，ICP 大幅修正时暂停 0.8 s |
| **控制频率** | 50 Hz 发布 Sport API 指令，与 Nav2 20 Hz 解耦 |

### cmd_vel_bridge_params.yaml 参数一览

| 参数 | 默认值 | 说明 |
|---|---|---|
| `max_vx` | 0.60 m/s | 前进最大速度 |
| `max_vy` | 0.0 | 横向速度（Go2 不支持，固定为 0） |
| `max_vyaw` | 1.4 rad/s | 最大角速度 |
| `motion_deadband` | 0.03 | 速度死区阈值 |
| `cmd_timeout_sec` | 0.6 s | cmd_vel 超时停车时间 |
| `publish_rate_hz` | 50.0 Hz | Sport API 指令发布频率 |
| `stand_up_on_motion` | true | 收到运动指令时自动站立 |
| `stand_up_settle_sec` | 0.6 s | 站立稳定等待时间 |
| `auto_stand_up` | false | 启动时立即站立 |
| `localization_guard_enabled` | true | 启用定位保护 |
| `localization_timeout_sec` | 1.5 s | 定位超时阈值 |
| `correction_pause_sec` | 0.8 s | ICP 修正后暂停时间 |
| `correction_pause_delta_xy` | 0.50 m | 触发暂停的位置修正幅度阈值 |
| `correction_pause_delta_yaw` | 0.70 rad | 触发暂停的角度修正幅度阈值 |
| `vyaw_smooth_alpha` | 0.85 | 角速度 EMA 平滑系数（1=无平滑） |

---

## nav_tts_announcer.py

订阅 `/navigate_to_pose/_action/status`，在导航成功（GoalStatus = SUCCEEDED）时向 `/tts_text` 发布中文语音文本。

| 参数 | 默认值 | 说明 |
|---|---|---|
| `success_text` | "导航成功，已到达目标位置" | 成功播报文本 |
| `tts_topic` | `/tts_text` | TTS 文本发布话题 |

---

## 启动方式

```bash
# 方式一：通过 run_nav2.sh（推荐，自动 source 环境）
MAP_YAML=~/Go2_Nav_ws/maps/MID360_map.yaml \
bash ~/Go2_Nav_ws/src/Go2_bringup/run_nav2.sh

# 方式二：直接 launch（需事先 source 环境）
source ~/Go2_Nav_ws/install/setup.bash
ros2 launch go2_nav2 nav2_bringup.launch.py \
  map:=~/Go2_Nav_ws/maps/MID360_map.yaml \
  controller:=dwb \
  use_rviz:=false

# 单独启动 cmd_vel 桥接
ros2 launch go2_nav2 cmd_vel_bridge.launch.py
```

---

## 话题接口

### 订阅

| 话题 | 消息类型 | 来源 | 说明 |
|---|---|---|---|
| `/odom` | `nav_msgs/Odometry` | odom_tf_bridge | 里程计（RELIABLE，10 Hz） |
| `/scan` | `sensor_msgs/LaserScan` | go2_pc2scan | 激光扫描（RELIABLE，10 Hz） |
| `map → odom` TF | TF | fast_lio_localization | 地图定位 TF（100 Hz） |
| `/map` | `nav_msgs/OccupancyGrid` | map_server | 静态地图（latched） |
| `/goal_pose` | `geometry_msgs/PoseStamped` | 外部 / Web UI | 导航目标点 |
| `/initialpose` | `geometry_msgs/PoseWithCovarianceStamped` | 外部 | 重定位初始位姿 |

### 发布

| 话题 | 消息类型 | 说明 |
|---|---|---|
| `/cmd_vel` | `geometry_msgs/Twist` | DWB 输出速度指令 |
| `/map` | `nav_msgs/OccupancyGrid` | map_server 发布静态地图 |
| `/tts_text` | `std_msgs/String` | 导航成功 TTS 文本 |
| `/navigate_to_pose/_action/status` | `action_msgs/GoalStatusArray` | 导航 Action 状态 |

---

## 发送导航目标

```bash
# 命令行方式
ros2 action send_goal /navigate_to_pose nav2_msgs/action/NavigateToPose \
  "{pose: {header: {frame_id: map}, pose: {position: {x: 1.0, y: 0.5}, orientation: {w: 1.0}}}}"

# 取消导航
ros2 action cancel /navigate_to_pose $(ros2 action list --ids /navigate_to_pose | head -1)

# 检查 Nav2 Action 就绪
ros2 action list | grep navigate_to_pose

# 监控导航状态
ros2 topic echo /navigate_to_pose/_action/status
```

---

## 常见问题

**Q：Nav2 启动后 costmap 初始化超时**
- 确认 `fast_lio_localization_ros2` 已发布 `map→odom` TF：`ros2 run tf2_ros tf2_echo map odom`
- `lifecycle_manager_navigation` 有 8 秒延迟，等待 FastLIO 定位初始化完成
- 查看 Nav2 日志：`cat /tmp/go2_nav_bringup/nav2.log`

**Q：DWB 控制器报"Control loop missed its desired rate"**
- Orin NX 单核 25 Hz 会触发此警告，已调至 20 Hz 稳定工作
- 检查 CPU 负载：`top -b -n1 | head -20`

**Q：机器人到达目标附近但一直不停（进出 goal tolerance）**
- 已调整 `xy_goal_tolerance = 0.25 m`，如果仍不停，可适当增大此值
- 确认 `map→odom` TF 平滑收敛，抖动幅度在容差范围内

**Q：机器人接近目标时掉不过来（无法完成 RotateToGoal）**
- `RotateToGoal.slowing_factor` 已从 5.0 降为 1.5，保持足够角速度
- 确认 `min_speed_theta ≥ 0.15 rad/s`（低于此值 Go2 步态踩不动）

**Q：导航路径卡住后无法恢复**
- 行为树会自动触发恢复：清空代价地图 → 原地旋转 90° → 等待 5 秒（最多 6 次重试）
- 手动清空代价地图：`ros2 service call /global_costmap/clear_entirely_global_costmap nav2_msgs/srv/ClearEntireCostmap {}`
