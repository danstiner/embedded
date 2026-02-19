cmake_minimum_required(VERSION 3.20.0)

# Add custom board directory (boards live at SW/ level)
list(APPEND BOARD_ROOT ${CMAKE_CURRENT_SOURCE_DIR}/..)

find_package(Zephyr HINTS $ENV{ZEPHYR_BASE})

project(devkit)

option(TIDY "Run clang-tidy during build" OFF)
if(TIDY)
  set_target_properties(app PROPERTIES
    C_CLANG_TIDY "clang-tidy"
    CXX_CLANG_TIDY "clang-tidy"
  )
endif()

target_sources(app PRIVATE
    src/main.cpp
)
