# Go2 下次上电运动链路测试清单

更新日期：2026-07-29
目标链路：外载 Jetson Nav2 → UDP 速度网关 → 内载 Jetson 原生 Unitree SDK → Go2 下位机

## 1. 本次改动解决的问题

上一轮测试中，内载网关把同步 `SportClient.Move()` 放在 UDP/ACK 主线程执行。
一次 SDK 调用可能阻塞约 0.45 秒，导致外载看到 ACK 超时并 fail-closed，所以机器狗
只前探或刚起步就停止。

现在的实现把原生 SDK 调用放到独立 worker：

- UDP 解包、序号校验、ACK 和 0.5 秒 watchdog 始终留在主线程；
- worker 每 100 ms 用“最新速度”调用一次 `Move(vx, vy, vyaw)`；
- 不保存历史速度队列，新速度直接覆盖旧速度；
- 零速、watchdog 或 SDK 错误都会清除目标并执行 `StopMove()`；
- worker 的 SDK 错误会回传主线程，网关立即进入 `LOCKED`。

外载还新增了受保护的测试命令。它要求显式确认、限制速度与时长，并在任何异常
路径连续发送零速度。

## 2. 固定网络与接口

| 设备 | 接口 | IP | 用途 |
|---|---|---:|---|
| 外载 Jetson NX | 局域网接口 | `192.168.0.101` | SSH、Web 控制台 |
| 外载 Jetson NX | `eth0`/USB 转网口 | `192.168.123.5` | 只连接内载控制网 |
| 外载 Jetson NX | `eth1` | MID360 网段地址 | 只连接 MID360 雷达 |
| 内载 Jetson | `eth0` | `192.168.123.18` | UDP 网关与原生 SDK |
| Go2 下位机 | Go2 控制网 | `192.168.123.161` | Unitree SportClient |

严禁把 `192.168.123.0/24` 路由到 `eth1`。外载检查：

```bash
ip -br addr show eth0 eth1
ip route get 192.168.123.18
ip route get 192.168.123.161
```

前两条 Go2 地址的结果都必须显示 `dev eth0 src 192.168.123.5`。

## 3. 上电前状态

外载上已保留以下安全状态：

- Web 控制台：`http://192.168.0.101:8080/`；
- `go2-direct-sport.service`：disabled/inactive，仅保留为诊断代码，不用于真机控制；
- UDP sender 启动时只发送 token 0 零速度；
- `localization_guard_enabled: true`；
- 内载服务启动时固定为 `LOCKED`，不会因开机自动行走。

本次新增提交：

```text
958d627 feat: run Unitree Move calls on an SDK worker
44d2482 fix: fail closed on asynchronous SDK errors
347cd97 feat: add guarded Go2 motion smoke test
453e222 fix: preserve deployed posture control interfaces
```

外载 `Go2_nav2` 兼容修正：

```text
038a578 fix: match working Go2 DDS motion request semantics
```

## 4. 第一次上电后的只读检查

以下命令不发送运动指令。

在本地电脑：

```bash
ssh nvidia@192.168.0.101
```

在外载：

```bash
ping -c 2 192.168.123.18
ping -c 2 192.168.123.161
ip route get 192.168.123.18
ip route get 192.168.123.161
systemctl is-enabled go2-direct-sport.service
systemctl is-active go2-direct-sport.service
pgrep -af 'go2_cmd_vel_udp_sender|go2_direct_sport|go2_cmd_vel_bridge'
```

预期：

- 内载 `192.168.123.18` 可达；
- 下位机 `192.168.123.161` 可从 Go2 控制网访问；
- 两条路由都走 `eth0`；
- direct Sport 服务是 `disabled` 和 `inactive`；
- 只允许一个 `go2_cmd_vel_udp_sender`，不得同时运行 direct bridge 或旧 bridge。

进入内载：

```bash
ssh unitree@192.168.123.18
ip -br addr show eth0
ip route get 192.168.123.161
systemctl --no-pager --full status go2-cmd-gateway.service
ss -lunp | grep ':15000'
```

预期 UDP `192.168.123.18:15000` 只有一个监听者。

## 5. 将新 worker 部署到内载

机器狗上电后才能访问内载，因此本步骤留到上电现场执行。先在外载制作源代码包：

```bash
cd /home/nvidia/Go2_Nav_ws/src
tar -czf /tmp/Go2_control_gateway-next.tar.gz Go2_control_gateway
scp /tmp/Go2_control_gateway-next.tar.gz unitree@192.168.123.18:/tmp/
```

进入内载并备份当前可执行文件：

```bash
ssh unitree@192.168.123.18
stamp=$(date +%Y%m%d-%H%M%S)
sudo cp -a /usr/local/bin/go2_cmd_gateway \
  "/home/unitree/go2_cmd_gateway.before-async-${stamp}"
mkdir -p /home/unitree/Go2_control_gateway-next
tar -xzf /tmp/Go2_control_gateway-next.tar.gz \
  -C /home/unitree/Go2_control_gateway-next --strip-components=1
cd /home/unitree/Go2_control_gateway-next
bash scripts/deploy_internal_gateway.sh
```

部署脚本会用内载 `/usr/local/include` 和 `/usr/local/lib` 中的预装 Unitree SDK
编译，替换 `/usr/local/bin/go2_cmd_gateway`，并以 `LOCKED` 状态启动服务。

