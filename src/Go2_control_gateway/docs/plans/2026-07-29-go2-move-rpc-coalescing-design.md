# Go2 内载 Move RPC 合并设计

## 背景与证据

外载以 20 Hz 发送速度心跳时，内载网关对每一帧同步调用一次
`SportClient.Move()`。安装在内载板上的 Unitree SDK 将 `Move()` 实现为
同步 `Client::Call()`，而内载 UDP 收包、ACK、watchdog 和 SDK 调用当前位于
同一个线程。

实测结果：

- 20 Hz 会出现 ACK 超过 0.5 秒并触发 fail-closed；
- 降到 3 Hz 后 ACK 稳定，但 7.5 秒、0.2 m/s 仅移动约 0.181 m；
- Unitree 官方高层示例只调用一次 `Move()`，之后由 `StopMove()` 结束，
  不把 `Move()` 当作心跳反复调用。

因此根因是“传输心跳”与“SDK 状态切换 RPC”被错误地一一绑定。

## 方案比较

### 方案 A：仅降低外载发送频率

不改内载，实施最简单，但会造成运动命令保持不足。3 Hz 已证明实际速度远低于
命令速度，不能满足 Nav2。

### 方案 B：关闭 ACK/fail-closed 或大幅增加超时

可以掩盖同步阻塞，但 StopMove 可能排在大量 Move RPC 后面，扩大失控距离，
不采用。

### 方案 C：内载合并 Move RPC（采用）

UDP 心跳仍按 20 Hz 接收并立即 ACK，但只有以下情况调用 SDK：

- 从静止进入非零速度时立即调用一次 `Move()`；
- 速度发生有效变化时，按最大 10 Hz 合并更新；
- 相同速度心跳不重复调用 `Move()`；
- 零速度、watchdog、Disarm、SDK 错误和进程退出仍调用 `StopMove()`。

该方案保持现有协议、外载节点、Web 接口和 fail-closed 边界不变，只修正内载
对 Unitree SDK 的调用语义。

## 状态与数据流

```text
外载 20 Hz ControlFrame
        |
        v
内载校验 session / sequence / token
        |
        +-- 相同非零速度 --> 刷新 watchdog，立即 ACK，不调用 SDK
        |
        +-- 速度变化且达到更新周期 --> SportClient.Move(new_velocity)
        |
        +-- 零速 / Disarm / watchdog --> SportClient.StopMove()
```

内载保存：

- 上一次真正下发给 SDK 的速度；
- 上一次 Move RPC 的单调时钟时间；
- 当前是否处于 moving 状态。

速度差采用小阈值比较，抑制浮点抖动。最小 SDK 更新间隔默认 0.1 秒。

## 故障处理

- Move 返回非零：调用 StopMove，撤销 token，进入 LOCKED，ACK 携带 SDK fault。
- ACK/UDP 失联：内载 watchdog 仍在 0.5 秒后 StopMove 并 LOCKED。
- 零速度：仅在 moving 状态调用一次 StopMove，后续零心跳只 ACK。
- Disarm：无条件 StopMove 并撤销 token。
- Arm：暂不改变，仍只调用一次 BalanceStand。

## 测试

先写失败测试并确认 RED：

1. 20 Hz 重复相同速度时，`Move()` 只调用一次，但每帧都有 ARMED ACK。
2. 速度在 0.1 秒窗口内多次变化时不立即调用；窗口结束后只应用最新速度。
3. 零速度只调用一次 StopMove。
4. watchdog 仍调用 StopMove 并进入 LOCKED。

通过单元测试后，在内载 SDK 环境构建并运行 CTest。物理验证顺序为：

1. Arm 后 0.2 m/s 短脉冲；
2. 检查 ACK 无丢失、SDK 无 fault；
3. 1.5 米、0.2 m/s 验证；
4. 恢复外载默认定位保护和 Web 服务。
