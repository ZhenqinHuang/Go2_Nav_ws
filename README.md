# Go2 Navigation Workspace

Unitree Go2 的建图、三维定位、Nav2 导航、安全运动网关和局域网 Web 控制工程。

当前正式控制架构：

```text
MID360S -> FAST-LIO2 -> ICP map->odom + /odom + /scan -> Nav2
Nav2 /cmd_vel 或 Web 手动速度
  -> Jetson UDP sender
  -> 内载安全 gateway
  -> Unitree SportClient
  -> Go2
```

默认不允许 Jetson 直接通过 Unitree DDS 控制底盘。外载直连 DDS 只作为显式维护模式保留，并且不能与 UDP 后端同时运行。

## 快速入口

| 操作 | 命令 |
|---|---|
| 系统检查 | `bash scripts/check_system.sh` |
| 启动建图 | `bash scripts/start_mapping.sh` |
| 启动导航 | `bash scripts/start_navigation.sh` |
| 停止本项目进程 | `bash scripts/stop_all.sh` |
| Web 控制台 | `http://192.168.0.101:8080` |

根目录脚本是稳定入口，具体 ROS 参数仍保存在各功能包中。

## 仓库结构

```text
Go2_Nav_ws/
├── docs/                  架构、部署、运维和实施记录
├── maps/                  当前唯一生效的地图包；archive 仅存历史地图
├── scripts/               面向操作者的稳定入口
├── src/
│   ├── Go2_bringup/       统一启动、检查与系统编排
│   ├── Go2_Slam/          FAST-LIO2 建图接入说明与工程约定
│   ├── Go2_localization/  ICP 定位和 odom TF
│   ├── Go2_perception/    点云转 scan、PCD 转二维地图
│   ├── Go2_nav2/          Nav2、DWB、RPP 和行为树
│   ├── Go2_control_gateway/ 外载 sender 与内载 gateway
│   ├── Go2_web_console/   正式局域网 Web 控制台
│   ├── Go2_web_bridge/    可选云端和语音功能
│   └── Go2_time_sync/     NTP/PTP 时间同步
└── test/                  接口、安全和零运动冒烟测试入口
```

Livox 驱动和 FAST-LIO2 不复制进本仓库，默认分别由 `~/ws_Livox` 和 `~/ws_fastlio2` 提供；本仓库只负责配置约定、启动编排和下游导航链路。

## 地图

当前生效地图只有一套：

```text
maps/MID360.pcd
maps/MID360_map.pgm
maps/MID360_map.yaml
maps/map_manifest.yaml
```

PCD、PGM 和 YAML 必须来自同一次 FAST-LIO2 建图。三维定位只读取根目录 PCD，Nav2 只读取根目录 YAML。切换地图前必须通过 Manifest 校验。

## 控制器与附加功能

- Nav2 默认使用 DWB，设置 `CONTROLLER=rpp` 可选择 RPP；
- Web 控制台保留手动控制、站立、趴下、急停、单点和多点导航；
- PTP 配置保留为可选时间同步能力，正常系统时间仍先由 NTP 保证；
- `Go2_web_bridge` 继续作为可选云端 WebSocket/TTS 功能，不属于安全运动主链路。

## 文档

- [系统架构](docs/architecture.md)
- [部署与网络](docs/deployment.md)
- [地图工作流](docs/mapping.md)
- [启动与操作](docs/operations.md)
- [故障排查](docs/troubleshooting.md)
- [Jetson 后续开发边界](docs/jetson-development-guardrails.md)
- [2026-08-10 工作日志](docs/work-log-2026-08-10.md)
- [已确认的整合设计](docs/plans/2026-08-10-go2-navigation-web-integration-design.md)

## 安全说明

开发和无运动检查不会发送非零速度或姿态命令。实机验证前必须确认 Go2 控制专网上电、UDP ACK 新鲜、定位稳定、急停可用，并先执行 0.5～1 m 的短距离测试。
