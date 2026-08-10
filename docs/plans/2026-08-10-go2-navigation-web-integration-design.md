# Go2 导航与 Web 控制整合设计

日期：2026-08-10
状态：已确认，进入实施

## 1. 目标

将现有 FAST-LIO2、三维定位、Nav2、Go2 UDP 控制网关和正式 Web 控制台整理为一个可部署、可诊断、默认安全的 ROS 2 工程，同时保留：

- Web 控制；
- 站立和趴下；
- DWB 与 RPP 控制器配置；
- PTP 时间同步；
- PCD 建图、二维地图生成、多点导航等现有能力。

本次不重写已经工作的算法节点，也不改变机器狗正常控制边界。默认运动链路仍为外载 UDP 到内载安全网关，外载直接 DDS 只作为显式维护模式保留。

## 2. 系统边界

### 2.1 网络

| 设备/接口 | 地址 | 职责 |
|---|---:|---|
| Jetson `wlan0` | `192.168.0.101/24` | SSH、Web、默认路由 |
| Jetson `eth0` | `192.168.123.5/24` | Go2 控制专网，无默认网关 |
| Jetson `eth1` | `192.168.1.5/24` | MID360S 专网，无默认网关 |
| 内载 Ubuntu `eth0` | `192.168.123.18/24` | UDP 安全网关 |
| MID360S | `192.168.1.158` | 激光雷达 |
| Go2 下位机 | `192.168.123.161` | Unitree DDS / Sport API |

启动检查必须确认 `.18` 和 `.161` 经 `eth0`，雷达经 `eth1`，默认路由经 `wlan0`。控制专网断电时服务进入“等待网络”状态，不通过 systemd 高频重启。

### 2.2 控制链路

```text
Nav2 /cmd_vel 或 Web /go2/manual_cmd_vel
  -> 外载 go2_cmd_vel_udp_sender（20 Hz）
  -> UDP 192.168.123.5:15001 -> 192.168.123.18:15000
  -> 内载 go2_cmd_gateway
  -> 校验、序号、CRC、限速、ACK、双端 watchdog
  -> Unitree SportClient
  -> Go2 192.168.123.161
```

UDP 是唯一默认控制后端。直接 DDS 模式必须显式选择，并与 UDP 后端互斥。

## 3. 导航 Pipeline

### 3.1 阶段 0：时间与网络

1. 主机时间有效并完成 NTP 校时；
2. PTP 可选启用，用于雷达/主机高精度同步；
3. 检查三张网卡、地址和路由；
4. 控制专网未上电时允许感知和 Web 只读功能启动，但禁止运动。

### 3.2 阶段 1：地图包

一次 FAST-LIO2 建图只产生一个可激活地图包：

```text
maps/MID360.pcd
maps/MID360_map.pgm
maps/MID360_map.yaml
maps/map_manifest.yaml
```

PCD 用于三维 ICP 全局定位，PGM/YAML 用于 Nav2。Manifest 记录生成时间、来源、坐标原点、分辨率、文件大小和 SHA-256。新地图先写入 staging，验证完整后原子切换；旧地图移到 `maps/archive/<timestamp>/`。

源码包中不再保存第二份默认 PCD，避免定位加载旧地图。

### 3.3 阶段 2：实时感知与里程计

```text
Livox Driver
  -> FAST-LIO2
     -> /Odometry
     -> /cloud_registered
     -> /cloud_registered_body
```

`odom_tf_bridge` 将 FAST-LIO2 输出转换为 `/odom` 与 `odom -> base_link`。导航运行时不调用 `/map_save`。

### 3.4 阶段 3：定位与障碍物

```text
/cloud_registered + maps/MID360.pcd
  -> fast_lio_localization_ros2
  -> map -> odom

/cloud_registered_body
  -> go2_pc2scan
  -> /scan (base_link)
```

最终 TF 为 `map -> odom -> base_link`。就绪检查不仅验证 topic 存在，还验证时间戳新鲜度、频率和 TF 跳变。

### 3.5 阶段 4：Nav2 与控制器

Nav2 自己启动唯一的 map_server。DWB 为默认控制器，RPP 保留为可选参数集，二者共用统一地图、footprint、速度限制和 topic 命名。

导航目标必须经过以下门禁：

- 地图包完整；
- `/odom`、`/scan`、`/map_to_odom` 新鲜；
- `map -> base_link` 可查询且稳定；
- Nav2 lifecycle active；
- UDP ACK 新鲜；
- 控制网关 ready；
- 急停未锁存。

## 4. Web 控制设计

正式控制台源码纳入 `src/Go2_web_console`，继续以 systemd 提供 `http://192.168.0.101:8080`。页面布局和视觉风格不重做，重点调整安全、状态、地图导航和接口一致性。

### 4.1 统一接口

控制接口统一到：

```text
POST /api/control/acquire
POST /api/control/release
POST /api/control/manual
POST /api/control/posture          # stand | lie
POST /api/control/emergency-stop
POST /api/control/reset-emergency-stop
```

