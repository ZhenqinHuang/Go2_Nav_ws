cmake_minimum_required(VERSION 3.8)
project(go2_bringup)

find_package(ament_cmake REQUIRED)

install(PROGRAMS
  check_system.sh
  go2_env.sh
  run_keyboard_teleop.sh
  run_web_bridge.sh
  start_mapping.sh
  start_navigation.sh
  stop_all.sh
  time_sync_start.sh
  DESTINATION lib/${PROJECT_NAME}
)

install(DIRECTORY systemd/
  DESTINATION share/${PROJECT_NAME}/systemd
)

ament_package()

