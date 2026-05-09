# Go2_web_bridge

Go2 机器狗远程控制与交互模块，提供云端 WebSocket 桥接（双向数据通道）和本地 TTS 中文语音播报功能。

---

## 架构概览

```
Go2_web_bridge
    ├─ web_bridge_node.py   云端 WebSocket 桥接
    │       ├─ 上行：/odom (2 Hz), /localization (1 Hz), 导航状态（变化时立即上报）
    │       └─ 下行：/goal_pose, /initialpose, /tts_text
    │
    ├─ tts_node.py          中文 TTS 节点
    │       ├─ 订阅 /tts_text (std_msgs/String)
    │       └─ edge-tts 合成 → ALSA 播放
    │
    └─ launch/web_bridge.launch.py  同时启动两个节点
```

---

## 目录结构

```
Go2_web_bridge/
├── Go2_web_bridge/
│   ├── __init__.py
│   ├── web_bridge_node.py    # 云端 WebSocket 桥接节点
│   └── tts_node.py           # 中文 TTS 节点
├── launch/
│   └── web_bridge.launch.py  # 同时启动 web_bridge_node + tts_node
├── config/
│   ├── web_bridge_params.yaml  # 参数参考（当前通过 launch arg 传入，修改此处不生效）
│   └── waypoints.yaml          # 预设航点配置
├── resource/
├── setup.py
├── CMakeLists.txt
└── package.xml
```

---

## web_bridge_node.py

### 功能

将机器人 ROS 2 话题与云端 WebSocket 服务器双向打通，使远程服务器可以监控机器人状态并下发导航指令。

### 上行消息（Robot → Server）

| ROS 话题 | 发送频率 | 说明 |
|---|---|---|
| `/odom` | 2 Hz | 机器人位姿（x, y, yaw）和速度 |
| `/localization` | 1 Hz | ICP 重定位位姿（更高精度） |
| `/navigate_to_pose/_action/status` | 变化时立即发送 | 导航状态（EXECUTING / SUCCEEDED / ABORTED 等） |
| 心跳 `{"action": "ping"}` | 30 s | 保持连接活跃 |

**上行消息格式示例（odom）：**
```json
{
  "action": "odom",
  "data": {
    "x": 1.234,
    "y": 0.567,
    "yaw": 1.57,
    "vx": 0.35,
    "vyaw": 0.0
  }
}
```

### 下行消息（Server → Robot）

| 动作字段 | 目标话题 | 消息类型 | 说明 |
|---|---|---|---|
| `"goal_pose"` | `/goal_pose` | `geometry_msgs/PoseStamped` | 导航目标点（Nav2 接收） |
| `"initialpose"` | `/initialpose` | `geometry_msgs/PoseWithCovarianceStamped` | 重定位初始位姿 |
| `"tts_text"` | `/tts_text` | `std_msgs/String` | 语音播报文本 |

**下行消息格式示例（goal_pose）：**
```json
{
  "action": "goal_pose",
  "data": {
    "x": 2.0,
    "y": 1.5,
    "yaw": 0.0
  }
}
```

### 连接机制

- **自动重连**：断线后等待 `reconnect_delay_sec`（默认 5 秒）自动重连
- **心跳保活**：每 30 秒发送 `{"action": "ping"}` 防止连接被服务器关闭
- **线程架构**：ROS 2 回调与 asyncio WebSocket 在独立线程运行，通过 `queue.Queue` 解耦

### 参数

| 参数 | 默认值 | 说明 |
|---|---|---|
| `server_url` | `ws://121.40.212.85:30100/ws/source?token=...&source_id=dog_001` | 云端 WebSocket 地址（含鉴权 token） |
| `odom_topic` | `/odom` | 里程计话题 |
| `localization_topic` | `/localization` | 定位话题 |
| `odom_publish_hz` | 2.0 | odom 上报频率 |
| `nav_status_publish_hz` | 1.0 | 导航状态轮询频率（变化时立即上报） |
| `reconnect_delay_sec` | 5.0 | 断线重连间隔 |

**注意**：当前参数通过 `run_web_bridge.sh` 和 `web_bridge.launch.py` 中的 LaunchArgument 传入，`web_bridge_params.yaml` 仅作参数参考，修改 yaml 文件不会直接生效。

---

## tts_node.py

### 功能

订阅 `/tts_text` 话题，使用 `edge-tts` 在线 TTS 引擎合成中文语音，通过 ALSA 播放到机器人扬声器。

### 参数

