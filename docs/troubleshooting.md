# 故障排查

## Web 在线但不能运动

按 Web 显示的 `block_reason` 处理，不要仅看 systemd 的 `active`：

| 状态 | 检查 |
|---|---|
| `waiting_network` | `ip link show eth0`、`ip addr show eth0`、控制路由 |
| `waiting_gateway_ack` | 内载是否上电、UDP 15000/15001、ACK 年龄 |
| `waiting_localization` | `/map_to_odom`、TF 新鲜度、地图 PCD |
| `nav2_not_ready` | lifecycle 状态和 action server |
| `lease_held` | 当前操作员和租约超时 |
| `estop_latched` | 排除原因后显式复位，不能靠刷新页面解除 |

Go2 断电造成 `eth0` 无载波时，sender 应保持等待而不是无限重启。

## 地图和机器人错位

1. 验证 `maps/map_manifest.yaml`；
2. 确认定位实际加载 `maps/MID360.pcd`；
3. 确认 Nav2 实际加载 `maps/MID360_map.yaml`；
4. 检查是否存在源码目录 PCD 被旧 launch 默认值加载；
5. 检查 `map -> odom -> base_link` 是否有重复 broadcaster。

## 有 topic 但仍未就绪

“Publisher count ≥ 1”不足以证明健康。检查频率和消息时间戳；进程退出后缓存的最后一条网关状态也必须超时失效。

## Nav2 发出速度但底盘不动

依次检查：

1. `/cmd_vel` 是否非零；
2. sender 的 `active_source` 是否为 `navigation`；
3. 是否被急停、定位或 ACK 门禁阻断；
4. UDP 序号和 ACK 是否增长；
5. 内载 gateway 是否执行 watchdog StopMove；
6. `.18` 和 `.161` 是否都经 `eth0`。

不要临时切到外载直连 DDS 来掩盖 UDP 链路故障。

## 时间异常

如果日志时间为 1970、消息时间戳倒退或 TF extrapolation 大量出现，先修复 NTP/系统时间，再检查 PTP。系统时间无效时禁止生成或激活地图。
