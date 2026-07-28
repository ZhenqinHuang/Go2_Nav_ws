# Go2 外载—内载 UDP 控制网关与局域网控制台设计

## 1. 背景与结论

Go2 导航、建图和 MID360S 雷达链路运行在外载 Jetson 上。现有
`go2_cmd_vel_bridge` 会从外载直接向 Go2 下位机发布 Unitree Sport API
DDS 请求。实机诊断确认：

- 外载可以通过 `eth0` 收到 `/sportmodestate`、`/lowstate` 和 Sport API
  响应；
- 外载直接发送 Move 时，机器人保持 `mode=0`，只发生前探，不进入
  `mode=3 locomotion`；
- 内载计算机使用本机 Unitree 原生 `SportClient` 调用
  `BalanceStand()`、`Move()`、`StopMove()` 时，机器人能够实际迈步。

因此执行链路固定为：

```text
外载 Jetson：Nav2 /cmd_vel
          ↓ 专用网线 UDP
内载计算机：cmd_vel 网关
          ↓ Unitree 原生 SportClient
Go2 下位机：192.168.123.161
```

雷达、FAST-LIO、定位和 Nav2 的现有测试通过链路保持不变。

## 2. 网络与设备职责

| 设备/接口 | 地址 | 职责 |
|---|---|---|
| 外载 Jetson `wlan0` | `192.168.0.101/24` | 管理、SSH、局域网 Web 控制台 |
| 外载 Jetson `eth0` | `192.168.123.5/24` | Go2 专用控制网；连接内载和下位机 |
| 外载 Jetson `eth1` | `192.168.1.5/24` | MID360S 雷达专用网络 |
| 内载计算机 `eth0` | `192.168.123.18/24` | 接收外载 UDP 控制，访问 Go2 下位机 |
| Go2 下位机 | `192.168.123.161/24` | Unitree DDS/Sport API 运动执行 |
| MID360S | `192.168.1.158/24` | 点云与 IMU 数据 |

网络配置约束：

- `eth0` 只保留 Go2 网段，不配置默认网关；
- `eth1` 只保留 MID360S 网段，不配置默认网关；
- 管理默认路由由 `wlan0` 提供；
- Unitree DDS 配置绑定外载 `eth0`，雷达网络不承载底盘流量。

## 3. 组件设计

### 3.1 外载 ROS 2 UDP sender

新增 `go2_cmd_vel_udp_sender`：

- 订阅 Nav2 `/cmd_vel`；
- 订阅控制台手动速度输入；
- 保留现有 bridge 的限速、死区、角速度平滑、定位健康检查和
  `cmd_vel` 超时逻辑；
- 绑定源地址 `192.168.123.5`，以 20 Hz 向
  `192.168.123.18:15000` 发送控制帧；
- 接收内载 ACK，发布链路、Arm 和故障状态；
- 提供 `std_srvs/SetBool` Arm/Disarm 服务；
- 启动、进程重启和 ACK 超时后均保持未 Arm。

现有直接 DDS bridge 不删除，作为诊断和回退入口；正常导航启动默认改用
UDP sender。

### 3.2 内载原生 SDK 网关

新增独立 C++ 守护进程 `go2_cmd_gateway`：

- 不运行 Nav2，不依赖 Unitree ROS 2 消息包；
- 使用内载已有 `/usr/local/lib/libunitree_go2_sdk.a`；
- UDP 监听绑定 `192.168.123.18:15000`；
- 只接受来自 `192.168.123.5` 的合法控制帧；
- Arm 时执行 `BalanceStand()`，稳定后才允许 `Move()`；
- 在 ARMED 状态以 20 Hz 调用 `SportClient.Move()`；
- 零速度、Disarm、失联或故障调用 `StopMove()`；
- 通过 systemd 开机自启，但启动状态始终为 LOCKED。

### 3.3 局域网 Web 控制台

控制台运行在外载 Jetson：

```text
http://192.168.0.101:8080
```

使用 `rclpy + aiohttp` 提供服务端鉴权、HTTP、WebSocket 和 ROS 2
适配，静态前端随仓库一同部署。控制权限在服务端校验，不能只隐藏前端按钮。
现有 rosbridge 仅允许本机访问，浏览器不能绕过鉴权直接向关键 ROS 2
话题发布数据。

页面功能：

- 独立 `operator` 登录；
- 密码使用 scrypt 哈希保存，不保存明文；
- 同一时间只允许一个浏览器持有控制租约；
- 显示网关连接、Arm、运动模式、Nav2 状态；
- 显示电量、当前速度、里程计位置；
- Arm 二次确认，Disarm 始终可用；
- 前进、后退、左转、右转、停止；
- 手动线速度和角速度调节；
- 按住按钮才运动，松开、页面失焦、控制租约丢失或 WebSocket
  中断立即发送零速度；
- Nav2 活跃时服务端拒绝手动控制；操作员必须先点击“取消导航”，等
  Nav2 确认空闲后才能进入手动模式。

控制台使用可信局域网 HTTP，不提供传输加密，不允许端口映射到公网。

## 4. UDP 协议

控制帧为固定长度、网络字节序的二进制结构，包含：

