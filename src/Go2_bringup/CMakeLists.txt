cmake_minimum_required(VERSION 3.8)
project(go2_bringup)

find_package(ament_cmake REQUIRED)

install(PROGRAMS
  check_nav2_ready.sh
  go2_autostart.sh
  go2_nav_start.sh
  run_keyboard_teleop.sh
  run_nav2.sh
  run_robot_web.sh
  run_web_bridge.sh
  time_sync_start.sh
  DESTINATION lib/${PROJECT_NAME}
)

ament_package()

