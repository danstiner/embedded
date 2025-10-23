# TODO - nRF54 Soil Moisture Sensor

This document tracks improvements, refactoring ideas, and future development tasks for the nRF54 soil moisture sensor project. Remove once complete.

---

* Do temp/battery checks as part of a single periodic wakeup to check sensors
* Only check temperature if we successfully did a deep sleep, not on first wakeup
* Add matter support, report temperature & battery voltage over matter

---

## Current Status: Step 1 - Ultra-Low Power Monitoring

This step implements:
- ADC-based battery voltage measurement with 22MΩ voltage divider (95nA leakage)
- Internal die temperature sensor monitoring
- Battery state detection (Critical/Low/Good/Full)
- Automatic deep sleep on critical battery
- **System OFF mode with GRTC wakeup** for <5µA sleep current
- Retained RAM preserves state across sleep cycles
- LED status indicators

---

### **Add .clang-format**
Copy Nordic's .clang-format for consistent code style.

---

### **Reduce C++ Bloat (Post-Matter Integration)**
After converting to C++ for Matter support, investigate size optimizations:
- Current: 87KB flash, 20KB RAM (vs 46KB/11KB in C release build)
- Compiler flags: -fno-rtti, -fno-exceptions (may already be set)
- Link-time optimization (LTO)
- Function/data sections with --gc-sections
- Consider selective C++ usage (only where needed for Matter API)
- Baseline: C build was 46KB ROM / 11KB RAM
- Target: Keep under 100KB ROM / 25KB RAM even with Matter

---

## Low Priority / Future Enhancements

### **Add Retained Memory for Diagnostics**
Add crash logging with retained RAM for debugging crashes without debugger and log retention across reboots.

---

### **Add Sysbuild Support**
Add sysbuild configuration for MCUboot bootloader integration, multi-image builds, partition management, and OTA update capability.

---

### **Implement DFU Capability**
Add Device Firmware Update support with MCUboot secure bootloader, DFU over BLE SMP, and partition manager configuration.

---

### **Add NVS for Persistent Settings**
Add non-volatile storage for calibration data, last known battery state, and configuration persistence.

---

## Matter Protocol Implementation Plan

### Overview
Implement Matter protocol support to create a Thread-networked temperature sensor that can be commissioned and controlled via Matter controllers (Apple Home, Google Home, etc.).

### Phase 2.1: Basic Matter Setup

#### Step 1: Project Configuration
**Files to create/modify:**
- `Kconfig` - Add Matter-specific options
- `prj.conf` - Enable Matter and Thread
- `Kconfig.sysbuild` - Multi-image build configuration
- `sysbuild.conf` - Bootloader configuration

**Key configs to add:**
```kconfig
CONFIG_CHIP=y
CONFIG_CHIP_PROJECT_CONFIG="src/chip_project_config.h"
CONFIG_CHIP_DEVICE_PRODUCT_ID=32781  # 0x800D (Temperature sensor example)
CONFIG_CHIP_DEVICE_TYPE=770          # 0x0302 (Temperature sensor)

# Enable Thread networking
CONFIG_NET_L2_OPENTHREAD=y
CONFIG_OPENTHREAD_MTD=y              # Minimal Thread Device
CONFIG_OPENTHREAD_NORDIC_LIBRARY_MTD=y

# Enable BLE for commissioning
CONFIG_BT=y
CONFIG_CHIP_ENABLE_PAIRING_AUTOSTART=y
CONFIG_CHIP_BLE_EXT_ADVERTISING=y

# Enable Matter shell for debugging
CONFIG_CHIP_LIB_SHELL=y
```

#### Step 2: Data Model (ZAP Configuration)
**Files to create:**
- `src/temperature_sensor.zap` - Matter data model definition
- `src/chip_project_config.h` - Project-specific CHIP config

**Clusters to implement:**
1. **Temperature Measurement Cluster (0x0402)**
   - MeasuredValue attribute (die temperature in 0.01°C units)
   - MinMeasuredValue / MaxMeasuredValue

2. **Power Source Cluster (0x002F)**
   - Status (battery)
   - BatPercentRemaining
   - BatChargeLevel (OK/Warning/Critical)

