cmake_minimum_required(VERSION 3.20.0)

find_package(Zephyr HINTS $ENV{ZEPHYR_BASE})

project(humid_zephyr)

# Enable GNU STD support for Matter to use
include(${ZEPHYR_CONNECTEDHOMEIP_MODULE_DIR}/config/nrfconnect/app/enable-gnu-std.cmake)

# Matter data model generation
include(${ZEPHYR_CONNECTEDHOMEIP_MODULE_DIR}/src/app/chip_data_model.cmake)

target_include_directories(app PRIVATE
    src
    src/zap-generated
)

target_sources(app PRIVATE
    src/main.cpp
    src/app_task.cpp
    src/identify_stub.cpp
    src/sht4x.cpp
    src/commissioning_window.cpp
)

target_include_directories(matter-data-model PUBLIC
    src
)

chip_configure_data_model(app
    BYPASS_IDL
    GEN_DIR src/zap-generated
    ZAP_FILE ${CMAKE_CURRENT_SOURCE_DIR}/src/sensor.zap
)
