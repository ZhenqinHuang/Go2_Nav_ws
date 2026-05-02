# Go2_time_sync

基于 PTP (IEEE 1588) 的硬件时间戳同步包，设计用于 Go2 机器人主机（Master）与 MID360 激光雷达（Slave）之间的精确时间同步。

> **当前状态（2026-04）**：MID360 PTP 硬件时间同步暂时无法正常工作，该模块**当前未启用**。系统统一使用主机系统时钟，MID360 Livox 驱动直接以系统时间为点云打时间戳。
>
> **当前时间链路**：
> ```
> 主机系统时钟（建议 NTP 同步）
>         │
>   Livox 驱动使用系统时间 → /livox/lidar.header.stamp
>         │
>   FAST-LIO2 透传 → /Odometry.stamp
> ```
>
> 使用建议：运行前通过 NTP 同步主机时钟，避免时间戳漂移导致 TF 查询失败：
> ```bash
> sudo ntpdate ntp.aliyun.com
> ```

---

## 目录结构

```
Go2_time_sync/
├── CMakeLists.txt
├── package.xml
├── setup.py
├── config/
│   ├── ptp_sync.yaml        # 主配置文件（含 NTP + PTP 参数）
│   ├── ptp4l_master.cfg     # ptp4l 参考配置
│   └── ptp_sync.service     # systemd 开机自启服务
├── go2_time_sync/
│   ├── ptp_sync_node.py     # ROS2 同步节点（含 NTP 校准）
│   └── ptp_monitor_node.py  # ROS2 状态监控节点
├── launch/
│   └── ptp_sync.launch.py
└── scripts/
    ├── sync_host_time.py    # 本机 NTP 时间校准工具（独立使用）
    ├── start_ptp_sync.py    # 完整启动脚本（NTP + PTP）
    └── check_ptp_env.py     # 环境检查脚本（含 NTP 服务器检查）
```

---

## 工作原理

```
互联网 NTP 服务器（阿里云/腾讯云/Pool 等）
       ↓  步骤1: NTP 校准（sync_host_time.py）
系统时钟 (CLOCK_REALTIME) ← 更新为准确的网络时间
       ↓  步骤2: phc2sys（系统时钟 → 网卡 PHC）
网卡硬件时钟 (PHC)
       ↓  步骤3: ptp4l IEEE 1588 Master
MID360 内部时钟 (Slave，自动跟随)
```

本机作为 PTP Master，首先通过 NTP 将自身系统时钟校准到互联网标准时间，再通过网卡硬件时间戳向 MID360 广播精确时间。硬件时间戳模式下时间偏差通常在 **100 ns ~ 1 μs** 级别。

---

## 依赖安装

```bash
sudo apt install linuxptp ethtool
```

---

## 配置

编辑 `config/ptp_sync.yaml`，根据实际环境修改以下配置：

### 网络与雷达配置（必须修改）

```yaml
network:
  interface: "eth0"       # 连接 MID360 的网卡名称（用 ip link 查看）

lidar:
  ip: "192.168.1.12"      # MID360 的 IP 地址
  host_ip: "192.168.1.5"  # 本机 IP 地址
```

### NTP 时间校准配置（可选调整）

```yaml
ntp:
  enabled: true           # 是否启用 NTP 校准（建议 true）
  servers:                # NTP 服务器列表（按优先顺序依次尝试）
    - "ntp.aliyun.com"
    - "cn.pool.ntp.org"
    - "time1.cloud.tencent.com"
    - "pool.ntp.org"
  timeout: 5                   # 单个服务器查询超时（秒）
  max_offset_seconds: 1.0      # 超过此偏差才校准（0=始终校准）
  retry_count: 2               # 全部服务器失败后的重试次数
  continue_on_failure: true    # NTP 失败时是否仍继续启动 PTP
```

---

## 使用方法

### 第一步：环境检查

```bash
python3 scripts/check_ptp_env.py
```

检查项目：依赖工具、网卡状态、**NTP 服务器可达性**、雷达连通性。

### 第二步：启动同步

#### 方式一：完整启动脚本（推荐）

```bash
# 完整流程：NTP 本机校准 → PTP 从机同步
sudo python3 scripts/start_ptp_sync.py

# 指定配置文件
sudo python3 scripts/start_ptp_sync.py --config /path/to/ptp_sync.yaml

# 跳过 NTP 校准直接启动 PTP（网络不可用时）



# NTP 仅检测偏差，不修改时钟（调试用）
sudo python3 scripts/start_ptp_sync.py --ntp-dry-run
```

按 `Ctrl+C` 停止。

#### 方式二：单独执行 NTP 校准

```bash
# 仅同步本机时间到 NTP 网络时间（无需启动 PTP）
sudo python3 scripts/sync_host_time.py

# 强制校准（忽略偏差阈值）
sudo python3 scripts/sync_host_time.py --force

# 仅检测偏差，不修改时钟
python3 scripts/sync_host_time.py --dry-run
```

#### 方式三：ROS2 Launch

```bash
cd /home/unitree/Go2_Nav_ws
colcon build --packages-select go2_time_sync
source install/setup.bash
sudo ros2 launch go2_time_sync ptp_sync.launch.py
```

可用参数：

```bash
sudo ros2 launch go2_time_sync ptp_sync.launch.py \
  config_file:=/path/to/ptp_sync.yaml \
  skip_ntp:=false \
  ntp_dry_run:=false
```

#### 方式四：开机自启（systemd）

```bash
# 复制服务文件
sudo cp config/ptp_sync.service /etc/systemd/system/

# 启用并启动
sudo systemctl daemon-reload
sudo systemctl enable ptp_sync.service
sudo systemctl start ptp_sync.service

# 查看状态
sudo systemctl status ptp_sync.service
```

---

## ROS2 话题

| 话题 | 类型 | 说明 |
|------|------|------|
| `/ptp_sync/status` | `std_msgs/String` | 同步状态（接口、IP、NTP/PTP 偏移） |
| `/ptp_sync/is_synced` | `std_msgs/Bool` | PTP 从机是否已完成同步 |
| `/diagnostics` | `diagnostic_msgs/DiagnosticArray` | ROS 诊断信息（含 NTP 状态） |

查看同步状态：

```bash
ros2 topic echo /ptp_sync/status
ros2 topic echo /ptp_sync/is_synced
```

---


## 常见问题

**Q: ptp4l 提示权限不足**

ptp4l 需要 root 权限访问网卡硬件时钟，必须使用 `sudo` 运行。

**Q: NTP 校准失败**

- 检查网络连接是否正常（`ping ntp.aliyun.com`）
- 可在 `config/ptp_sync.yaml` 中设置 `continue_on_failure: true` 使 NTP 失败后仍继续 PTP
- 或使用 `--skip-ntp` 跳过校准步骤

**Q: 网卡不支持硬件时间戳**

运行 `ethtool -T <网卡名>` 查看支持情况。若不支持 `hardware-transmit`，程序会自动回退到软件时间戳，精度约 10 μs 级别，仍可正常使用。

**Q: 无法 ping 通 MID360**

检查本机 IP 是否与 MID360 在同一网段（默认 `192.168.1.x`），并确认网线已连接。

**Q: 如何确认 MID360 已完成同步**

MID360 支持 PTP Slave 模式，上电后会自动向网络中的 Master 发起同步请求。可通过 Livox Viewer 或查看点云时间戳是否与系统时间一致来验证。
