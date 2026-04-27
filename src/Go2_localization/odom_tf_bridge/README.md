# odom_tf_bridge — FAST-LIO2 里程计 → Nav2 适配桥

将 **FAST-LIO2** 输出的里程计（`/Odometry`，camera_init→body）转换为 **Nav2** 标准格式（`/odom`，odom→base_link），并广播 `odom → base_link` TF 变换。

| 项目 | 内容 |
|---|---|
| 机器人 | **Go2** 机器狗 |
| 上游 | FAST-LIO2 LiDAR-IMU 里程计 |
| 下游 | Nav2（costmap / 路径规划） |
| 平台 | Jetson Orin NX **16GB** |
| ROS | ROS 2 Foxy |

---

## 坐标系映射关系

```
FAST-LIO2 坐标系              Nav2 标准坐标系
─────────────────────         ─────────────────────────────
camera_init (起点/全局帧)  →  odom      (里程计参考帧)
body        (IMU/机体帧)   →  base_link (机器人基座帧)
```

两者坐标含义完全等价，本节点只做重命名和协方差填充，不做坐标变换（除非配置了 body→base_link 偏移）。

**Nav2 要求的 TF 树：**
```
map (由 fast_lio_localization 的 transform_fusion 广播)
 └── odom
      └── base_link ← 本节点广播（odom_tf_bridge）
```

---

## 数据流

```
FAST-LIO2
  /Odometry  (nav_msgs/Odometry, BEST_EFFORT, ~10 Hz)
    frame_id:       camera_init
    child_frame_id: body
    covariance:     全零（FAST-LIO2 未填充）
          ↓
    odom_tf_bridge_node
    · 重命名 frame: camera_init→odom, body→base_link
    · 补充协方差默认值（仅当 FAST-LIO2 协方差全零时）
    · body→base_link 偏移修正（可选，默认 0）
          ↓
  /odom  (nav_msgs/Odometry, RELIABLE, ~10 Hz)
    frame_id:       odom
    child_frame_id: base_link
    covariance:     已填充（pos=0.01 m², rot=0.005 rad²）

  TF: odom → base_link  (TransformBroadcaster, ~10 Hz)
```

---

## 目录结构

```
odom_tf_bridge/
├── CMakeLists.txt
├── package.xml
├── README.md
├── config/
│   └── odom_bridge_params.yaml       # 节点参数
├── odom_tf_bridge/
│   ├── __init__.py
│   └── odom_tf_bridge_node.py        # 核心转换节点
└── launch/
    └── odom_bridge.launch.py
```

---

## 编译

```bash
cd ~/Go2_Nav_ws
colcon build --packages-select odom_tf_bridge
source install/setup.bash
```

---

## 启动

```bash
# 默认启动（广播 TF）
ros2 launch odom_tf_bridge odom_bridge.launch.py

# 不广播 TF（由 robot_localization/EKF 接管 TF 广播时使用）
ros2 launch odom_tf_bridge odom_bridge.launch.py publish_tf:=false
```

---

## 参数说明

编辑 `config/odom_bridge_params.yaml`：

| 参数 | 默认值 | 说明 |
|---|---|---|
| `fastlio_odom_topic` | `/Odometry` | FAST-LIO2 输出的里程计话题 |
| `odom_topic` | `/odom` | Nav2 消费的里程计话题 |
| `odom_frame` | `odom` | 输出 `header.frame_id` |
| `base_frame` | `base_link` | 输出 `child_frame_id` |
| `publish_tf` | `true` | 是否广播 `odom→base_link` TF |
| `body_to_base_link_x` | `0.0` | IMU→base_link 平移 x (m) |
| `body_to_base_link_y` | `0.0` | IMU→base_link 平移 y (m) |
| `body_to_base_link_z` | `0.0` | IMU→base_link 平移 z (m) |
| `default_pos_cov` | `0.01` | 位置协方差对角值 (m²) |
| `default_rot_cov` | `0.005` | 姿态协方差对角值 (rad²) |

---

## Go2 特定说明

### body_to_base_link 偏移

Go2 的 IMU 内置于主控板附近，与机器人几何中心（base_link）偏差约 3~5 cm。FAST-LIO2 的 LiDAR-IMU 标定已通过外参估计补偿大部分误差，默认设为 0 即可。

若需精确标定，用尺量取后填入：

```yaml
body_to_base_link_x: 0.03   # IMU 在 base_link 前方 3 cm
body_to_base_link_y: 0.0
body_to_base_link_z: 0.0
```

### QoS 策略

| 方向 | 话题 | QoS | 原因 |
|---|---|---|---|
| 输入 | `/Odometry` | BEST_EFFORT | 匹配 FAST-LIO2 发布者 QoS |
| 输出 | `/odom` | RELIABLE | Nav2 要求可靠传输 |
| 广播 | `odom→base_link` TF | — | TF 使用独立广播机制 |

### 协方差设置建议

| 场景 | `default_pos_cov` | `default_rot_cov` |
|---|---|---|
| 室内平坦地面（店铺） | `0.01`（±10 cm） | `0.005`（±4°） |
| 室外草地/斜坡 | `0.05`（±22 cm） | `0.01`（±6°） |

### 与 Nav2 的接口

在 `nav2_params.yaml` 中：

```yaml
amcl:
  ros__parameters:
    odom_frame_id: odom
    base_frame_id: base_link

local_costmap:
  local_costmap:
    ros__parameters:
      robot_base_frame: base_link

bt_navigator:
  ros__parameters:
    odom_topic: /odom
```

---

## 常见问题

**Q：Nav2 报 `waiting for transform odom → base_link`**
- 确认本节点正在运行：`ros2 node list | grep odom_tf`
- 检查 TF：`ros2 run tf2_ros tf2_echo odom base_link`
- 确认 FAST-LIO2 正常发布：`ros2 topic hz /Odometry`

**Q：里程计漂移严重**
- FAST-LIO2 本身已是紧耦合 LiDAR-IMU 里程计，漂移主要来自退化场景（长走廊、空旷空间）
- 可通过 `fast_lio_localization_ros2` 的 `map→odom` TF 定期纠正累积误差

**Q：TF 树报 `would create cycle`**
- 检查是否有其他节点也在广播 `odom→base_link` TF
- FAST-LIO2 默认广播 `camera_init→body`，与本节点 `odom→base_link` 不冲突
- 若冲突，将本节点 `publish_tf` 设为 `false`

**Q：`/odom` 频率低于预期**
- FAST-LIO2 里程计约 10 Hz（受 LiDAR 帧率限制），本节点原样透传
- Nav2 默认可接受 10~50 Hz 里程计
