# Go2 异步运动桥接设计

## 背景与已验证事实

目标控制链路保持为：

```text
外载 Nav2 /cmd_vel
  -> UDP 安全网关
  -> 内载 Jetson
  -> Unitree 原生 SportClient
  -> Go2 下位机 192.168.123.161
```

实机测试已经确认：

1. 内载连续调用原生 `SportClient.Move()` 可以让 Go2 迈步。
2. 在内载 UDP 线程中以 10 Hz 或 20 Hz 同步调用 `Move()` 会阻塞 ACK；
   1 米测试在 1.054 秒时因 ACK age 达到 0.45 秒而自动中止。
3. 将相同速度合并为一次 `Move()` 可以保持 ACK 稳定，但 Go2 只会前探，
   不会持续行走。
4. `go2_jetson/web-console-fixes` 的已验证桥接使用非阻塞 ROS 2
   Publisher：10 Hz `/cmd_vel` 被转换为 `unitree_api/Request` 并异步发布到
   `/api/sport/request`。
5. 参考桥接使用 `RecoveryStand(1006)` 进入 locomotion-ready 状态，并为每个
   Request 设置唯一 `identity.id`、`noreply=true`。

## 方案比较

### 方案 A：仅使用外载 DDS 直连

在外载 Foxy 上复刻参考桥接，通过 `eth0` 直接发布
`/api/sport/request`。

优点：

- 改动最小；
- 不存在同步 SDK RPC 阻塞；
- 下次上电可以最快做 A/B 测试。

缺点：

- 当前硬件上外载直连曾停留在 `mode=0`；
- 绕过了用户确认的外载—内载架构；
- 仍需实机确认 `RecoveryStand` 和完整 Request 头是否能解决 mode 问题。

### 方案 B：内载 SDK 运控线程与 UDP/ACK 分离（推荐生产方案）

UDP 主线程只做协议校验、状态机、watchdog 和 ACK。新的 SDK worker 独占
同步 Unitree `SportClient`，以 10 Hz 执行最新的非零速度；速度队列只有一个
槽位，不累计历史命令。

优点：

- 保留已验证的内载原生 SDK 控制路径；
- `Move()` 阻塞不会拖住 UDP ACK；
- watchdog 仍由网络线程独立运行；
- 不需要在内载安装 Humble 或完整 ROS 2。

缺点：

- 比方案 A 多一个线程和异步错误回传；
- 内载断电期间只能完成无 SDK 单元测试，真实 SDK 链接需下次上电完成。

### 方案 C：在内载安装 ROS 2 并运行参考 Python 桥接

优点是最接近参考仓库；缺点是引入 Humble/Foxy、`unitree_api`、
`unitree_go` 和 CycloneDDS 环境迁移，扩大内载负载与维护范围。当前内载
配置有限，因此不采用。

## 最终设计

同时准备方案 A 和方案 B：

- 方案 A 作为下次上电的第一项快速诊断，用于验证完整 Request 语义和
  `RecoveryStand`；
- 方案 B 作为目标生产路径，方案 A 是否成功都不影响其测试。

### 外载异步 DDS 桥接

现有 `go2_cmd_vel_bridge` 保留 Nav2、速度限幅、定位保护和 watchdog，只修改：

1. 每次 Sport API 发布前生成新的单调递增请求 ID；
2. 设置 `lease.id=0`、`policy.priority=0`、`policy.noreply=true`；
3. 运动准备动作改为 `RecoveryStand`；
4. 默认发布频率改为 10 Hz；
5. `go2-direct-sport.service` 继续保持 disabled/inactive，只有人工 A/B
   测试时才临时启动。

### 内载 SDK worker

新增 `PumpedSportApi`，包装现有同步 `SportApi`：

- `BalanceStand`/运动准备动作：停止 worker 后同步执行；
- `Move(vx,vy,vyaw)`：只更新最新目标并立即返回；
- worker：每 100 ms 调用一次后端 `Move()`，不堆积调用；
- `StopMove()`：先清除目标，再与 worker 串行化调用后端 `StopMove()`；
- worker SDK 错误写入原子错误槽；
- `GatewayCore::tick()` 消费错误槽并进入 SDK fault/LOCKED；
- UDP watchdog 超时后无论 worker 状态如何都请求 StopMove；
- 析构和进程退出必须停止 worker 并调用 StopMove。

### 安全约束

- 任何网络恢复、服务重启或新 session 都不会自动 Arm；
- ACK 超时、UDP watchdog、SDK 错误、显式 Disarm 均 fail-closed；
- worker 只保留最新速度，旧速度不会排队执行；
- 零速度和 StopMove 的优先级高于新 Move；
- 外载定位保护正式运行时保持开启；
- 实机测试前必须明确通知用户并获得现场安全确认。

## 测试策略

### 离线测试

- Request 头字段与请求 ID 唯一性；
- 默认运动准备命令为 RecoveryStand；
- `Move()` 在后端阻塞时仍快速返回；
- worker 以受控频率重复最新 Move；
- 更新速度时丢弃旧目标；
- StopMove 后不再执行 Move；
- worker 错误触发 GatewayCore SDK fault；
- 原协议、watchdog、撤销令牌和 Python 控制台测试全部回归。

### 下次上电测试顺序

1. 只做网络、服务、电量和 mode 预检；
2. 外载 DDS 路径：RecoveryStand 后发送 1 秒、0.2 m/s；
3. 若进入持续步态，立即 StopMove，并记录 mode/ACK；
4. 部署或启动内载 SDK worker；
5. 内载链路先做 1 秒、0.2 m/s；
6. 用户确认连续迈步后再做 1 米测试；
7. 恢复定位保护、Web 控制台和正式 systemd 配置。
