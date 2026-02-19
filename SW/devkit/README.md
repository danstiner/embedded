# BL54L15u DevKit

Sample application for the BL54L15u development board. Tests GPIO, LEDs, and button input, reads battery voltage and SoC% via the nPM1304 PMIC, and broadcasts both over BTHome BLE advertising.

## Build Instructions

> Run all commands from `SW/devkit/`.

### Prerequisites
- nRF Connect SDK v3.2 or later

### Build

```bash
west build -b bl54l15u_devkit@2026v1/nrf54l15/cpuapp -- -DBOARD_ROOT=$(pwd)/..
```

Add `--pristine` (or `-p`) to force a clean rebuild.

### Release build

For production, overlay `prj_release.conf` to extend the measurement interval to 5 minutes and strip logging:

```bash
west build -b bl54l15u_devkit@2026v1/nrf54l15/cpuapp -p \
  --extra-conf prj_release.conf \
  -- -DBOARD_ROOT=$(pwd)/..
```

### Flash

```bash
west flash
```

For a full chip erase before flashing (required on first flash of a new board):
```bash
west flash --erase
```

### Monitor (RTT)

Logs go to RTT by default. Connect using nRF Connect for VS Code → RTT, or `JLinkRTTViewer`.

### OTA update

Build a new image, then flash it wirelessly using the SMP BLE transport:
```bash
uv run ../ota.py flash
```

After verifying the new firmware boots correctly, confirm it permanently:
```bash
uv run ../ota.py confirm --target <BLE-address>
```
