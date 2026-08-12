# Jetson 后续开发边界

本文用于在 Jetson 上继续开发 Go2 功能时保护现有 SLAM、导航、Web 和运动安全链路。新增功能可以复用公开接口，但不得绕过网关、抢占 TF 所有权或直接覆盖当前地图。

## 1. 固定架构

```text
MID360S -> Livox Driver -> FAST-LIO2
  -> odom_tf_bridge -> /odom、odom -> base_link
  -> fast_lio_localization_ros2 -> map -> odom
  -> go2_pc2scan -> /scan
  -> Nav2 -> /cmd_vel

Nav2 /cmd_vel 或 Web /go2/manual_cmd_vel
  -> Jetson go2-motion-sender.service
  -> UDP 内载安全网关
  -> Unitree SportClient
  -> Go2
```

唯一完整 TF 链是 `map -> odom -> base_link`。Jetson 直连 Unitree DDS 只允许在显式维护模式使用，并且必须与 UDP sender 互斥。

## 2. 网络边界

| 设备/接口 | 地址 | 职责 |
|---|---|---|
| Jetson `wlan0` | `192.168.0.101/24` | SSH、Web、默认路由 |
| Jetson `eth0` | `192.168.123.5/24` | Go2 控制专网；不设默认网关 |
| Jetson `eth1` | `192.168.1.5/24` | MID360S 专网；不设默认网关 |
| 内载 Ubuntu `eth0` | `192.168.123.18/24` | UDP 安全网关 |
| MID360S | `192.168.1.158/24` | 激光雷达 |
| Go2 下位机 | `192.168.123.161/24` | Unitree DDS/Sport API |

上电后必须确认 `.18` 和 `.161` 经 `eth0`，`.158` 经 `eth1`，默认路由经 `wlan0`。控制专网断开时允许感知和只读 Web 状态运行，但运动状态必须 fail closed。

## 3. 外载、内载和下位机职责

- 外载 Jetson：雷达、FAST-LIO2、定位、Nav2、Web、限速前置检查和 UDP sender。
- 内载 Ubuntu：协议校验、序号、CRC、Arm 令牌、ACK、限速、双端 watchdog、锁存急停和 SportClient 执行。
- Go2 下位机：只接受内载计算机经 Unitree 官方接口发出的最终命令。
- 新功能不得让浏览器、Nav2 节点或普通 ROS 节点直接调用 Unitree DDS。

## 4. 运动安全规则

- 所有手动速度必须按住执行，释放、超时、断线或租约丢失立即归零。
- Nav2 与手动控制只能有一个活动速度源。
- `emergency-stop` 不要求控制租约；触发后外载和内载同时锁存，并取消导航、清空速度。
- 急停复位要求控制租约有效、导航停止、速度为零、网关 ACK 和定位新鲜。
- 姿态只保留站立和趴下；必须经 UDP 网关离散命令执行，并以网关 ACK 为成功依据。
- 未经现场人员明确授权，不发送非零速度，不执行站立或趴下。

## 5. ROS、TF 与接口所有权

| 输出 | 唯一所有者 |
|---|---|
| `/Odometry`、实时注册点云 | FAST-LIO2 |
| `/odom`、`odom -> base_link` | `odom_tf_bridge` |
| `map -> odom`、`/map_to_odom` | `fast_lio_localization_ros2` |
| `/scan`，frame=`base_link` | `go2_pc2scan` |
| `/map` | Nav2 中唯一的 `map_server` |
| `/cmd_vel` | Nav2 controller；由 sender 接收 |
| `/go2/manual_cmd_vel` | Web 手动控制；由 sender 接收 |

新增节点前先检查 topic、frame、QoS 和 TF broadcaster。不得新增第二个 `map -> odom`、`odom -> base_link` 或 `map_server` 所有者，也不得用固定 sleep 代替 topic/TF/lifecycle 新鲜度判断。

