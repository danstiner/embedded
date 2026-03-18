# Soil Moisture Sensor

Soil moisture sensor firmware for the BL54L15u DevKit. Reads capacitance from a TI FDC1004 sensor, converts it to a moisture percentage, and broadcasts the value over BLE using the BTHome v2 protocol. Also reports battery voltage from the on-board NPM1304 PMIC.

## Hardware

- **MCU:** nRF54L15 (BL54L15u module)
- **Capacitance sensor:** TI FDC1004 at I2C address 0x50
- **PMIC:** Nordic NPM1304 at I2C address 0x6B
- **Debug:** SEGGER RTT (no UART)

### Board Revisions

The BL54L15u DevKit has two hardware revisions with different I2C bus routing:

| Bus   | 2026v1                                | 2026v2 (default)                      |
|-------|---------------------------------------|---------------------------------------|
| I2C20 | NPM1304 PMIC only                    | NPM1304 PMIC + Qwiic J1 (shared)     |
| I2C21 | Qwiic J1 (SDA=P1.05 SCL=P1.04)       | Qwiic J8 (SDA=P1.05 SCL=P1.04)       |
| I2C22 | Qwiic J8 (SDA=P0.02 SCL=P0.04)       | *does not exist*                      |

### Pinout

| Function         | Pin   | Peripheral      | Connector |
|------------------|-------|-----------------|-----------|
| PMIC SDA         | P1.07 | I2C20           | —         |
| PMIC SCL         | P1.08 | I2C20           | —         |
| Qwiic SDA        | P1.05 | I2C21           | J1 (v1) / J8 (v2) |
| Qwiic SCL        | P1.04 | I2C21           | J1 (v1) / J8 (v2) |
| Qwiic J8 SDA     | P0.02 | I2C22 (v1 only) | Qwiic J8  |
| Qwiic J8 SCL     | P0.04 | I2C22 (v1 only) | Qwiic J8  |
| Button SW1       | P0.00 | GPIO            | —         |
| Red LED          | P2.08 | GPIO            | —         |

The FDC1004 connects to the **Qwiic J1** connector via a standard Qwiic cable (VDD, GND, SDA, SCL). Power is supplied through NPM1304 LDO1 (load switch), enabled at boot via devicetree.

### Power Configuration

The board overlay configures the NPM1304 regulators at boot via devicetree:

- **BUCK2:** Set to 3.0V (`regulator-init-microvolt`), enabled at boot.
- **LDO1:** Enabled at boot (`regulator-boot-on`) to power the FDC1004 via Qwiic J1.

### FDC1004 Channel Configuration

The default overlay configures measurement channel 0:

- **CHA:** CIN2 (positive input)
- **CHB:** CAPDAC (internal offset capacitor)
- **CAPDAC:** 0 (no offset)

Edit the revision-specific overlay (`boards/bl54l15u_devkit_nrf54l15_cpuapp_2026v1.overlay` or `_2026v2.overlay`) to add more channels or change the CAPDAC value after probe characterization.

## Building

Requires nRF Connect SDK v3.2 or later. The board definition lives in `SW/boards/` (shared across apps).

```sh
cd soil_sensor
west build -b bl54l15u_devkit@2026v2/nrf54l15/cpuapp -p -- -DBOARD_ROOT=..
```

To build for the v1 hardware revision:

```sh
west build -b bl54l15u_devkit@2026v1/nrf54l15/cpuapp -p -- -DBOARD_ROOT=..
```

The default revision is `2026v2`, but the `@<revision>` qualifier is always required when passing `-DBOARD_ROOT`.

### Release build

Strips logging, extends measurement interval to 60s, and reduces power consumption:

```sh
west build -b bl54l15u_devkit@2026v2/nrf54l15/cpuapp -p \
  -- -DBOARD_ROOT=.. \
  -DEXTRA_CONF_FILE=prj_extra_release.conf \
  -Dmcuboot_EXTRA_CONF_FILE=sysbuild/mcuboot_extra_release.conf
```

### Production build

Signs with the production key, enables FPROTECT and APPROTECT:

```sh
west build -b bl54l15u_devkit@2026v2/nrf54l15/cpuapp -p \
  -- -DBOARD_ROOT=.. \
  -DEXTRA_CONF_FILE=prj_extra_production.conf \
  -Dmcuboot_EXTRA_CONF_FILE=sysbuild/mcuboot_extra_production.conf \
  -DSB_EXTRA_CONF_FILE=sysbuild_extra_production.conf
```

### Flashing

```sh
west flash
```

On first flash (or after changing NFC pin configuration or KMU keys), a full chip erase is required:

```sh
west flash --erase
```

### KMU Provisioning

Provision signing keys to the hardware KMU before first boot. See [`keys/README.md`](../keys/README.md) for details.

```sh
# From SW/
west ncs-provision upload -i keys/provision-dev.yml   # dev device
west ncs-provision upload -i keys/provision-prod.yml  # production device
```

### Viewing RTT Logs

```sh
JLinkRTTClient
```

Expected output:

```
[00:00:00.000,000] <inf> soil_sensor: Soil Sensor starting
[00:00:00.010,000] <inf> fdc1004: FDC1004 found (mfg=0x5449 dev=0x1004)
[00:00:00.020,000] <inf> fdc1004: CH0: CHA=2 CHB=4 CAPDAC=0
[00:00:00.100,000] <inf> soil_sensor: BTHome advertising started
[00:00:00.200,000] <inf> soil_sensor: Capacitance: 12.345678 pF -> Moisture: 29.38 %
[00:00:00.200,000] <inf> soil_sensor: Battery: 3.100 V
```

## Calibration

