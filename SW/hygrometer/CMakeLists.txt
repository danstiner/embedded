cmake_minimum_required(VERSION 3.20.0)
list(APPEND BOARD_ROOT ${CMAKE_CURRENT_SOURCE_DIR}/..)
find_package(Zephyr HINTS $ENV{ZEPHYR_BASE})
project(hygrometer)
option(TIDY "Run clang-tidy during build" OFF)
if(TIDY)
  set_target_properties(app PROPERTIES
    C_CLANG_TIDY "clang-tidy"
    CXX_CLANG_TIDY "clang-tidy"
  )
endif()

# Define PINCTRL_STATE_OFF so the "off" pinctrl-names entry compiles.
# Must be visible to both our code and the I2C driver (which instantiates pinctrl).
zephyr_compile_definitions(PINCTRL_STATE_OFF=PINCTRL_STATE_PRIV_START)

target_include_directories(app PRIVATE src src/sensor)

# Shared sensor module (always built)
target_sources(app PRIVATE
  src/sensor/sensor_reading.cpp
  src/sensor/stcc4.cpp
)

if(CONFIG_APP_USE_MATTER)
  include(${ZEPHYR_CONNECTEDHOMEIP_MODULE_DIR}/config/nrfconnect/app/enable-gnu-std.cmake)
  include(${ZEPHYR_NRF_MODULE_DIR}/samples/matter/common/cmake/source_common.cmake)
  include(${ZEPHYR_NRF_MODULE_DIR}/samples/matter/common/cmake/data_model.cmake)
  include(${ZEPHYR_NRF_MODULE_DIR}/samples/matter/common/cmake/zap_helpers.cmake)
  ncs_get_zap_parent_dir(ZAP_PARENT_DIR)
  target_include_directories(app PRIVATE ${ZAP_PARENT_DIR})
  target_sources(app PRIVATE
    src/matter/main.cpp
    src/matter/app_task.cpp
  )
  ncs_configure_data_model()
else()
  target_sources(app PRIVATE
    src/bthome/main.cpp
    src/bthome/led_svc.cpp
    src/bthome/co2_cal_svc.cpp
  )
endif()
