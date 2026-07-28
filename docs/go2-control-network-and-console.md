# Go2 外载—内载控制网络与局域网控制台

本文是当前机器人的控制链路交付说明。建图、定位、MID360 雷达和 Nav2 保持运行在外载 Jetson；内载计算机只负责把经过安全校验的速度送入 Unitree 原生 `SportClient`。不要再把外载直连 DDS bridge 作为正常执行路径。

## 1. 地址与接口职责

| 设备 / 接口 | 固定地址 | 职责 |
|---|---|---|
| 外载 Jetson `wlan0` | `192.168.0.101/24` | 局域网管理、SSH、Web 控制台；默认路由从这里走 |
| 外载 Jetson `eth0` | `192.168.123.5/24` | Go2 控制专网，经 USB 转网口连接内载计算机 |
| 外载 Jetson `eth1` | `192.168.1.5/24` | MID360S 雷达专网 |
| 内载计算机 `eth0` | `192.168.123.18/24` | 接收外载 UDP 速度并访问 Go2 下位机 |
| Go2 下位机 | `192.168.123.161/24` | Unitree DDS / Sport API 执行端 |
| MID360S | `192.168.1.158/24` | 点云与 IMU |

特别注意：

- `192.168.123.18` 是内载 Ubuntu 计算机。
- `192.168.123.161` 是 Go2 下位机，不是内载计算机。
- `eth0` 只承载 Go2 控制网，`eth1` 只承载 MID360 雷达，二者都不配置默认网关。
- 外载默认路由只应由 `wlan0` 提供。雷达网不能抢占 `192.168.123.0/24` 的路由。

检查当前配置：

```bash
ip -br address
ip route
ip route get 192.168.123.18
ip route get 192.168.123.161
ip route get 192.168.1.158
nmcli -f NAME,DEVICE,TYPE,IP4.ADDRESS,IP4.GATEWAY connection show --active
```

预期路由：

```text
192.168.123.18  -> eth0，源地址 192.168.123.5
192.168.123.161 -> eth0，源地址 192.168.123.5
192.168.1.158   -> eth1，源地址 192.168.1.5
default         -> wlan0
```

NetworkManager 持久化配置时，先用上面的 `nmcli ... show --active` 找到真实连接名，再执行：

```bash
sudo nmcli connection modify "<eth0 的 Go2 连接名>" \
  ipv4.method manual ipv4.addresses 192.168.123.5/24 \
  ipv4.gateway "" ipv4.never-default yes

sudo nmcli connection modify "<eth1 的 MID360 连接名>" \
  ipv4.method manual ipv4.addresses 192.168.1.5/24 \
  ipv4.gateway "" ipv4.never-default yes
```

不要照抄或删除未知连接名。修改后分别重新激活对应连接，再重复检查 `ip route get`。`/home/nvidia/unitree_ros2/setup.sh` 中 Unitree DDS 的网卡应保持为 `eth0`。

基础连通检查：

```bash
ping -I eth0 -c 3 192.168.123.18
ping -I eth0 -c 3 192.168.123.161
ping -I eth1 -c 3 192.168.1.158
```

## 2. 三层控制架构

```text
外载 Jetson
  Nav2 /cmd_vel
  Web 手动速度 /go2/manual_cmd_vel
           │
           │ UDP 20 Hz
           │ 192.168.123.5:15001
           ▼
内载计算机 192.168.123.18:15000
  go2_cmd_gateway
  协议、序列、令牌、限速、watchdog
           │
           │ Unitree 原生 SportClient
           ▼
Go2 下位机 192.168.123.161
  BalanceStand / Move / StopMove
```

外载继续运行已经测试通过的 MID360、FAST-LIO2、定位和 Nav2。内载不运行 Nav2，也不承担点云计算。原 `go2_cmd_vel_bridge` 源码和 `cmd_vel_bridge.launch.py` 仍保留，但只用于诊断回退。

## 3. UDP 协议与 fail-closed 状态机

外载每 50 ms 发送一个固定 56 字节的网络字节序控制帧，内载返回固定 56 字节 ACK。控制帧包含：

