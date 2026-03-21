# BL54L15u DevKit

Sample application for the BL54L15u development board. Tests GPIO, LEDs, and button input, reads battery voltage and SoC% via the nPM1304 PMIC, and broadcasts both over BTHome BLE advertising.

## Build Instructions

> Run all commands from `SW/devkit/`.

### Prerequisites
- nRF Connect SDK v3.2 or later

### Builds

Base build:
```bash
west build -b bl54l15u_devkit@2026v2/nrf54l15/cpuapp -p -- -DBOARD_ROOT=..
```

Release mode with reduced power use:
```bash
west build -b bl54l15u_devkit@2026v2/nrf54l15/cpuapp -p -- -DBOARD_ROOT=.. -DEXTRA_CONF_FILE=prj_extra_release.conf
```

### KMU Provisioning

Provision signing keys to the hardware KMU before first boot. See [`keys/README.md`](../keys/README.md) for details.

```sh
(cd .. && west ncs-provision upload -i keys/provision-dev.yml)
```

### Flash

```sh
west flash
```