| 参数 | 默认值 | 说明 |
|---|---|---|
| `tts_topic` | `/tts_text` | 订阅的 TTS 文本话题 |
| `voice` | `zh-CN-XiaoxiaoNeural` | edge-tts 语音模型（Microsoft 小晓） |
| `alsa_device` | `plughw:Device,0` | ALSA 音频输出设备 |

### 工作原理

1. 订阅 `/tts_text` 收到文本
2. 调用 `edge-tts` 在线合成为 MP3/WAV 音频（需要网络连接）
3. 通过 `aplay` 或 `ffplay` 播放到指定 ALSA 设备

### 依赖

```bash
pip3 install edge-tts
# ALSA 工具（Ubuntu 20.04 通常已预装）
sudo apt install alsa-utils
```

---

## config/waypoints.yaml

预设航点配置文件，可供 Web 控制台或脚本批量导航使用。

```yaml
# 示例格式
waypoints:
  - name: "充电站"
    x: 0.0
    y: 0.0
    yaw: 0.0
  - name: "会议室门口"
    x: 3.5
    y: 1.2
    yaw: 1.57
```

---

## 启动方式

### 通过 run_web_bridge.sh（推荐）

```bash
# 使用默认服务器地址
bash ~/Go2_Nav_ws/src/Go2_bringup/run_web_bridge.sh

# 指定服务器地址
SERVER_URL="ws://your-server:30100/ws/source?token=xxx&source_id=dog_001" \
bash ~/Go2_Nav_ws/src/Go2_bringup/run_web_bridge.sh
```

**环境变量（run_web_bridge.sh）：**

| 变量 | 默认值 | 说明 |
|---|---|---|
| `SERVER_URL` | `ws://121.40.212.85:30100/...` | 云端 WebSocket 服务器地址 |
| `ODOM_HZ` | `2.0` | odom 上报频率（Hz） |
| `NAV_STATUS_HZ` | `1.0` | 导航状态上报频率（Hz） |
| `RECONNECT_DELAY` | `5.0` | 断线重连间隔（秒） |
| `TTS_ALSA_DEVICE` | `plughw:Device,0` | ALSA 音频设备 |
| `TTS_VOICE` | `zh-CN-XiaoxiaoNeural` | edge-tts 语音模型 |

### 直接 launch

```bash
source ~/Go2_Nav_ws/install/setup.bash
ros2 launch Go2_web_bridge web_bridge.launch.py \
  server_url:="ws://121.40.212.85:30100/ws/source?token=xxx&source_id=dog_001"
```

---

## 话题接口

### 订阅

| 话题 | 消息类型 | 说明 |
|---|---|---|
| `/odom` | `nav_msgs/Odometry` | 里程计（上行到服务器） |
| `/localization` | `nav_msgs/Odometry` | 定位（上行到服务器） |
| `/navigate_to_pose/_action/status` | `action_msgs/GoalStatusArray` | 导航状态（上行到服务器） |
| `/tts_text` | `std_msgs/String` | TTS 文本（本地播报） |

### 发布

| 话题 | 消息类型 | 说明 |
|---|---|---|
| `/goal_pose` | `geometry_msgs/PoseStamped` | 从服务器接收的导航目标点 |
| `/initialpose` | `geometry_msgs/PoseWithCovarianceStamped` | 从服务器接收的重定位位姿 |
| `/tts_text` | `std_msgs/String` | 从服务器接收的 TTS 文本 |

---

## 日志

| 日志文件 | 说明 |
|---|---|
| `/tmp/go2_nav_bringup/web_bridge.log` | web_bridge_node 日志（含连接状态、上下行消息） |

---

## 常见问题

**Q：连接不上云端服务器**
- 检查网络连通性：`curl -v ws://121.40.212.85:30100`
- 确认 token 和 source_id 参数正确
- 注意：域名 wss://jqg.yihexiaozhong.com 的默认 443 端口未提供 wss 服务（实测连接被 reset），必须使用 IP + 30100 端口

**Q：TTS 无声音输出**
- 确认 ALSA 设备名称：`aplay -l`（找到对应设备填入 TTS_ALSA_DEVICE）
- 测试播放：`aplay -D plughw:Device,0 /usr/share/sounds/alsa/Front_Center.wav`
- 确认 edge-tts 网络可达（需要访问 Microsoft TTS 服务）

**Q：目标点下发后机器人不动**
- 检查 Nav2 是否已就绪：`ros2 action list | grep navigate_to_pose`
- 确认 `/goal_pose` 话题有数据：`ros2 topic echo /goal_pose`
- 查看 web_bridge.log 确认消息已接收并发布
