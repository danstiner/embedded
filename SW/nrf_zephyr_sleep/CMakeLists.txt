cmake_minimum_required(VERSION 3.20.0)

find_package(Zephyr HINTS $ENV{ZEPHYR_BASE})

project(nrf54_soil)

# Enable GNU STD support for Matter to use
include(${ZEPHYR_CONNECTEDHOMEIP_MODULE_DIR}/config/nrfconnect/app/enable-gnu-std.cmake)

# Matter data model generation
include(${ZEPHYR_CONNECTEDHOMEIP_MODULE_DIR}/src/app/chip_data_model.cmake)

target_include_directories(app PRIVATE
    src
)

target_sources(app PRIVATE
    src/main.cpp
    src/retained.cpp
)