- magic `G2GW`、协议版本、包类型和长度；
- 随进程变化的 `session_id`；
- 单调递增 `sequence`；
- 每次人工 Arm 生成的新 `arm_token`；
- Arm / Disarm 标志；
- `vx`、`vy`、`vyaw`；
- CRC32。

内载依次检查来源 IP、长度、magic、版本、CRC、有限浮点数、session、sequence 和 Arm 令牌。坏 CRC、乱序、重放、NaN/Inf 或错误令牌不会刷新 watchdog。

内载硬限速：

```text
vx   ∈ [-0.6, 0.6] m/s
vy   = 0
vyaw ∈ [-1.4, 1.4] rad/s
```

状态转换：

```text
LOCKED
  └─ 新 Arm 令牌 → BalanceStand → ARMING

ARMING
  └─ 连续有效心跳满 0.8 s → ARMED

ARMED
  ├─ 非零速度 → Move
  ├─ 零速度 / cmd_vel 超时 → StopMove，仍保持 ARMED
  ├─ Disarm → StopMove → LOCKED
  ├─ UDP 超过 0.5 s 未收到有效帧 → StopMove → LOCKED
  └─ SDK 错误 / 协议故障 → StopMove → LOCKED
```

外载超过 `0.5 s` 没收到 ACK 也会立即清除本地 Arm。内载 watchdog 锁定或任一故障后，旧令牌被撤销；网络恢复不会自动继续运动，必须由操作员检查现场并重新 Arm。

## 4. 安装与启动

### 4.1 内载计算机

在内载计算机上、仓库源码可访问时运行：

```bash
bash src/Go2_control_gateway/scripts/deploy_internal_gateway.sh
systemctl status go2-cmd-gateway.service
journalctl -u go2-cmd-gateway.service -f
```

服务随系统启动，但构造函数首先调用 `StopMove()`，状态始终从 LOCKED 开始。配置文件安装到 `/etc/go2-cmd-gateway/gateway.env`。

### 4.2 外载 Jetson

```bash
bash src/Go2_control_gateway/scripts/install_external_services.sh
```

首次安装会在终端安全提示设置 `operator` 密码，只保存 scrypt 哈希，不保存明文。控制台服务地址：

```text
http://192.168.0.101:8080
```

这是受信任局域网内的 HTTP 服务，不做公网端口映射。Cookie 为 HttpOnly / SameSite=Strict，所有改变状态的请求还需要 CSRF 令牌；同一时间只有一个浏览器能持有控制权。

控制台 systemd 服务使用 `rmw_fastrtps_cpp`，不加载把 CycloneDDS 强制绑定到
`eth0` 的 `/home/nvidia/unitree_ros2/setup.sh`。因此内载断电、Go2 专用链路无载波时，
管理页面仍能从 `wlan0` 打开并显示网关离线。该设置只属于 Web 管理面；Nav2 UDP
sender 仍使用已经验证的 `eth0` Unitree DDS 环境。

### 4.3 启动导航

定位和雷达链路照旧启动。启动 Nav2 时默认选择 UDP：

```bash
MAP_YAML=/path/to/map.yaml bash src/Go2_bringup/run_nav2.sh
```

默认值是：

```bash
GO2_CONTROL_BACKEND=udp
```

状态和人工命令：

```bash
bash src/Go2_bringup/go2_gateway_status.sh
bash src/Go2_bringup/go2_gateway_arm.sh
bash src/Go2_bringup/go2_gateway_disarm.sh
```

## 5. 实际操作流程

1. 机器人、内载计算机和外载 Jetson 上电。
2. 确认机器人已经离开充电器、四脚着地、急停条件和周边空间安全。
3. 内载执行 `systemctl status go2-cmd-gateway.service`，应在线且处于 LOCKED。
4. 外载启动 MID360、FAST-LIO2、定位和 Nav2；确认 `/scan`、`/map_to_odom`、`/cmd_vel` 所需链路正常。
5. 浏览器打开 `http://192.168.0.101:8080`，用 `operator` 登录。
6. 检查电量、网关在线、运动模式、速度、里程计和 Nav2 状态。
7. 点击“接管控制”，确认现场安全后点击 Arm，并等待 ARMED。
8. 导航时下发 Nav2 目标。Nav2 活跃期间服务器拒绝手动控制。
9. 如需手动移动，先点击“取消导航”，等待 Nav2 显示 IDLE，再按住方向按钮。只有按住时运动，松开、页面失焦、WebSocket 断开或租约丢失都会归零。
10. 任务完成后点击 Disarm，确认 LOCKED。
11. 关机或重新接充电器前，再执行一次 `go2_gateway_disarm.sh`。

