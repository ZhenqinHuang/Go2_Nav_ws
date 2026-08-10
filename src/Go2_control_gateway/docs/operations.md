# Go2 外载—内载控制台操作手册

## 1. 固定地址与网卡职责

| 设备 / 接口 | 地址 | 职责 |
|---|---:|---|
| 外载 Jetson `wlan0` | `192.168.0.101/24` | 局域网 SSH、Web 控制台和默认路由 |
| 外载 Jetson `eth0` | `192.168.123.5/24` | Go2 控制专网，连接内载计算机 |
| 外载 Jetson `eth1` | `192.168.1.5/24` | MID360S 雷达专网 |
| 内载计算机 `eth0` | `192.168.123.18/24` | 接收外载速度并访问 Go2 下位机 |
| Go2 下位机 | `192.168.123.161/24` | Unitree DDS / Sport API |
| MID360S | `192.168.1.158/24` | 点云与 IMU |

必须满足：

```text
192.168.123.18  -> eth0，源地址 192.168.123.5
192.168.123.161 -> eth0，源地址 192.168.123.5
192.168.1.158   -> eth1，源地址 192.168.1.5
default         -> wlan0
```

`eth0` 和 `eth1` 都不配置默认网关。`/home/nvidia/unitree_ros2/setup.sh` 中 Unitree DDS
网卡保持为 `eth0`。

只读检查：

```bash
ip -br address
ip route
ip route get 192.168.123.18
ip route get 192.168.123.161
ip route get 192.168.1.158
nmcli -f NAME,DEVICE,TYPE,IP4.ADDRESS,IP4.GATEWAY connection show --active
```

基础连通：

```bash
ping -I eth0 -c 3 192.168.123.18
ping -I eth0 -c 3 192.168.123.161
ping -I eth1 -c 3 192.168.1.158
```

## 2. 控制与可视化边界

```text
浏览器
  ├─ 固定认证 API ──> 导航目标、取消、初始位姿、手动控制
  └─ /ws/ros ──────> 只读白名单代理 ──> 127.0.0.1:9090 rosbridge

外载 ROS 2
  Nav2 /cmd_vel ─┐
                 ├─> go2_cmd_vel_udp_sender
  手动 cmd_vel ──┘
      192.168.123.5:15001 ── UDP 20 Hz ──> 192.168.123.18:15000
                                                   │
                                                   ▼
                                         内载 go2_cmd_gateway
                                                   │
                                                   └─> SportClient ─> Go2
```

浏览器不能直接调用 ROS publish、service 或 action。导航请求由后端固定 action client
执行；初始位姿由后端固定 publisher 执行。rosbridge 仅绑定回环地址，并且代理只允许订阅
地图、雷达、TF、路径、代价地图、点云、里程计和 Nav2 状态等白名单主题。

## 3. fail-closed 规则

- 外载和内载分别运行独立 watchdog，任一端失联都进入安全停止；
- 内载仅接受固定来源、正确 magic/版本/长度/CRC、有限浮点数、新序号、token 0 普通速度帧；
- 内载硬限速：`vx ∈ [-0.6, 0.6] m/s`、`vy = 0`、`vyaw ∈ [-1.4, 1.4] rad/s`；
- 首个非零速度由 SDK worker 在后台执行一次 `BalanceStand`，成功后使用最新速度调用 `Move`；
- UDP 超过 0.5 秒没有有效帧、SDK 错误或协议错误都会 `StopMove` 并锁定；
- 外载超过 0.5 秒没有 ACK 会清除本地速度命令并持续发送零速度；
- 浏览器松开按钮、失焦、隐藏、WebSocket 断开或控制权丢失立即归零；
- Nav2 活跃时禁止手动控制，必须先人工点击“取消导航”；
- 网络恢复不会自动恢复旧运动命令，必须检查现场、重新获取控制权并重新发送速度。

## 4. 实际操作流程

1. 机器人离开充电器，确认四脚着地、急停条件和周围空间安全。
2. 启动内载与外载，检查内载 `go2-cmd-gateway.service` 在线且为 `LOCKED`。
3. 外载启动 MID360、FAST-LIO2、定位和 Nav2，确认地图、TF、激光及里程计正常。
4. 浏览器访问 `http://192.168.0.101:8080`，使用现场配置的 `operator` 密码登录。
5. 检查电量、网关、速度通路、Nav2、当前速度和里程计状态。
6. 点击“接管控制”，确认网关和速度通路均为在线/就绪。
7. 导航时在地图设置单点或多点目标。Nav2 活跃期间手动按钮保持锁定。
8. 需要手动移动时先点击“取消导航”，等待 Nav2 为 `IDLE`，再按住方向按钮或按键。
9. 任务结束先停止导航或松开手动按钮，确认当前速度回到零。
10. 关机或接充电器前先停止外载 sender，再停止内载网关服务。

页面速度滑块只调节手动前进和转向速度，不修改 Nav2 已验证配置。

## 5. 服务检查与安全停机

外载：

```bash
systemctl status go2-console.service
systemctl status go2-console-rosbridge.service
ss -lntp | grep -E ':8080|:9090'
journalctl -u go2-console.service -n 100 --no-pager
journalctl -u go2-console-rosbridge.service -n 100 --no-pager
```

预期 `8080` 监听 `192.168.0.101`，`9090` 只监听 `127.0.0.1`。

安全停机：

```bash
ros2 topic pub --once /go2/manual_cmd_vel geometry_msgs/msg/Twist '{}'
sudo systemctl stop go2-console.service
```

内载随后执行：

```bash
sudo systemctl stop go2-cmd-gateway.service
```

## 6. 常见问题

网关离线：

```bash
ip route get 192.168.123.18
ping -I eth0 -c 3 192.168.123.18
ss -lunp | grep 1500
```

下位机不通：

```bash
ip route get 192.168.123.161
ping -I eth0 -c 3 192.168.123.161
```

若 `192.168.123.161` 被路由到 `eth1`，说明雷达网卡再次混入 Go2 网段；应修复
NetworkManager 持久连接，不要使用临时主机路由掩盖错误。

雷达异常：

```bash
ip route get 192.168.1.158
ping -I eth1 -c 3 192.168.1.158
ros2 topic hz /livox/lidar
```

控制台不能手动移动时，依次确认：已登录、已取得控制权、网关在线、速度通路就绪、Nav2
为 IDLE、页面可见且方向按钮持续按住。

## 7. 凭据与发布

- 密码仅通过安装命令设置，哈希保存在 `/etc/go2-console/password.hash`；
- 不把明文密码、密码哈希、SSH 私钥、Cookie 或现场令牌提交到 GitHub；
- 控制台仅用于受信任局域网，不向公网做端口映射；
- 修改白名单或新增运动 API 时，必须补充拒绝测试和断连归零测试。