## 6. 地图边界

当前地图包固定为：

```text
maps/MID360.pcd
maps/MID360_map.pgm
maps/MID360_map.yaml
maps/map_manifest.yaml
```

四个文件必须来自同一次建图。新地图先写入 `maps/staging/<session>/`，通过大小、SHA-256、YAML image 和 Manifest 校验后，再使用 `scripts/map_bundle.py promote` 原子切换。旧地图进入 `maps/archive/`，不参与启动；不得只覆盖 PCD、PGM 或 YAML 中的单个文件。

## 7. Web 与 API 边界

- 正式控制台为 `src/Go2_web_console`，服务地址为 `http://192.168.0.101:8080`。
- 认证密码、哈希、会话密钥和证书不进入 Git。
- 浏览器控制必须经过后端认证、CSRF、单操作者租约和服务器端安全门禁。
- rosbridge 仅允许经认证代理读取白名单数据，不能作为运动命令旁路。
- API 使用统一 `{ok, code, message, data}` 响应；接口字段变化必须同步更新后端、前端和契约测试。

## 8. 工作空间、服务与部署

| 路径 | 内容 |
|---|---|
| `/home/nvidia/Go2_Nav_ws` | 本项目 |
| `/home/nvidia/ws_Livox` | Livox ROS Driver 2 |
| `/home/nvidia/ws_fastlio2` | FAST-LIO2 |
| `/home/nvidia/unitree_ros2` | Unitree ROS 2 维护依赖 |

正式服务包括 `go2-motion-sender.service`、`go2-console.service`、`go2-console-rosbridge.service`，以及按部署角色安装的 mapping/navigation/gateway/PTP 服务。修改时先部署到版本化 staging 目录，完成零运动验证后再切换 systemd；保留上一版本目录和 unit 文件用于回滚。

## 9. 允许的零运动检查

```bash
bash scripts/check_system.sh
python3 scripts/map_bundle.py validate maps
python3 -m pytest -q test/interface
python3 -m pytest -q src/Go2_control_gateway/test
python3 -m pytest -q src/Go2_web_console/test
ros2 topic hz /odom
ros2 topic hz /scan
ros2 topic hz /map_to_odom
ros2 run tf2_ros tf2_echo map base_link
systemctl is-active go2-motion-sender.service
ip route get 192.168.123.18
ip route get 192.168.123.161
ip route get 192.168.1.158
```

首次物理测试按“急停/复位验证 → 低速原地检查 → 0.5～1 m 短目标”顺序进行，并由现场人员保持急停能力。

## 10. 检查清单

上电后：

- 三张网卡地址和路由正确；控制网卡有载波。
- 系统时间有效；PTP 如启用则状态正常。
- 地图 Manifest 校验通过。
- `/odom`、`/scan`、`/map_to_odom` 持续且时间戳新鲜。
- `map -> odom -> base_link` 可查询且无剧烈跳变。
- Nav2 lifecycle active，网关 ACK 新鲜，急停未锁存。

提交前：

- 未提交密码、密钥、构建目录、日志、历史大地图或设备数据。
- 接口、地图和相关包测试通过。
- 修改了 topic、frame、端口、服务或 API 时，同步更新文档和契约测试。
- 没有新增直接 DDS 运动路径或重复 TF/map_server 所有者。

## 11. 禁止事项

- 不要把 `eth0` 或 `eth1` 设置为默认路由。
- 不要让 Jetson 正常运行路径直接控制 Unitree DDS。
- 不要同时运行 UDP sender 和直接 DDS sender。
- 不要绕过急停、租约、ACK、watchdog 或定位新鲜度门禁。
- 不要在导航运行时调用 FAST-LIO2 `/map_save` 覆盖当前地图。
- 不要只替换地图包中的一个文件。
- 不要用浏览器端校验代替后端安全校验。
- 不要在无人监护或未授权时执行运动测试。