Disarm 不要求持有控制租约，只要求已经登录，因此在另一个浏览器占用控制权时仍可安全停止。

## 6. 故障排查

### 网关离线

```bash
ip route get 192.168.123.18
ping -I eth0 -c 3 192.168.123.18
ss -lunp | grep 1500
PYTHONUNBUFFERED=1 timeout 3s \
  ros2 topic echo /go2_cmd_vel_gateway/status std_msgs/msg/String
```

确认外载源端口为 `15001`，内载监听 `15000`，防火墙没有拦截两板之间的 UDP。

### 下位机不通

在内载检查：

```bash
ip route get 192.168.123.161
ping -c 3 192.168.123.161
journalctl -u go2-cmd-gateway.service -n 100 --no-pager
```

### 雷达异常

```bash
ip route get 192.168.1.158
ping -I eth1 192.168.1.158
ros2 topic hz /livox/lidar
```

如果 `192.168.123.161` 被路由到 `eth1`，说明接口配置再次混入了错误网段；修复 NetworkManager 连接配置，不要用临时主机路由掩盖错误。

### Arm 失败

- 网关必须先在线；
- 必须使用未撤销的新令牌；
- 内载 `BalanceStand()` 必须返回 0；
- ARMING 的 0.8 秒内必须持续收到 20 Hz 心跳；
- 任何 `0.5 s` 失联都会回到 LOCKED。

### 控制台不能手动移动

- 必须登录、接管控制且状态为 ARMED；
- 网关必须在线；
- Nav2 必须为 IDLE；若为 EXECUTING，先点击“取消导航”；
- 页面必须保持可见并持续按住控制键。

## 7. 停机、恢复与回退

正常停机：

```bash
bash src/Go2_bringup/go2_gateway_disarm.sh
sudo systemctl stop go2-console.service
# 内载上执行
sudo systemctl stop go2-cmd-gateway.service
```

内载守护进程收到 SIGTERM 后仍会走 `StopMove()` 退出路径。

失联恢复：

1. 不要立即重发旧目标；
2. 检查机器人姿态、网线、`eth0` 路由和服务日志；
3. 取消残留 Nav2 目标；
4. 确认链路恢复后重新“接管控制”；
5. 使用新令牌重新 Arm。

诊断回退到旧外载直连 DDS bridge：

```bash
bash src/Go2_bringup/go2_gateway_disarm.sh
GO2_CONTROL_BACKEND=direct-dds \
  MAP_YAML=/path/to/map.yaml \
  bash src/Go2_bringup/run_nav2.sh
```

该路径只用于定位问题。此前实机已经确认外载直连 DDS 的 Move 只会前探、不能稳定进入迈步模式，因此不能作为正常交付路径。

## 8. 当前验证边界

已完成 Python 单元/HTTP/前端契约、Jetson aarch64 C++ 协议与状态机测试、UDP dry-run 集成以及桌面/移动浏览器冒烟验证。2026-07-28 已把源码部署到外载 `/home/nvidia/Go2_Nav_ws`，并在其 Ubuntu 20.04、ROS 2 Foxy、Python 3.8 环境完成 `79 passed`；ROS sender → C++ dry-run gateway 的在线、Arm、ACK、Disarm、LOCKED 闭环也已通过。

外载 Web 服务已安装并启用。2026-07-28 从局域网访问首页、登录和状态 API 均返回 HTTP 200；在内载离线且 `eth0` 无载波时，页面正确显示网关离线、未 Arm。密码文件 `/etc/go2-console/password.hash` 只保存 scrypt 哈希，仓库不保存明文密码。

内载关机期间仍无法完成 `/usr/local/lib/libunitree_go2_sdk.a` 的最终链接和新网关实机运动验收；这些项目在[验收清单](go2-control-acceptance-checklist.md)中明确标为暂未验证，不能用 dry-run 结果替代。
