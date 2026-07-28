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
  add_library(go2_gateway_core src/gateway_core.cpp)
  target_include_directories(go2_gateway_core PUBLIC include)
  target_compile_options(go2_gateway_core PRIVATE -Wall -Wextra -Wpedantic)

  add_executable(gateway_core_test test/gateway_core_test.cpp)
  target_link_libraries(gateway_core_test PRIVATE go2_gateway_core)
  target_compile_options(gateway_core_test PRIVATE -Wall -Wextra -Wpedantic)
  add_test(NAME gateway_core_test COMMAND gateway_core_test)
endif()
