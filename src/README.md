# 源码包分层

本目录按职责保留 ROS 2 功能包，根目录 `scripts/` 是唯一推荐的运行入口。

| 层 | 包 | 职责 |
|---|---|---|
| 建图 | `Go2_Slam` | FAST-LIO2 建图说明与参数 |
| 定位 | `Go2_localization` | `/odom`、ICP `map -> odom`、`/localization` |
| 感知 | `Go2_perception` | 点云过滤、`/scan`、PCD 转 2D 地图 |
| 规划 | `Go2_nav2` | map_server、DWB/RPP、BT 与 waypoint follower |
| 安全控制 | `Go2_control_gateway` | 外载 UDP sender、内载 gateway、ACK/watchdog/急停 |
| Web | `Go2_web_console` | 正式 8080 控制台、状态与导航 API |
| 可选接口 | `Go2_web_bridge` | 云端 WebSocket 与 TTS |
| 时间 | `Go2_time_sync` | 可选 PTP 配置与诊断 |
| 编排 | `Go2_bringup` | 有序启动、就绪检查和停止 |

## 正式数据流

```text
MID360S -> FAST-LIO2
  ├─ /Odometry -> odom_tf_bridge -> /odom + odom -> base_link
  ├─ /cloud_registered + maps/MID360.pcd -> ICP -> map -> odom
  └─ /cloud_registered_body -> go2_pc2scan -> /scan

/odom + /scan + map -> odom + maps/MID360_map.yaml
  -> Nav2 -> /cmd_vel
  -> external UDP sender -> internal gateway -> SportClient -> Go2
```

Web 手动速度与 Nav2 `/cmd_vel` 在同一 UDP sender 内互锁。浏览器不能直接发布底盘 DDS 命令。
站立、趴下、急停和复位同样经过网关协议。

## 使用

```bash
cd /home/nvidia/Go2_Nav_ws
bash scripts/install.sh
bash scripts/check_system.sh
bash scripts/start_navigation.sh
```

地图只存放在仓库根目录 `maps/`；源码包不携带第二份 PCD/PGM。详细操作见根目录
[`README.md`](../README.md) 和 [`docs/`](../docs/)。
