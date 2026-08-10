# ROS 2 接口契约

## 1. 运动网关接口

| 方向 | 接口 | 类型 | 用途 |
|---|---|---|---|
| 发布 | `/go2/manual_cmd_vel` | `geometry_msgs/msg/Twist` | 人工速度 |
| 订阅 | `/go2_cmd_vel_gateway/status` | `std_msgs/msg/String` | ACK 和网关状态 |
| 调用 | `/go2_cmd_vel_gateway/stand_up` | `std_srvs/srv/Trigger` | 站立 |
| 调用 | `/go2_cmd_vel_gateway/stand_down` | `std_srvs/srv/Trigger` | 趴下 |
| 调用 | `/go2_cmd_vel_gateway/emergency_stop` | `std_srvs/srv/Trigger` | 显式停止 |

状态 JSON 使用字段：

- `gateway_link`
- `control_ready`
- `last_ack_age_sec`
- `nav_active`
- `send_hz`
- 可选的 `posture` 和 `battery_soc`

Web 不解析 UDP 帧，也不知道内载 UDP 端口或 Go2 下位机地址。

## 2. Nav2 接口

| 方向 | 接口 | 类型 |
|---|---|---|
| Action | `/navigate_to_pose` | `nav2_msgs/action/NavigateToPose` |
| Action | `/navigate_through_poses` | `nav2_msgs/action/NavigateThroughPoses` |
| 兼容 Action | `/follow_waypoints` | `nav2_msgs/action/FollowWaypoints` |
| 调用 | `/navigate_to_pose/_action/cancel_goal` | `action_msgs/srv/CancelGoal` |
| 订阅 | `/navigate_to_pose/_action/status` | `action_msgs/msg/GoalStatusArray` |
| 发布 | `/initialpose` | `geometry_msgs/msg/PoseWithCovarianceStamped` |

多点导航优先使用当前 Nav2 提供的 `NavigateThroughPoses`，旧版本缺少时回退
到 `FollowWaypoints`。

## 3. 状态接口

| 订阅 | 类型 | 页面用途 |
|---|---|---|
| `/odom` | `nav_msgs/msg/Odometry` | 位置、朝向和速度 |
| `/lowstate` | `unitree_go/msg/LowState` | 电量 |
| `/sportmodestate` | `unitree_go/msg/SportModeState` | 模式和底盘速度 |

Unitree 状态只用于显示；Web 不通过这些 topic 发送运动请求。

## 4. 只读 rosbridge

浏览器经 `/ws/ros` 使用后端代理。代理只允许白名单订阅、取消订阅和必要的
服务查询，不允许浏览器任意 publish、service call 或 action goal。

白名单变更必须同时：

1. 修改 `readonly_rosbridge.py`。
2. 增加对应测试。
3. 评估是否能够绕过 Web HTTP 控制策略。

任何涉及运动的发布都应继续走固定 HTTP API → `ros_adapter.py`，不能通过
rosbridge 旁路。
