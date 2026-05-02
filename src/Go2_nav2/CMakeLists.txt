cmake_minimum_required(VERSION 3.16)
project(go2_nav2)

find_package(ament_cmake REQUIRED)
find_package(rclcpp REQUIRED)
find_package(geometry_msgs REQUIRED)
find_package(nav_msgs REQUIRED)
find_package(unitree_api REQUIRED)

add_executable(go2_cmd_vel_bridge_node
  src/go2_cmd_vel_bridge.cpp
  src/ros2_sport_client.cpp
)

target_include_directories(go2_cmd_vel_bridge_node PRIVATE
  ${CMAKE_CURRENT_SOURCE_DIR}/include
)

ament_target_dependencies(go2_cmd_vel_bridge_node
  rclcpp
  geometry_msgs
  nav_msgs
  unitree_api
)

add_executable(go2_cmd_vel_keyboard_node
  src/go2_cmd_vel_keyboard.cpp
)

ament_target_dependencies(go2_cmd_vel_keyboard_node
  rclcpp
  geometry_msgs
)

install(TARGETS go2_cmd_vel_bridge_node go2_cmd_vel_keyboard_node
  DESTINATION lib/${PROJECT_NAME}
)

install(
  DIRECTORY launch/
  DESTINATION share/${PROJECT_NAME}/launch
  FILES_MATCHING PATTERN "*.py"
)

install(
  DIRECTORY config/
  DESTINATION share/${PROJECT_NAME}/config
  FILES_MATCHING PATTERN "*.yaml" PATTERN "*.xml"
)

install(
  DIRECTORY behavior_trees/
  DESTINATION share/${PROJECT_NAME}/behavior_trees
  FILES_MATCHING PATTERN "*.xml"
)

install(
  DIRECTORY rviz/
  DESTINATION share/${PROJECT_NAME}/rviz
  FILES_MATCHING PATTERN "*.rviz"
)

ament_package()