- 协议魔数和版本；
- 结构长度；
- sender 启动时生成的随机 `session_id`；
- 单调递增 `sequence`；
- 每次显式 Arm 生成的新 `arm_token`；
- Arm/Disarm/heartbeat 标志；
- `vx`、`vy`、`vyaw`；
- CRC32。

ACK 包含：

- 协议魔数和版本；
- 已处理的 `session_id`、`sequence`、`arm_token`；
- LOCKED、ARMING、ARMED 或 FAULT 状态；
- 最近 SDK 返回码；
- 最近 Stop/故障原因；
- CRC32。

内载对每帧执行：

1. 源 IP 检查；
2. 长度、魔数和版本检查；
3. CRC32 检查；
4. session、sequence 和 Arm 令牌检查；
5. NaN/Inf 检查；
6. 二次限速。

任一检查失败即丢弃数据，并且不刷新 watchdog。

内载硬限幅：

```text
vx    ∈ [-0.6, 0.6] m/s
vy    = 0
vyaw  ∈ [-1.4, 1.4] rad/s
```

## 5. Arm 与 fail-closed 状态机

```text
LOCKED
  └─ 新的显式 Arm 令牌
       → BalanceStand
       → ARMING
       → 稳定 0.8 s
       → ARMED

ARMED
  ├─ 有效非零速度 → Move
  ├─ 零速度或 Nav2 cmd_vel 超时 → StopMove，保持 ARMED
  ├─ 显式 Disarm → StopMove → LOCKED
  ├─ UDP 失联 → StopMove → LOCKED，撤销令牌
  └─ SDK/协议错误 → StopMove → LOCKED，撤销令牌
```

安全定时：

| 条件 | 阈值 | 动作 |
|---|---:|---|
| Nav2 `/cmd_vel` 未更新 | 0.6 s | 外载发送零速度心跳；内载停止但保持 Arm |
| 内载未收到合法 UDP 帧 | 0.5 s | `StopMove`、Disarm、作废 Arm 令牌 |
| 外载未收到 ACK | 0.5 s | 清除本地 Arm 状态，禁止非零速度 |
| Arm 未获确认 | 1.0 s | Arm 服务返回失败 |
| SDK 控制调用异常 | 立即 | `StopMove`、Disarm、进入故障状态 |

失联后旧 Arm 令牌不能再次使用。网络恢复不会自动继续运动，必须由操作员
重新检查环境并显式 Arm。

## 6. 实际操作流程

1. Go2、内载计算机和外载 Jetson 上电；
2. 内载 systemd 网关自动启动并保持 LOCKED；
3. 外载启动雷达、定位、Nav2、UDP sender 和控制台；
4. 操作员访问控制台并登录；
5. 检查机器人已离开充电器、四脚着地、环境安全且网关在线；
6. 点击 Arm 并等待内载 ARMED 确认；
7. 下发 Nav2 目标，或在 Nav2 空闲时进入手动控制；
8. 任务结束后取消导航并点击 Disarm；
9. 确认 LOCKED 后关闭系统或充电。

失联/故障恢复：

1. 内载自动 StopMove 并锁定；
2. 操作员检查机器人、网线和控制台故障原因；
3. 清除旧导航目标；
4. 链路恢复后重新显式 Arm；
5. 重新下发任务。

## 7. 测试与验收

按测试驱动实施：

1. 协议编码、CRC、乱序、重放和非法浮点单元测试；
2. Arm 令牌和 fail-closed 状态机单元测试；
3. 内载网关 dry-run 测试，不调用真实 SDK；
4. 控制台认证、单控制者、导航互锁和松开归零测试；
5. 两块板上电后完成无运动联调：连接、ACK、Arm/Disarm、非法帧和
   watchdog；
6. 获得现场安全确认后完成低速短距离手动运动；
7. 拔除/禁用控制链路验证 0.5 s 内 StopMove 和自动 Disarm；
8. 最后验证 Nav2 `/cmd_vel` 完整控制链路。

未通过无运动测试前不进行实机运动。

## 8. 部署与回退

内载安装：

- 网关二进制；
- `/etc/go2-cmd-gateway/` 配置；
- `go2-cmd-gateway.service`。

外载安装：

- ROS 2 UDP sender；
- 控制台后端和静态前端；
- 控制台 systemd 服务；
- 状态、Arm、Disarm 和密码设置脚本；
- 更新后的 Nav2 启动脚本。

回退：

- Disarm；
- 停止并禁用新 systemd 服务；
- 恢复导航启动脚本的执行后端；
- 保留原直接 DDS bridge 源码和启动入口，不删除雷达/导航功能。

## 9. 文档交付

开发和实机验收后同时更新仓库文档与用户指定的飞书文档。飞书文档至少
包括：

- 所有 IP、子网、静态路由和 NetworkManager 配置；
- 外载 `eth0`、`eth1`、`wlan0` 的职责和排障方法；
- 外载—内载—Go2 下位机控制架构；
- UDP 协议、Arm、watchdog 和 fail-closed 链路；
- Web 登录、控制租约、手动控制、Nav2 互锁；
- 上电、Arm、运行、Disarm、关机和故障恢复流程；
- 实机测试记录和已知限制。

当前环境没有飞书连接器。验收后通过用户已登录的浏览器访问指定飞书文档
并更新；届时需要文档链接。
