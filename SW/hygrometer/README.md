# nRF54 Humidity Sensor

Low power sensor for relative humidity, temperature, and water leaks utilizing the nRF54L15 microcontroller.

## Hardware

The `bl54l15u_hygrometer` board has two hardware revisions:

- **2026v4** (default): Resistive water-leak sensor, SHT4x, buzzer, CR2 lithium battery
- **2026v3**: SHT4x, optional BME688/STCC4, nPM2100 PMIC + 2×AAA alkaline

This project also can be used with the BL54L15u DevKit.

## Build Instructions

Debug build advertising over BLE in the BTHome format, with RTT logging:
```sh
west build -b bl54l15u_hygrometer/nrf54l15/cpuapp -p -- -DBOARD_ROOT=.. -DEXTRA_CONF_FILE=prj_extra_rtt.conf -Dmcuboot_EXTRA_CONF_FILE=$(pwd)/sysbuild/mcuboot_extra_rtt.conf
```

Release build with reduced power use:
```sh
west build -b bl54l15u_hygrometer/nrf54l15/cpuapp -p -- -DBOARD_ROOT=.. -DEXTRA_CONF_FILE=prj_extra_release.conf
```

Matter over Thread release build (instead of BTHome BLE advertising):

```sh
west build -b bl54l15u_hygrometer/nrf54l15/cpuapp -p -- -DBOARD_ROOT=.. -DEXTRA_CONF_FILE="prj_extra_release.conf;prj_extra_matter.conf" -DSB_EXTRA_CONF_FILE=sysbuild_extra_matter.conf -DEXTRA_DTC_OVERLAY_FILE=boards/matter.overlay
```

## Deployment

### KMU Provisioning

Provision signing keys to the hardware KMU before first boot. See [`keys/README.md`](../keys/README.md) for details.

```sh
(cd .. && west ncs-provision upload -i keys/provision-dev.yml)
```

### Flashing

```bash
west flash
```

## BTHome

### OTA update

Build a new image, then flash it wirelessly using the SMP BLE transport:
```bash
uv run ../ota.py flash --confirm
```

## Matter

### Provisioning

Per-device identity and other information must be flashed to the factory-data partition using the
provisioning tool [`../tools/matter/provisioning/provision.py`](../tools/matter/provisioning/provision.py):

```sh
python ../tools/matter/provisioning/provision.py --build-dir build --flash
```

It reads the product ID / names / partition offset from the build, assigns a sequential
serial (`SN-0001`, …), randomizes discriminator/passcode/salt/unique-ID, and writes the
hex, QR `.png`, onboarding `.txt`, and a `provisioning_log.csv` to the gitignored
`SW/tools/matter/provisioning/history/`. `--flash` programs the `factory_data` partition. To re-identify
an already-paired unit, re-provision it, run `matter factoryreset` on the device console, and
remove the stale device entry from the controller.

Commissioning, OTA-over-Matter, and Matter/Thread troubleshooting are board-agnostic and
documented in the shared guide: [`../docs/matter.md`](../docs/matter.md).

## References

- [nRF54L15 Product Specification](https://infocenter.nordicsemi.com/topic/ps_nrf54l15/index.html)
- [Zephyr ADC API](https://docs.zephyrproject.org/latest/hardware/peripherals/adc.html)
- [Zephyr Power Management](https://docs.zephyrproject.org/latest/services/pm/index.html)
