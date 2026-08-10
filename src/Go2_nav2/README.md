# Go2 Nav2

此包只负责地图、规划、控制、恢复行为、行为树和航点跟随。它发布 `/cmd_vel`，不直接拥有
Unitree DDS 或 UDP 传输。

## 控制器配置

- `controller_server.yaml`：默认 DWB，使用已验证的 Go2 footprint 和速度限制；
- `controller_server_rpp.yaml`：可选 RPP，保持相同 frame、话题、footprint 与安全速度上限；
- `waypoint_follower.yaml`：Web 多点导航所需的 waypoint follower。

```bash
# 推荐：统一入口
CONTROLLER=dwb bash scripts/start_navigation.sh

# 可选 RPP
CONTROLLER=rpp bash scripts/start_navigation.sh
```

直接调试 launch 时：

```bash
ros2 launch go2_nav2 nav2_bringup.launch.py \
  map:=/home/nvidia/Go2_Nav_ws/maps/MID360_map.yaml \
  controller:=dwb use_rviz:=false
```

Web 生成临时控制器参数时可通过 `controller_params_file:=...` 覆盖选中的 profile。

## 启动和地图所有权

`nav2_bringup.launch.py` 启动一个 lifecycle manager，统一管理：

```text
map_server, planner_server, controller_server,
recoveries_server, bt_navigator, waypoint_follower
```

本 launch 是导航期间 `/map` 的唯一 owner。上游 bringup 在启动 Nav2 前等待
`map -> odom -> base_link` 可查询，因此这里不再使用固定延时。

## 控制边界

正式运行时 `/cmd_vel` 由 `go2-motion-sender.service` 转成 UDP，发送到内载安全网关。
旧直连 DDS bridge 默认不构建；只有显式设置 CMake 选项
`GO2_BUILD_DIRECT_DDS_BRIDGE=ON` 才能作为维护工具编译，并且不能与 UDP sender 同时运行。

主要输入为 `/odom`、`/scan` 和 TF；主要接口为 `/navigate_to_pose`、
`/follow_waypoints`、`/plan` 与 `/cmd_vel`。
