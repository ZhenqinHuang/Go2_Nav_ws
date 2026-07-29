cmake_minimum_required(VERSION 3.16)
project(go2_nav2)

find_package(ament_cmake REQUIRED)
find_package(rclcpp REQUIRED)
find_package(geometry_msgs REQUIRED)
find_package(nav_msgs REQUIRED)
find_package(unitree_api REQUIRED)

if(BUILD_TESTING)
  enable_testing()

  add_executable(sport_request_test
    test/sport_request_test.cpp
  )
  target_include_directories(sport_request_test PRIVATE
    ${CMAKE_CURRENT_SOURCE_DIR}/include
  )
  ament_target_dependencies(sport_request_test
    unitree_api
  )
  add_test(NAME sport_request_test COMMAND sport_request_test)
endif()

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

install(PROGRAMS
  scripts/nav_tts_announcer.py
  DESTINATION lib/${PROJECT_NAME}
)

# 注意：colcon `--symlink-install` 仅对 install(FILES ...) 生效，
# 对 install(DIRECTORY ...) 仍是真实拷贝。
# 改用 file(GLOB) + install(FILES ...) 让 yaml/xml/rviz 文件以符号链接方式
# 安装到 install/，调参后无需重新 colcon build 即可生效。
file(GLOB LAUNCH_FILES   CONFIGURE_DEPENDS "${CMAKE_CURRENT_SOURCE_DIR}/launch/*.py")
file(GLOB CONFIG_YAMLS   CONFIGURE_DEPENDS "${CMAKE_CURRENT_SOURCE_DIR}/config/*.yaml")
file(GLOB CONFIG_XMLS    CONFIGURE_DEPENDS "${CMAKE_CURRENT_SOURCE_DIR}/config/*.xml")
file(GLOB BT_XMLS        CONFIGURE_DEPENDS "${CMAKE_CURRENT_SOURCE_DIR}/behavior_trees/*.xml")
file(GLOB RVIZ_FILES     CONFIGURE_DEPENDS "${CMAKE_CURRENT_SOURCE_DIR}/rviz/*.rviz")

install(FILES ${LAUNCH_FILES} DESTINATION share/${PROJECT_NAME}/launch)
install(FILES ${CONFIG_YAMLS} DESTINATION share/${PROJECT_NAME}/config)
install(FILES ${CONFIG_XMLS}  DESTINATION share/${PROJECT_NAME}/config)
install(FILES ${BT_XMLS}      DESTINATION share/${PROJECT_NAME}/behavior_trees)
install(FILES ${RVIZ_FILES}   DESTINATION share/${PROJECT_NAME}/rviz)

ament_package()
