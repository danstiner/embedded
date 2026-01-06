# nRF54 Humidity Sensor

Low power sensor for relative humidity, temperature, and water leaks utilizing the nRF54L15 microcontroller.

## Hardware Requirements

### Development Board
- nRF54L15 DK

## Build Instructions

### Prerequisites
- nRF Connect SDK v2.6.0 or later installed

### Builds

**Debug build** (with logging and console):

The nRF54L15 has enough internal storage (1524KB RRAM) that in release mode we can fit both A/B boot partitions internally, no external flash chip is needed.

```bash
west build -b nrf54l15dk/nrf54l15/cpuapp -p
```

**Release build** (optimized for low power):
```bash
west build -b nrf54l15dk/nrf54l15/cpuapp -p -- \
  -DEXTRA_CONF_FILE=prj_release.conf \
  -DEXTRA_DTC_OVERLAY_FILE=boards/nrf54l15dk_nrf54l15_cpuapp_release.overlay
```

**Production build** (Enables flash protection)

```bash
west build -b nrf54l15dk/nrf54l15/cpuapp -p -- \
  -DEXTRA_CONF_FILE=prj_release.conf \
  -DEXTRA_DTC_OVERLAY_FILE=boards/nrf54l15dk_nrf54l15_cpuapp_release.overlay \
  -DEXTRA_CONF_FILE=prj_production.conf
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
