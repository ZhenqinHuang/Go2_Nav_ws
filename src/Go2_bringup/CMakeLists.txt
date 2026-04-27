cmake_minimum_required(VERSION 3.8)
project(go2_bringup)

find_package(ament_cmake REQUIRED)

install(PROGRAMS
  go2_nav_start.sh
  check_nav2_ready.sh
  time_sync_start.sh
  DESTINATION lib/${PROJECT_NAME}
)

ament_package()
