cmake_minimum_required(VERSION 3.16)
project(go2_cmd_gateway LANGUAGES CXX)

option(GO2_GATEWAY_PROTOCOL_ONLY "Build only the protocol codec test" OFF)
option(GO2_GATEWAY_BUILD_SDK "Build the Unitree SDK adapter" OFF)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

enable_testing()

add_executable(protocol_test test/protocol_test.cpp)
target_include_directories(protocol_test PRIVATE include)
target_compile_options(protocol_test PRIVATE -Wall -Wextra -Wpedantic)
add_test(NAME protocol_test COMMAND protocol_test)

if(NOT GO2_GATEWAY_PROTOCOL_ONLY)
  find_package(Threads REQUIRED)

  add_library(go2_gateway_core src/gateway_core.cpp)
  target_include_directories(go2_gateway_core PUBLIC include)
  target_compile_options(go2_gateway_core PRIVATE -Wall -Wextra -Wpedantic)

  add_executable(gateway_core_test test/gateway_core_test.cpp)
  target_link_libraries(gateway_core_test PRIVATE go2_gateway_core)
  target_compile_options(gateway_core_test PRIVATE -Wall -Wextra -Wpedantic)
  add_test(NAME gateway_core_test COMMAND gateway_core_test)

  add_executable(
    go2_cmd_gateway
    src/main.cpp
    src/dry_run_sport_api.cpp
  )
  target_link_libraries(
    go2_cmd_gateway
    PRIVATE go2_gateway_core Threads::Threads
  )
  target_compile_options(
    go2_cmd_gateway
    PRIVATE -Wall -Wextra -Wpedantic
  )

  if(GO2_GATEWAY_BUILD_SDK)
    find_path(
      UNITREE_SDK_INCLUDE_DIR
      unitree/robot/go2/sport/sport_client.hpp
      PATHS /usr/local/include
      REQUIRED
    )
    find_library(
      UNITREE_GO2_SDK_LIBRARY
      NAMES unitree_go2_sdk
      PATHS /usr/local/lib
      REQUIRED
    )
    target_sources(go2_cmd_gateway PRIVATE src/unitree_sport_api.cpp)
    target_include_directories(
      go2_cmd_gateway PRIVATE ${UNITREE_SDK_INCLUDE_DIR}
    )
    target_link_libraries(
      go2_cmd_gateway PRIVATE ${UNITREE_GO2_SDK_LIBRARY}
    )
    target_compile_definitions(
      go2_cmd_gateway PRIVATE GO2_GATEWAY_HAS_UNITREE_SDK=1
    )
  else()
    target_compile_definitions(
      go2_cmd_gateway PRIVATE GO2_GATEWAY_HAS_UNITREE_SDK=0
    )
  endif()
endif()
