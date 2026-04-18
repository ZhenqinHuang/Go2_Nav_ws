# odom_tf_bridge — FAST-LIO2 里程计 → NAV2 适配桥

将 **FAST-LIO2** 输出的里程计（`/Odometry`）转换为 **NAV2** 标准格式（`/odom`），并广播 `odom → base_link` TF 变换。

| 项目 | 内容 |
|---|---|
| 机器人 | **Go2** 机器狗 |
| 上游 | FAST-LIO2 LiDAR-IMU 里程计 |
| 下游 | NAV2（代价地图 / AMCL / 路径规划） |
| 平台 | Jetson Orin NX 8GB |

---

## 坐标系映射关系

```
FAST-LIO2 坐标系              NAV2 标准坐标系
─────────────────────         ─────────────────────────────
camera_init (起点/全局帧)  →  odom      (里程计参考帧)
body        (IMU/机体帧)   →  base_link (机器人基座帧)
```

**NAV2 要求的 TF 树：**
```
map
 └── odom          ← AMCL/EKF 广播（或直接 map=odom 时为 static）
      └── base_link ← 本节点广播（odom_tf_bridge）
           ├── lidar_frame
           ├── imu_frame
           └── ...
```

---

## 数据流

```
FAST-LIO2
  └─ /Odometry  (nav_msgs/Odometry)
       frame_id: camera_init
       child_frame_id: body
       pose: {x,y,z,qx,qy,qz,qw}
       twist: {vx,vy,vz,wx,wy,wz}
       covariance: 全零（FAST-LIO2未填充）
              ↓
        odom_tf_bridge_node
        · 重命名 frame: camera_init→odom, body→base_link
        · 补充协方差默认值
        · body→base_link 偏移修正（可选）
              ↓
  ├─ /odom  (nav_msgs/Odometry)
  │    frame_id: odom
  │    child_frame_id: base_link
  │    covariance: 已填充合理值
  │
  └─ TF: odom → base_link  (TransformBroadcaster)
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
cd /home/wangzhenjie/Go2_Nav_ws
colcon build --packages-select odom_tf_bridge
source install/setup.bash
```

---

## 启动

```bash
# 默认启动（广播 TF）
ros2 launch odom_tf_bridge odom_bridge.launch.py

# 不广播 TF（由 robot_localization/EKF 接管 TF）
ros2 launch odom_tf_bridge odom_bridge.launch.py publish_tf:=false

# 自定义话题
ros2 launch odom_tf_bridge odom_bridge.launch.py \
  fastlio_odom_topic:=/Odometry \
  odom_topic:=/odom
```

---

## 参数说明

编辑 `config/odom_bridge_params.yaml`：

| 参数 | 默认值 | 说明 |
|---|---|---|
| `fastlio_odom_topic` | `/Odometry` | FAST-LIO2 输出的里程计话题 |
| `odom_topic` | `/odom` | NAV2 消费的里程计话题 |
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

Go2 的 IMU 内置于主控板附近，与机器人几何中心（base_link）偏差约 3~5 cm。

若需精确标定，可用尺量取后填入：

```yaml
body_to_base_link_x: 0.03   # IMU 在 base_link 前方 3 cm
body_to_base_link_y: 0.0
body_to_base_link_z: 0.0
```

### 协方差设置建议

| 场景 | `default_pos_cov` | `default_rot_cov` |
|---|---|---|
| 室内平坦地面（店铺） | `0.01`（±10 cm） | `0.005`（±4°） |
| 室外草地/斜坡 | `0.05`（±22 cm） | `0.01`（±6°） |
| 精度要求极高 | `0.001` | `0.001` |

### 与 NAV2 的接口

在 `nav2_params.yaml` 中：

```yaml
amcl:
  ros__parameters:
    odom_frame_id: odom
    base_frame_id: base_link
    scan_topic: /scan

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

**Q：NAV2 报 `waiting for transform odom → base_link`**
- 确认本节点正在运行：`ros2 node list | grep odom_tf`
- 检查 TF：`ros2 run tf2_ros tf2_echo odom base_link`
- 确认 FAST-LIO2 正常发布 `/Odometry`：`ros2 topic hz /Odometry`

**Q：里程计漂移严重**
- FAST-LIO2 本身已经是紧耦合 LiDAR-IMU 里程计，漂移主要来自退化场景（长走廊、空旷空间）
- 可接入 `robot_localization` EKF 与 IMU 融合进一步平滑

**Q：TF 树报 `would create cycle`**
- 检查 FAST-LIO2 是否也在广播与本节点冲突的 TF（如 `odom→base_link`）
- FAST-LIO2 默认广播 `camera_init→body`，与本节点 `odom→base_link` 不冲突
- 若有其他节点广播同名 TF，将本节点 `publish_tf` 设为 `false`

**Q：`/odom` 频率低于预期**
- FAST-LIO2 里程计约 10 Hz（受 LiDAR 帧率限制）
- 本节点原样透传，频率与输入一致
- NAV2 默认可接受 10~50 Hz 里程计