所有响应统一为：

```json
{"ok": true, "code": "ok", "message": "...", "data": {}}
```

错误码、Web 状态和 ROS 网关状态使用同一组字段。浏览器 rosbridge 保持只读白名单，不能绕过后端发布运动指令。

### 4.2 姿态与急停

- 只保留站立和趴下，删除 recovery-stand；
- Web 不再直接发布 `/api/sport/request`；
- 站立/趴下通过外载 sender 和内载 gateway 的受控离散命令执行；
- 姿态动作要求导航停止、速度为零、网关健康，趴下要求二次确认；
- 动作以内部网关 ACK 为成功依据，而不是以 HTTP 请求发送成功为依据；
- 急停对所有已登录用户可用，不要求控制租约；
- 急停取消 Nav2、清空手动速度，并在外载和内载两端锁存；
- 复位要求持有租约、导航已停止、速度为零、网关和定位健康；
- 锁存期间新的 `/cmd_vel` 不能恢复运动。

### 4.3 状态机

```text
offline
 -> waiting_network
 -> waiting_gateway_ack
 -> waiting_localization
 -> ready
 -> manual_active | navigation_active
 -> estop_latched
```

状态必须给出具体阻断原因，包括：网卡无载波、缺少地址、控制路由错误、ACK 超时、定位超时、Nav2 未 active、租约被占用和急停锁存。旧状态必须按时间戳失效，不能一直显示“在线”。

统一状态至少包含：

```text
gateway_link, ack_age, control_ready, localization_ready,
nav_active, active_source, estop_latched, posture,
block_reason, map_id, navigation_phase
```

### 4.4 地图导航

- Web 只允许选择完整且校验通过的地图包；
- 地图目标在发送前预览并确认；
- 障碍栅格内目标拒绝，未知区目标警告；
- 单点、多点和取消操作使用一致的导航接口；
- 取消导航作为安全动作，对所有已登录用户开放；
- 设置初始位姿前停止导航，并等待新的定位/TF 证据，替代固定 sleep；
- 停止导航时先取消目标并确认速度归零，再停止进程。

## 5. 项目结构

```text
Go2_Nav_ws/
├── README.md
├── docs/
│   ├── architecture.md
│   ├── deployment.md
│   ├── mapping.md
│   ├── operations.md
│   ├── troubleshooting.md
│   └── plans/
├── maps/
│   ├── MID360.pcd
│   ├── MID360_map.pgm
│   ├── MID360_map.yaml
│   ├── map_manifest.yaml
│   └── archive/
├── scripts/
│   ├── install.sh
│   ├── start_mapping.sh
│   ├── start_navigation.sh
│   ├── check_system.sh
│   └── stop_all.sh
├── src/
│   ├── Go2_bringup/
│   ├── Go2_Slam/
│   ├── Go2_localization/
│   ├── Go2_perception/
│   ├── Go2_nav2/
│   ├── Go2_control_gateway/
│   ├── Go2_web_console/
│   ├── Go2_web_bridge/
│   └── Go2_time_sync/
└── test/
    ├── interface/
    ├── safety/
    └── smoke/
```

现有 ROS 包名尽量不改，避免无收益的大规模引用迁移。根脚本只做稳定入口，具体参数仍归各 ROS 包所有。

## 6. 启动与故障处理

统一启动器采用条件等待而非固定 sleep：

1. 时间和网络；
2. Livox 与 FAST-LIO2；
3. odom bridge、ICP 定位与 pc2scan；
4. TF/topic 新鲜度门禁；
5. 控制网关与 ACK；
6. Nav2 lifecycle；
7. Web 控制台。

任一运动相关条件失效时 fail closed：发送零速度、禁止新目标和手动速度、显示准确原因。Web 进程退出不终止已运行导航，但租约和手动控制立即失效；导航或定位退出时 sender 归零。

## 7. 验证范围

先完成不运动验证：

- Python 单元测试：租约、超时、速度限制、状态失效、急停锁存和接口响应；
- C++/协议测试：CRC、序号、ACK、重复包、姿态命令、watchdog；
- 前端测试和 production build；
- ROS 2 参数、launch、topic 和 TF 契约检查；
- 地图 Manifest 和哈希校验；
- shell 静态检查；
- Jetson 上不发送非零速度的 smoke test。

机器狗上电后再执行受控验证：确认路由与 gateway，先急停/复位验证，再发送 0.5～1 m 短距离导航目标。未完成该步骤前不宣称实机闭环已经通过。

## 8. 迁移原则

- 以机器人当前正式 Web 控制台和新版 UDP 网关为迁移源；
- 保留工作区已有未提交修改，不覆盖未知用户改动；
- 先复制和验证，再切换 systemd 服务；
- 删除只针对已确认无引用的临时文件、备份和重复地图；
- 大体积历史地图默认归档且不进入源码版本库。