The moisture percentage is a linear mapping from capacitance:

```
moisture % = (C - CAP_DRY) / (CAP_WET - CAP_DRY) * 100
```

Calibration constants are configurable via Kconfig (values in femtofarads):

| Kconfig option         | Default | Description                          |
|-----------------------|---------|--------------------------------------|
| `CONFIG_SOIL_CAP_DRY_FF` | 5000    | Dry soil capacitance (5000 = 5.0 pF)    |
| `CONFIG_SOIL_CAP_WET_FF` | 124500  | Saturated soil capacitance (124500 = 124.5 pF) |

Override at build time:

```sh
west build -b bl54l15u_devkit@2026v2/nrf54l15/cpuapp -p always -- \
  -DBOARD_ROOT=.. -DCONFIG_SOIL_CAP_DRY_FF=8000 -DCONFIG_SOIL_CAP_WET_FF=25000
```

Or add to `prj.conf`:

```
CONFIG_SOIL_CAP_DRY_FF=8000
CONFIG_SOIL_CAP_WET_FF=25000
```

## BLE Protocol

The device advertises as **"Soil Sensor"** using non-connectable BTHome v2 packets. Compatible with Home Assistant and other BTHome receivers.

Advertised objects:

| Object     | BTHome ID | Type   | Factor | Unit |
|-----------|-----------|--------|--------|------|
| Moisture   | 0x14      | uint16 | 0.01   | %    |
| Voltage    | 0x0C      | uint16 | 0.001  | V    |

Advertising interval: 1s (slow). Measurement interval: 60s.

## DFU (Over-the-Air Updates)

The firmware includes MCUboot and MCUmgr for over-the-air updates via BLE SMP. To avoid increasing idle power consumption, DFU mode is triggered by a button press rather than always advertising a connectable service.

### Entering DFU Mode

1. Press **SW1** on the board. The red LED turns on and the device switches to connectable advertising with both BTHome data and the SMP service UUID (in the scan response).
2. Sensor reads and BTHome data updates continue during DFU — the device remains visible to Home Assistant.
3. The device is discoverable by `smpmgr` or nRF Connect for firmware upload.
4. DFU mode **times out after 5 minutes** and returns to non-connectable BTHome automatically.
5. Press **SW1** again to exit DFU mode manually.

### OTA Flashing

The easiest way to flash OTA is with the `ota.py` script (requires [uv](https://docs.astral.sh/uv/)):

```sh
cd soil_sensor
uv run ../ota.py flash                    # upload build/dfu_application.zip
uv run ../ota.py confirm --target <addr>  # make permanent
uv run ../ota.py verify                   # check device image state
uv run ../ota.py scan                     # list SMP devices
```

This auto-installs `smpmgr`, uploads `build/dfu_application.zip`, marks it for test boot, and resets the device.

### Manual smpmgr Commands

```sh
# Upload, mark for test boot, and reset (all-in-one)
smpmgr --ble "Soil Sensor" upgrade build/dfu_application.zip

# After verifying the new firmware, confirm it (enter DFU mode again first)
smpmgr --ble "Soil Sensor" image state-write --confirm
```

### Notes

- The first flash must be via J-Link (`west flash`). OTA is only available after MCUboot and the SMP-enabled firmware are running.
- The DFU package (`build/dfu_application.zip`) is generated automatically by the build system when `CONFIG_BOOTLOADER_MCUBOOT=y`.

## Project Structure

```
SW/
├── west.yml                       # West manifest (pins NCS v3.1.1)
├── ota.py                         # OTA DFU script (uv run ota.py)
├── boards/                        # Shared board definitions
│   └── nordic/bl54l15u_devkit/
│       ├── board.yml              # Board metadata + revision config
│       ├── revision.cmake         # Custom revision validation
│       ├── bl54l15u_devkit_nrf54l15_cpuapp.dts          # Base DTS (v2 default)
│       ├── bl54l15u_devkit_nrf54l15_cpuapp_2026v1.overlay  # v1: adds I2C22
│       └── bl54l15u_devkit-pinctrl.dtsi
└── soil_sensor/
    ├── CMakeLists.txt             # Build config (BOARD_ROOT, DTS_ROOT, ZEPHYR_EXTRA_MODULES)
    ├── Kconfig                    # App Kconfig (calibration constants)
    ├── prj.conf                   # Kconfig (BLE broadcaster, I2C, sensor, MCUboot)
    ├── sysbuild.conf              # Sysbuild MCUboot enable
    ├── sysbuild/
    │   └── mcuboot.conf           # MCUboot size opts + KMU key slots
    ├── boards/
    │   ├── bl54l15u_devkit_nrf54l15_cpuapp.overlay         # Common: BUCK2/LDO1 power
    │   ├── bl54l15u_devkit_nrf54l15_cpuapp_2026v1.overlay  # v1: FDC1004 on I2C21
    │   └── bl54l15u_devkit_nrf54l15_cpuapp_2026v2.overlay  # v2: FDC1004 on I2C20
    ├── dts/bindings/sensor/
    │   └── ti,fdc1004.yaml        # Devicetree binding for FDC1004
    ├── drivers/
    │   ├── CMakeLists.txt         # Module CMake entry
    │   ├── Kconfig                # Module Kconfig entry
    │   ├── zephyr/module.yml      # Zephyr module descriptor
    │   └── sensor/fdc1004/
    │       ├── CMakeLists.txt
    │       ├── Kconfig
    │       ├── fdc1004.h          # Register defs, custom sensor channels
    │       └── fdc1004.c          # Driver: init, fetch, channel_get
    └── src/
        └── main.c                 # App: read sensors, BTHome advertising, DFU mode
```
