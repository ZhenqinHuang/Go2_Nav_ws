# 系统架构

## 数据流

```text
Livox MID360S
  -> FAST-LIO2
     -> /Odometry -> odom_tf_bridge -> /odom + odom->base_link
     -> /cloud_registered -> ICP localization -> map->odom
     -> /cloud_registered_body -> go2_pc2scan -> /scan

maps/MID360_map.yaml -> Nav2 map_server -> /map
/map + /odom + /scan + map->odom->base_link -> Nav2 -> /cmd_vel
```

完整 TF 只有一条所有者明确的链：

```text
map -> odom -> base_link
```

`fast_lio_localization_ros2` 负责 `map -> odom`，`odom_tf_bridge` 负责 `odom -> base_link`。其他节点不得重复广播这两个变换。

## 运动控制边界

```text
Nav2 /cmd_vel          Web /go2/manual_cmd_vel
       \                    /
        外载控制仲裁与 UDP sender
             -> 内载 go2_cmd_gateway
             -> Unitree SportClient
             -> Go2
```

外载负责控制源仲裁、状态聚合、ACK 新鲜度和急停锁存。内载再次执行协议校验、限速、watchdog 和急停锁存。任一端状态失效都归零并阻断运动。

## 运行阶段

1. 时间与网络就绪；
2. Livox 与 FAST-LIO2；
3. 里程计、ICP 定位和 LaserScan；
4. TF/topic 新鲜度检查；
5. UDP 网关与 ACK；
6. Nav2 lifecycle active；
7. Web 控制和任务下发。

感知和 Web 只读状态可以在控制专网断电时运行，但运动状态必须显示为不可用。

## 模块职责

| 目录 | 职责 |
|---|---|
| `src/Go2_bringup` | ROS 启动编排与兼容入口 |
| `src/Go2_Slam` | FAST-LIO2 建图说明与配置 |
| `src/Go2_localization` | 三维定位与里程计 TF |
| `src/Go2_perception` | 点云过滤、LaserScan、PCD 转栅格图 |
| `src/Go2_nav2` | Nav2、DWB/RPP、BT、waypoint |
| `src/Go2_control_gateway` | 外载 sender 与内载安全 gateway |
| `src/Go2_web_console` | 正式局域网控制台 |
| `src/Go2_web_bridge` | 可选云端桥接和 TTS |
| `src/Go2_time_sync` | NTP/PTP 检查和 PTP 工具 |

详细控制与 Web 状态机见 `docs/plans/2026-08-10-go2-navigation-web-integration-design.md`。