检查日志，不发送非零速度：

```bash
systemctl --no-pager --full status go2-cmd-gateway.service
journalctl -u go2-cmd-gateway.service -n 80 --no-pager
```

必须看到：

```text
READY bind=192.168.123.18:15000 allowed=192.168.123.5 interface=eth0 mode=unitree
```

## 6. 真机测试前必须人工确认

执行任何运动命令前，先明确告知现场人员，并等待“可以开始”：

1. 机器狗四足接地、机身稳定；
2. 前方至少 1 米安全空间，人员不在运动方向；
3. 电量建议不低于 30%，低电量时不要测试；
4. 遥控器/急停可立即使用；
5. Nav2 未运行或状态为 IDLE；
6. Web 控制台未被其他操作者占用；
7. direct bridge、旧 bridge 均未运行。

没有现场确认时，不得添加 `--confirm-safe`。

## 7. 最短的一键通路测试

在外载执行：

```bash
source /opt/ros/foxy/setup.bash
source /home/nvidia/unitree_ros2/install/setup.bash
source /home/nvidia/Go2_Nav_ws/install/setup.bash
ros2 run go2_control_gateway go2_motion_smoke_test \
  --confirm-safe --vx 0.10 --duration 1.0
```

这条命令的最大硬限制是：

- `|vx| <= 0.20 m/s`；
- `duration <= 2.0 s`；
- ACK 年龄必须 `<= 0.4 s`；
- 开始前必须 online、ACK 新鲜、Nav2 IDLE；
- 结束或异常时连续发送 3 次零速度。

第一次测试理论位移约 0.10 米。先确认是连续迈步，不是只前探。不要直接从 1 米或
1.5 米开始。

同时观察：

```bash
ros2 topic echo /go2_cmd_vel_gateway/status
```

另一个外载终端观察内载日志：

```bash
ssh unitree@192.168.123.18 \
  'journalctl -fu go2-cmd-gateway.service'
```

成功标准：

- `gateway_link=online`；
- token 0 ACK 持续返回且 `control_ready=true`；
- ACK 持续小于 0.4 秒；
- 机器狗连续迈步；
- 测试结束后当前速度回到零；
- 没有 SDK fault、watchdog fault 或重复 sender。

## 8. 从短测试升级到导航

只有 0.10 米测试连续成功两次，才进行下一阶段：

```bash
ros2 run go2_control_gateway go2_motion_smoke_test \
  --confirm-safe --vx 0.20 --duration 2.0
```

单次最多约 0.40 米。确认加速、持续运动、停车均正常后，再启动 Nav2。Nav2 流程：

1. 启动定位、地图与 Nav2；
2. 确认 `/map_to_odom` 连续更新；
3. Web 页面或 RViz 发送导航目标；
4. 确认网关 online、`control_ready=true`；
5. `/cmd_vel` 由外载 sender 以 UDP 下发；
6. 导航结束后确认 `/cmd_vel` 和手动速度均回到零。

不要同时使用 Web 手动速度和 Nav2。Nav2 活跃时控制台会拒绝手动运动，必须先点击
“取消导航”。

## 9. 立即停止与回滚

外载发送零速度：

```bash
ros2 topic pub --once /go2/manual_cmd_vel geometry_msgs/msg/Twist '{}'
```

内载停止服务：

```bash
ssh unitree@192.168.123.18 \
  'sudo systemctl stop go2-cmd-gateway.service'
```

如新 worker 构建或运行异常，在内载回滚：

```bash
sudo systemctl stop go2-cmd-gateway.service
ls -1t /home/unitree/go2_cmd_gateway.before-* | head
sudo install -m 0755 \
  /home/unitree/go2_cmd_gateway.before-async-<时间戳> \
  /usr/local/bin/go2_cmd_gateway
sudo systemctl start go2-cmd-gateway.service
```

回滚后仍以零速度启动；运动前必须重新检查 ACK、Nav2 和现场安全。

## 10. 故障判断

| 现象 | 优先检查 |
|---|---|
| gateway offline | 内载电源、`192.168.123.18`、UDP 15000、外载 `eth0` |
| ACK 大于 0.4 秒 | 是否仍使用旧同步 SDK 二进制、是否有重复 gateway |
| 只前探不走 | 内载是否确实运行 async worker 版本、SDK Move 是否每 100 ms 刷新 |
| mode 始终为 0 | 是否误启用外载 direct DDS；应切回内载原生 SDK 路径 |
| `control_ready` 反复掉线 | 查 SDK fault、watchdog、低电量和 ACK 是否中断 |
| 雷达正常但控制不通 | 雷达只证明 `eth1` 正常；Go2 控制必须检查 `eth0` |

完整控制数据流：

```text
Nav2 /cmd_vel 或 Web /go2/manual_cmd_vel
  -> 外载 go2_cmd_vel_udp_sender (192.168.123.5:15001)
  -> UDP control frame + CRC + session/sequence（兼容字段固定 token 0）
  -> 内载 go2_cmd_gateway (192.168.123.18:15000)
  -> PumpedSportApi worker, 100 ms 最新速度刷新
  -> Unitree 原生 SportClient.Move(vx, vy, vyaw), eth0
  -> Go2 下位机 192.168.123.161

ACK:
内载 GatewayCore -> 外载 sender -> /go2_cmd_vel_gateway/status -> Web/冒烟测试
```
