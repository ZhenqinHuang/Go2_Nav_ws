cmake_minimum_required(VERSION 3.16)
project(pcd_to_map VERSION 0.1.0 LANGUAGES CXX)

if(NOT CMAKE_CXX_STANDARD)
  set(CMAKE_CXX_STANDARD 17)
endif()

find_package(ament_cmake REQUIRED)
find_package(rclcpp REQUIRED)
find_package(nav_msgs REQUIRED)
find_package(PCL REQUIRED COMPONENTS common io filters)

include_directories(${PCL_INCLUDE_DIRS})
link_directories(${PCL_LIBRARY_DIRS})
add_definitions(${PCL_DEFINITIONS})

add_executable(pcd_to_occupancy src/pcd_to_occupancy.cpp)
ament_target_dependencies(pcd_to_occupancy rclcpp nav_msgs)
target_link_libraries(pcd_to_occupancy ${PCL_LIBRARIES})

install(TARGETS
  pcd_to_occupancy
  DESTINATION lib/${PROJECT_NAME}
)

install(DIRECTORY launch config
  DESTINATION share/${PROJECT_NAME}
)

ament_package()
