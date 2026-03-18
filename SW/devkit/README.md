# BL54L15u DevKit

Sample application for the BL54L15u development board. Tests GPIO, LEDs, and button input, reads battery voltage and SoC% via the nPM1304 PMIC, and broadcasts both over BTHome BLE advertising.

## Build Instructions

> Run all commands from `SW/devkit/`.

### Prerequisites
- nRF Connect SDK v3.2 or later

### Build

```bash
west build -b bl54l15u_devkit@2026v2/nrf54l15/cpuapp -- -DBOARD_ROOT=..
```

Add `--pristine` (or `-p`) to force a clean rebuild.

### Release build

Strips logging and reduces power consumption:

```bash
west build -b bl54l15u_devkit@2026v2/nrf54l15/cpuapp -p \
  -- -DBOARD_ROOT=.. \
  -DEXTRA_CONF_FILE=prj_extra_release.conf \
  -Dmcuboot_EXTRA_CONF_FILE=sysbuild/mcuboot_extra_release.conf
```

### Production build

Signs with the production key, enables FPROTECT and APPROTECT:

```bash
west build -b bl54l15u_devkit@2026v2/nrf54l15/cpuapp -p \
  -- -DBOARD_ROOT=.. \
  -DEXTRA_CONF_FILE=prj_extra_production.conf \
  -Dmcuboot_EXTRA_CONF_FILE=sysbuild/mcuboot_extra_production.conf \
  -DSB_EXTRA_CONF_FILE=sysbuild_extra_production.conf
```

### Flash

```bash
west flash
```

### KMU Provisioning

Provision signing keys to the hardware KMU before first boot. See [`keys/README.md`](../keys/README.md) for details.

```bash
# From SW/
west ncs-provision upload -i keys/provision-dev.yml
```
