cmake_minimum_required(VERSION 3.20.0)

# Add custom board directory (boards live at SW/ level)
list(APPEND BOARD_ROOT ${CMAKE_CURRENT_SOURCE_DIR}/..)

find_package(Zephyr HINTS $ENV{ZEPHYR_BASE})

project(devkit)

target_sources(app PRIVATE
    src/main.cpp
)
