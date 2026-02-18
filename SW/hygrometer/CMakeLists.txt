cmake_minimum_required(VERSION 3.20.0)
list(APPEND BOARD_ROOT ${CMAKE_CURRENT_SOURCE_DIR}/..)
find_package(Zephyr HINTS $ENV{ZEPHYR_BASE})
project(hygrometer)
target_include_directories(app PRIVATE src)
target_sources(app PRIVATE
    src/main.cpp
    src/stcc4.cpp
)
