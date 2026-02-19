cmake_minimum_required(VERSION 3.20.0)

# Custom board definitions in SW/boards/ (pass -DBOARD_ROOT=.. or set via module)
list(APPEND BOARD_ROOT ${CMAKE_CURRENT_SOURCE_DIR}/..)

# DT bindings for FDC1004
list(APPEND DTS_ROOT ${CMAKE_CURRENT_SOURCE_DIR})

# Out-of-tree FDC1004 driver
list(APPEND ZEPHYR_EXTRA_MODULES ${CMAKE_CURRENT_SOURCE_DIR}/drivers)

find_package(Zephyr HINTS $ENV{ZEPHYR_BASE})

project(soil_sensor)

option(TIDY "Run clang-tidy during build" OFF)
if(TIDY)
  set_target_properties(app PROPERTIES
    C_CLANG_TIDY "clang-tidy"
    CXX_CLANG_TIDY "clang-tidy"
  )
endif()

target_sources(app PRIVATE
    src/main.c
)
