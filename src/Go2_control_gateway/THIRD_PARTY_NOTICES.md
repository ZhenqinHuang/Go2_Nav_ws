# Third-Party Notices

## ljh_robot_ros2_web

The navigation visualization frontend in `frontend/` is derived from
[lijinghai/ljh_robot_ros2_web](https://github.com/lijinghai/ljh_robot_ros2_web).

- Original copyright: Copyright (c) 2024 chengyangkj
- Original license: CC BY-NC-SA 4.0
- Source retrieved: 2026-07-28
- Upstream source: https://github.com/lijinghai/ljh_robot_ros2_web

This project modifies the upstream work to:

- replace direct ROS control publishing with authenticated, fixed Go2 control APIs;
- connect visualization through an authenticated, read-only rosbridge proxy;
- add Unitree Go2 Arm/Disarm, gateway, battery, odometry and Nav2 status;
- enforce manual/Nav2 mutual exclusion and fail-closed manual velocity handling;
- correct ROS2 Action status, cancellation and multi-goal behavior;
- package the production frontend with the ROS2 control gateway.

The modified frontend remains available under CC BY-NC-SA 4.0. The Python,
C++ and deployment portions of `Go2_control_gateway` that are not derived from
the frontend remain under Apache-2.0.