3. **Identify Cluster (0x0003)** - Required by Matter
   - Identify command (could blink LED or log)

4. **Descriptor Cluster (0x001D)** - Auto-generated
   - Device type list
   - Server list
   - Parts list

#### Step 3: Application Task Structure
**Files to create:**
- `src/app_task.cpp` - Main application task (C++)
- `src/app_task.h` - Application task header
- `src/temperature_sensor.cpp` - Temperature sensor driver
- `src/temperature_sensor.h` - Temperature sensor header

**Application flow:**
```
main()
  ├─> Initialize Matter stack
  ├─> Start Thread network
  ├─> Initialize sensors (die temp, battery)
  ├─> Start periodic sensor reading task
  └─> Start Matter event loop

Sensor Task (1 minute interval):
  ├─> Read die temperature
  ├─> Read battery voltage
  ├─> Update Matter attributes
  └─> Report to subscribers
```

#### Step 4: Temperature Sensor Integration
**Use nRF54L15 internal die temperature sensor:**

Device tree addition:
```dts
&temp {
    status = "okay";
};
```

Code:
```c
#include <zephyr/drivers/sensor.h>

const struct device *temp_dev = DEVICE_DT_GET(DT_NODELABEL(temp));

int read_die_temperature(int16_t *temp_celsius_x100) {
    struct sensor_value val;

    sensor_sample_fetch(temp_dev);
    sensor_channel_get(temp_dev, SENSOR_CHAN_DIE_TEMP, &val);

    // Convert to 0.01°C units for Matter
    *temp_celsius_x100 = (val.val1 * 100) + (val.val2 / 10000);
    return 0;
}
```

#### Step 5: Matter Attribute Updates
**In `src/app_task.cpp`:**
```cpp
#include <app-common/zap-generated/attributes/Accessors.h>

using namespace chip;
using namespace chip::app::Clusters;

void UpdateTemperature(int16_t temp_celsius_x100) {
    // Update Matter Temperature Measurement cluster
    TemperatureMeasurement::Attributes::MeasuredValue::Set(
        /* endpoint */ 1,
        /* value */ temp_celsius_x100
    );
}

void UpdateBattery(uint8_t percent, uint8_t level) {
    // Update Matter Power Source cluster
    PowerSource::Attributes::BatPercentRemaining::Set(
        /* endpoint */ 1,
        /* value */ percent * 2  // Matter uses 0-200 scale
    );

    PowerSource::Attributes::BatChargeLevel::Set(
        /* endpoint */ 1,
        /* value */ level  // 0=OK, 1=Warning, 2=Critical
    );
}
```

#### Step 6: CMakeLists.txt Updates
```cmake
# Enable Matter support
set(CHIP_ROOT ${ZEPHYR_CONNECTEDHOMEIP_MODULE_DIR})
include(${CHIP_ROOT}/config/nrfconnect/app/enable-gnu-std.cmake)

# Include Matter common source
include(${ZEPHYR_NRF_MODULE_DIR}/samples/matter/common/cmake/source_common.cmake)
include(${ZEPHYR_NRF_MODULE_DIR}/samples/matter/common/cmake/data_model.cmake)
include(${ZEPHYR_NRF_MODULE_DIR}/samples/matter/common/cmake/zap_helpers.cmake)

ncs_get_zap_parent_dir(ZAP_PARENT_DIR)

target_include_directories(app PRIVATE
    src
    ${ZAP_PARENT_DIR}
)

target_sources(app PRIVATE
    src/main.cpp              # Convert to C++
    src/app_task.cpp
    src/temperature_sensor.cpp
    src/battery.c             # Keep as C
)

ncs_configure_data_model()
```

### Phase 2.2: Testing & Validation

#### Commissioning Test
1. Build and flash firmware
2. Use chip-tool or mobile app (Apple Home, Google Home)
3. Commission device over BLE
4. Verify Thread network join
5. Read temperature attribute
6. Read battery attributes

#### Power Measurement
1. Measure current in active mode
2. Measure current in sleep mode (after reporting)
3. Optimize sleep intervals
4. Target: <100µA average current

