# BL54L15u DevKit

Sample application for the BL54L15u development board. Tests GPIO, LEDs, and button input, reads battery voltage and SoC% via the nPM1304 PMIC, and broadcasts both over BTHome BLE advertising.

## Build Instructions

> Run all commands from `SW/devkit/`.

### Prerequisites
- nRF Connect SDK v3.2 or later

### Build

```bash
west build -b bl54l15u_devkit@2026v1/nrf54l15/cpuapp -- -DBOARD_ROOT=..
```

Add `--pristine` (or `-p`) to force a clean rebuild.

### Release build

For production, overlay `prj_release.conf` to extend the measurement interval to 5 minutes and strip logging:

```bash
west build -b bl54l15u_devkit@2026v1/nrf54l15/cpuapp -p \
  --extra-conf prj_release.conf \
  -- -DBOARD_ROOT=..
```

### Production build

Signs with the production key, enables FPROTECT and APPROTECT:

```bash
west build -b bl54l15u_devkit@2026v1/nrf54l15/cpuapp -p \
  --extra-conf prj_release.conf \
  -- -DBOARD_ROOT=.. -DFILE_SUFFIX=production
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
