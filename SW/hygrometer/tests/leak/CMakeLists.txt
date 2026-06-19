# Unit tests for the resistive leak sensor driver (src/sensor/leak.cpp), run on
# native_sim with the emulated ADC/GPIO drivers.
cmake_minimum_required(VERSION 3.20.0)

# Resolve the out-of-tree "local,leak-sensor" binding under hygrometer/dts/bindings.
set(DTS_ROOT ${CMAKE_CURRENT_SOURCE_DIR}/../..)

find_package(Zephyr REQUIRED HINTS $ENV{ZEPHYR_BASE})
project(leak_test)

target_include_directories(app PRIVATE
  ${CMAKE_CURRENT_SOURCE_DIR}/../../src
  ${CMAKE_CURRENT_SOURCE_DIR}/../../src/sensor
)

# Compile the real driver under test (it needs only leak.h / leak_model.h /
# sensor_reading.h — no sensor_reading.cpp).
target_sources(app PRIVATE
  src/main.cpp
  ${CMAKE_CURRENT_SOURCE_DIR}/../../src/sensor/leak.cpp
)