#### Functional Tests
- [ ] Temperature updates every minute
- [ ] Battery level updates
- [ ] Attribute subscriptions work
- [ ] Device survives network disruption
- [ ] Deep sleep on critical battery
- [ ] OTA update capability (future)

### Phase 2.3: Integration with Existing Code

#### Migrate from C to C++
**Files to rename:**
- `src/main.c` → `src/main.cpp`

**Keep C for:**
- `src/battery.c` (wrap with `extern "C"` in header)

**Update:**
```cpp
// In battery.h
#ifdef __cplusplus
extern "C" {
#endif

int battery_init(void);
int battery_read_voltage(int32_t *voltage_mv);
// ... rest of API

#ifdef __cplusplus
}
#endif
```

#### Preserve Battery Monitoring
- Keep existing battery.c/h
- Call from Matter app task
- Update Matter attributes with battery state

### Files Checklist

**New files:**
- [ ] `Kconfig` - Matter configuration
- [ ] `Kconfig.sysbuild` - Multi-image build
- [ ] `sysbuild.conf` - Bootloader settings
- [ ] `src/chip_project_config.h` - CHIP config
- [ ] `src/temperature_sensor.zap` - Data model
- [ ] `src/app_task.cpp` - Main app logic
- [ ] `src/app_task.h` - Header
- [ ] `src/temperature_sensor.cpp` - Temp sensor driver
- [ ] `src/temperature_sensor.h` - Header
- [ ] `pm_static.yml` - Partition manager (optional)

**Modified files:**
- [ ] `prj.conf` - Add Matter configs
- [ ] `CMakeLists.txt` - Matter build integration
- [ ] `nrf54l15dk_nrf54l15_cpuapp.overlay` - Add temp sensor
- [ ] `src/main.c` → `src/main.cpp` - Convert to C++
- [ ] `src/battery.h` - Add extern "C" wrapper

**Reference:**
- Use `nrf54_matter` as template
- Nordic Matter samples: `ncs/samples/matter/`
- Matter spec: Temperature Sensor device type

---

## Refactoring Ideas

### **ADC Driver Optimization (Long-term)**
Consider switching from Zephyr ADC API to direct nrfx SAADC driver API for lower overhead, better power efficiency, and more control. Only pursue if profiling shows Zephyr ADC overhead is significant.

**Reference**: [Nordic Academy - Choosing between Zephyr ADC API and nrfx SAADC driver API](https://academy.nordicsemi.com/courses/nrf-connect-sdk-intermediate/lessons/lesson-6-analog-to-digital-converter-adc/topic/choosing-between-zephyr-adc-api-and-nrfx-saadc-driver-api/)

---

## Next Steps / Roadmap

**Phase 1 - Battery Monitoring (Current):**
- ✅ Basic ADC battery voltage reading
- ✅ Battery state detection
- ✅ Deep sleep on critical battery
- ✅ Device tree macros for ADC
- ✅ ADC calibration
- ✅ Proper voltage conversion with helpers
- ✅ Overflow protection
- ✅ GPIO-controlled voltage divider
- ✅ Deferred logging
- ✅ Disabled unused peripherals
- ✅ Improved CMakeLists.txt organization

**Phase 2 - Matter Protocol Integration:**
- Add Matter support (Temperature Sensor device type)
- Use internal die temperature sensor for initial testing
- Configure as Matter Temperature Measurement device (Device Type 0x0302)
- Implement Thread networking (Sleepy End Device)
- Add battery power source cluster
- Test commissioning and reporting

**Phase 3 - Sensor Integration:**
- Add I2C sensor integration (FDC2x1x capacitive moisture sensor)
- Replace die temperature with actual sensor readings
- Add custom Matter cluster for soil moisture
- Periodic measurements with RTC wakeup

**Phase 4 - Advanced Features:**
- OTA updates via Matter
- Advanced power optimization
- Multiple sensor support

---

---

## Notes

- This project is based on comparison with `nrf54_matter` (Matter Weather Station) reference implementation
- nrf54_matter targets nRF5340 (Thingy:53), but patterns are applicable to nRF54L15
