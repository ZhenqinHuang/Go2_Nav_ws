cmake_minimum_required(VERSION 3.8)
project(go2_time_sync)

find_package(ament_cmake REQUIRED)
find_package(ament_cmake_python REQUIRED)
find_package(rclpy REQUIRED)
find_package(std_msgs REQUIRED)
find_package(diagnostic_msgs REQUIRED)

# 安装 Python 包
ament_python_install_package(${PROJECT_NAME})

# 安装可执行脚本
install(PROGRAMS
  go2_time_sync/ptp_sync_node.py
  go2_time_sync/ptp_monitor_node.py
  DESTINATION lib/${PROJECT_NAME}
)

# 安装 launch 文件
install(DIRECTORY launch/
  DESTINATION share/${PROJECT_NAME}/launch
)

# 安装配置文件
install(DIRECTORY config/
  DESTINATION share/${PROJECT_NAME}/config
)

# 安装脚本
install(PROGRAMS
  scripts/start_ptp_sync.py
  scripts/check_ptp_env.py
  DESTINATION lib/${PROJECT_NAME}
)

ament_package()
