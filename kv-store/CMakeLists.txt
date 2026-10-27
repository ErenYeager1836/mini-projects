cmake_minimum_required(VERSION 3.16)
project(kv-store VERSION 1.0.0 LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

if(MSVC)
    add_compile_options(/W4 /permissive- /utf-8)
else()
    add_compile_options(-Wall -Wextra -Wpedantic -O2)
endif()

include_directories(include)

# Core library shared across server, client, and tests
add_library(kv_core STATIC
    src/aof.cpp
    src/kv_store.cpp
    src/kv_protocol.cpp
    src/kv_server.cpp
    src/net_utils.cpp
)

if(WIN32)
    target_link_libraries(kv_core PUBLIC Ws2_32)
else()
    target_link_libraries(kv_core PUBLIC pthread)
endif()

# Server executable
add_executable(kv_server src/main_server.cpp)
target_link_libraries(kv_server PRIVATE kv_core)

# Client executable
add_executable(kv_client src/main_client.cpp)
target_link_libraries(kv_client PRIVATE kv_core)

# Automated unit & integration tests
enable_testing()
add_executable(kv_tests tests/test_kv_store.cpp)
target_link_libraries(kv_tests PRIVATE kv_core)

add_test(NAME kv_tests COMMAND kv_tests)
