# nRF54 Soil Moisture Sensor

Ultra-low power soil moisture monitoring system utilizing an nRF54L15.

## Hardware Requirements

### Development Board
- nRF54L15 DK (PCA10156)

### Battery Monitoring Circuit
```
Battery+ ──[LDO]── VDD (powers nRF54L15)
           │
          [R]
           │
           ├─── P0.00 (ADC AIN0)
           │
          [R]
           │
          GND
```

1:2 voltage divider measures up to 4.2V battery. Current drain = Vbat/(2×R).

### Optional
- LED on GPIO (check DK schematic for led0 alias)
- Battery (3.0V - 4.2V Li-ion or similar)

## Build Instructions

### Prerequisites
- nRF Connect SDK v2.6.0 or later installed

### Build

**Debug build** (with logging and console):
```bash
west build -b nrf54l15dk/nrf54l15/cpuapp
```

**Release build** (optimized for lowest power):
```bash
west build -b nrf54l15dk/nrf54l15/cpuapp -- -DEXTRA_CONF_FILE=prj_release.conf
```

**Internal build** (only uses internal storage)

For the nRF54L15, we can skip external storage and use the internal 1.5MB RRAM for both boot slots.

To enable this, set the ``FILE_SUFFIX`` CMake option to ``internal``.
```bash
west build -b nrf54l15dk/nrf54l15/cpuapp -- -DFILE_SUFFIX=internal
```

### Flash
```bash
west flash
```

### Monitor
```bash
# Linux
screen /dev/ttyACM0 115200

# macOS (find port with: ls /dev/tty.usbmodem*)
screen /dev/tty.usbmodem0010577860871 115200
```

## Power Management

### Normal Operation (Battery Good)

The device operates in a periodic measurement cycle:
1. **Boot/Wakeup**: Initialize peripherals and check retained RAM
2. **Measure**: Read temperature and battery voltage (~5-10ms active)
3. **Sleep**: Enter System OFF mode for 300 seconds (<5µA)
4. **Repeat**: GRTC timer wakes device for next measurement

## Configuration

### Measurement Interval

Edit `prj.conf` or `prj_release.conf`:
```
CONFIG_APP_MEASUREMENT_INTERVAL_SEC=300   # 5 minutes
```

Or override via Kconfig menuconfig.

### Voltage Divider

Edit `nrf54l15dk_nrf54l15_cpuapp.overlay`:
```dts
vbatt {
    output-ohms = <22000000>;  /* R (lower resistor) */
    full-ohms = <44000000>;    /* 2×R (total) */
};
```

### ADC Pin

Edit `nrf54l15dk_nrf54l15_cpuapp.overlay`:
```dts
&adc {
    channel@0 {
        zephyr,input-positive = <NRF_SAADC_AIN0>;  /* P0.00 - change as needed */
    };
};
```

## Project Structure

```
nrf54_soil/
├── CMakeLists.txt                         # Build configuration
├── Kconfig                                # Application Kconfig options
├── prj.conf                               # Debug config (full logging)
├── prj_release.conf                       # Release config (power optimized)
├── nrf54l15dk_nrf54l15_cpuapp.overlay    # Device tree (ADC, retention RAM)
├── src/
│   ├── main.c                            # Main app with System OFF loop
│   ├── battery.c                         # Battery monitoring
│   ├── battery.h                         # Battery API
│   ├── retained.c                        # Retained RAM management
│   └── retained.h                        # Retained data structure
├── VERSION                                # Version tracking
└── README.md                             # This file
```

## Troubleshooting

### ADC reads 0V or wrong voltage
- Check voltage divider resistors (should be 100K + 100K)
- Verify ADC pin connection (P0.00 = AIN0)
- Measure actual voltage at ADC pin (should be battery/2)
- Check battery is connected

### Immediate deep sleep on boot
- Battery voltage is below 2.7V
- ADC calibration issue
- Check voltage divider calculation in code

### No LED blinking
- Check if DK has led0 alias defined
- LED feature is optional, won't affect functionality
- Check DK schematic for LED GPIO

### Build errors
- Ensure nRF Connect SDK v2.6.0+ is installed
- Verify ZEPHYR_BASE environment variable
- Try clean build: `west build -p`

## Power Consumption

### System OFF Deep Sleep Mode

**Release build** (prj_release.conf) with 300 second measurement interval:
- **Sleep**: <5µA (System OFF mode)
- **Active**: ~1-2mA for ~10ms (CPU + ADC + temperature sensor)
- **Average**: ~5-10µA overall
- **Voltage divider leakage**: 95nA (22MΩ resistors)

**Debug build** (prj.conf):
- **Sleep**: <5µA (System OFF mode)
- **Active**: ~3mA for ~50ms (CPU + ADC + UART logging)
- **Average**: ~10-20µA overall

### Memory Usage

- **Debug build**: 61KB ROM, 14KB RAM
- **Release build**: 46KB ROM, 11KB RAM (25% smaller)

### Battery Life Estimates

With 2000mAh Li-ion battery and 300 second (5 minute) measurement interval:

**Release build**:
- Current draw: ~8µA average
- **Battery life: ~25 years** (limited by battery self-discharge, not system consumption)

**Debug build** (for development):
- Current draw: ~15µA average
- **Battery life: ~15 years**

Real-world battery life will be limited by battery self-discharge (~2-3% per month) rather than system power consumption.

## References

- [nRF54L15 Product Specification](https://infocenter.nordicsemi.com/topic/ps_nrf54l15/index.html)
- [Zephyr ADC API](https://docs.zephyrproject.org/latest/hardware/peripherals/adc.html)
- [Zephyr Power Management](https://docs.zephyrproject.org/latest/services/pm/index.html)
